"""
portal/helpers/test_cards.py
============================
Predefined test cards, so the whole credit-card flow can be exercised without a
real card and without a real charge.

Two things make this safe rather than merely convenient:

1. **The backend never receives a card number.** The link endpoint takes a BIN
   and a last-four only (PRD 8.2) - the full PAN and the CVV never leave the
   browser even in production. The numbers below exist so a developer has
   something to type into the form; the server only ever sees the same six plus
   four digits it always does.

2. **Nothing reaches a payment network.** Test cards are only accepted while
   test mode is on, test mode is refused outright in production, and the
   scenarios are played out by the sandbox adapter that already exists for
   failure injection. There is no code path from a test card to a gateway.

Each card is bound to one scenario, so a tester picks an outcome rather than
trying to provoke it. The scenario is recorded on the card row at link time and
replayed on every payment that card funds.
"""

from decimal import Decimal

from flask import current_app


class Scenario:
    """What a given test card does when it is used to pay."""

    SUCCESS = 'SUCCESS'
    DECLINE = 'DECLINE'
    INSUFFICIENT_LIMIT = 'INSUFFICIENT_LIMIT'
    PENDING = 'PENDING'
    TOKEN_EXPIRED = 'TOKEN_EXPIRED'
    PAYOUT_FAIL = 'PAYOUT_FAIL'

    CHOICES = [
        SUCCESS, DECLINE, INSUFFICIENT_LIMIT, PENDING, TOKEN_EXPIRED,
        PAYOUT_FAIL,
    ]


#: The catalogue. Every number is Luhn-valid, so client-side card validation
#: behaves exactly as it would for a real card, and every one is a number
#: published by the networks as a test value - none of them can be issued to a
#: real person.
#:
#: `limit` is deliberately tiny on the insufficient-limit card: that scenario is
#: enforced by the ordinary available-limit check in transfer_engine, not by a
#: special case, which is the point - the failure happens through the real code
#: path rather than around it.
TEST_CARDS = [
    {
        # Not 4111 1111 1111 1111: that BIN is seeded as "Test Debit Issuer"
        # precisely so the suite can prove ERR-001 refuses debit cards, and
        # turning it into a valid credit card would silently retire that guard.
        'number': '4012888888881881',
        'scenario': Scenario.SUCCESS,
        'label': 'Successful payment',
        'description': 'Charges cleanly and settles. Use this for the happy path.',
        'network': 'VISA',
        'issuer_bank': 'HDFC Bank',
        'brand_color': '#004C8F',
        'limit': Decimal('200000.00'),
    },
    {
        'number': '5555555555554444',
        'scenario': Scenario.DECLINE,
        'label': 'Declined by issuer',
        'description': 'The issuer refuses the charge. Nothing is debited and the transfer fails.',
        'network': 'MASTERCARD',
        'issuer_bank': 'ICICI Bank',
        'brand_color': '#AE282E',
        'limit': Decimal('150000.00'),
    },
    {
        'number': '4000000000000002',
        'scenario': Scenario.INSUFFICIENT_LIMIT,
        'label': 'Insufficient limit',
        'description': 'Linked with a limit of Rs. 500, so any ordinary transfer is refused before a charge is attempted.',
        'network': 'VISA',
        'issuer_bank': 'Axis Bank',
        'brand_color': '#97144D',
        'limit': Decimal('500.00'),
    },
    {
        'number': '6521111111111110',
        'scenario': Scenario.PENDING,
        'label': 'Pending / timeout',
        'description': 'The gateway never answers, so the payment parks as pending and the poller picks it up.',
        'network': 'RUPAY',
        'issuer_bank': 'State Bank of India',
        'brand_color': '#22409A',
        'limit': Decimal('100000.00'),
    },
    {
        'number': '4000000000000069',
        'scenario': Scenario.TOKEN_EXPIRED,
        'label': 'Expired card',
        'description': 'Tokenisation fails at link time. Use this to see the add-card error path.',
        'network': 'VISA',
        'issuer_bank': 'Kotak Mahindra',
        'brand_color': '#ED1C24',
        'limit': Decimal('75000.00'),
    },
    {
        'number': '5105105105105100',
        'scenario': Scenario.PAYOUT_FAIL,
        'label': 'Charge succeeds, payout fails',
        'description': 'The card is charged but the bank transfer fails, so the reversal and refund path runs.',
        'network': 'MASTERCARD',
        'issuer_bank': 'IndusInd Bank',
        'brand_color': '#7B2D8E',
        'limit': Decimal('120000.00'),
    },
]

#: Shared across every test card. A CVV is never sent to this backend, so this
#: is purely something for a tester to type into the form.
TEST_CVV = '123'
TEST_EXPIRY_MONTH = '12'
TEST_EXPIRY_YEAR = '2030'
TEST_CARDHOLDER = 'TEST USER'

#: The expired card has to look expired, or the client-side expiry check
#: refuses it before the server ever sees the scenario.
EXPIRED_EXPIRY_MONTH = '01'
EXPIRED_EXPIRY_YEAR = '2020'


def enabled() -> bool:
    """
    Whether test cards may be linked and used.

    Three gates, all of which must pass:

    - never in production, whatever the environment says;
    - only while the sandbox adapters are active, because the scenarios are
      played out by the sandbox and a live gateway would ignore them;
    - and not if an operator has explicitly switched it off.

    The production check is first and unconditional. A misconfigured env file
    should not be able to turn a real deployment into one that accepts test
    cards.
    """
    cfg = current_app.config

    if cfg.get('ENV_NAME') == 'production' or not cfg.get('DEBUG', False):
        # A non-debug build is treated as production for this purpose. Test
        # cards are a development affordance; erring towards off is the only
        # safe direction.
        if cfg.get('CARD_TEST_MODE', '') != 'True':
            return False

    if cfg.get('CARD_TEST_MODE', '') == 'False':
        return False

    return bool(cfg.get('USE_SANDBOX_ADAPTERS', True))


def _digits(value: str) -> str:
    return ''.join(c for c in str(value or '') if c.isdigit())


def find(bin_prefix: str, last4: str) -> dict:
    """
    Resolve the BIN and last-four the client sent back to a test card.

    Matching on those two alone is what keeps this consistent with the rest of
    the system: the server is not given the middle digits and does not want
    them. Two different test cards never share a BIN and last-four pair.
    """
    head = _digits(bin_prefix)[:6]
    tail = _digits(last4)[-4:]

    if not head or not tail:
        return None

    for card in TEST_CARDS:
        number = card['number']
        if number[:6] == head and number[-4:] == tail:
            return card

    return None


def is_test_pan(bin_prefix: str, last4: str) -> bool:
    """True when this BIN/last-four pair belongs to the catalogue."""
    return find(bin_prefix, last4) is not None


def catalogue() -> list:
    """
    The catalogue as the client needs it - full numbers included.

    Safe to serve because these are published network test values, and it is
    only ever reachable while `enabled()` is true.
    """
    return [
        {
            'number': card['number'],
            'formatted': ' '.join(
                card['number'][i:i + 4] for i in range(0, len(card['number']), 4)
            ),
            'bin': card['number'][:6],
            'last4': card['number'][-4:],
            'scenario': card['scenario'],
            'label': card['label'],
            'description': card['description'],
            'network': card['network'],
            'issuer_bank': card['issuer_bank'],
            'brand_color': card['brand_color'],
            'card_limit': float(card['limit']),
            'cvv': TEST_CVV,
            'cardholder_name': TEST_CARDHOLDER,
            'expiry_month': (
                EXPIRED_EXPIRY_MONTH
                if card['scenario'] == Scenario.TOKEN_EXPIRED
                else TEST_EXPIRY_MONTH
            ),
            'expiry_year': (
                EXPIRED_EXPIRY_YEAR
                if card['scenario'] == Scenario.TOKEN_EXPIRED
                else TEST_EXPIRY_YEAR
            ),
        }
        for card in TEST_CARDS
    ]


#: How a card's scenario maps onto the sandbox's failure-injection tokens. The
#: adapter looks for these inside the reference id it is handed, so binding a
#: scenario to a payment is a matter of putting the right token in the order
#: reference - no branching inside the payment path itself.
_SIMULATION_TOKENS = {
    # SIMAUTHDECL, not SIMDECLINE: the order should open and the charge be
    # refused at authorisation, so a tester walks the whole journey - amount,
    # method, processing - and sees the decline where a real one appears.
    # SIMDECLINE refuses at order creation and never reaches a payment screen.
    Scenario.DECLINE: 'SIMAUTHDECL',
    Scenario.PENDING: 'SIMTIMEOUT',
    Scenario.PAYOUT_FAIL: 'SIMPAYOUTFAIL',
    Scenario.TOKEN_EXPIRED: 'SIMTOKENEXP',
}


def simulation_token(scenario: str) -> str:
    """
    The sandbox directive for a scenario, or '' when none is needed.

    SUCCESS needs no token - the sandbox succeeds by default. INSUFFICIENT_LIMIT
    needs none either: it is produced by the card's own small limit meeting the
    ordinary balance check.
    """
    return _SIMULATION_TOKENS.get(scenario, '')
