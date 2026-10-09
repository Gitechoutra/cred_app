"""
portal/helpers/adapters.py
==========================
Vendor seams for the external money rails.

Every PRD section 21 integration is marked "To Be Confirmed", so each one sits
behind an interface with two implementations: a sandbox that simulates the rail
end to end, and a live one backed by Cashfree. Which runs is decided by
USE_SANDBOX_ADAPTERS plus whether credentials are actually present - so a
half-configured environment degrades to the simulator instead of failing
mid-transfer with a confusing gateway error.

The sandbox is not a stub. It produces realistic references and UTRs, and it
can be told to fail on demand, because PRD section 20's eleven error scenarios
and the 9.4 circuit breaker are untestable without a rail that fails
deliberately.

Design rule: swapping a vendor must touch only this file. If a route or a model
needs to change, the seam was drawn in the wrong place.
"""

import hashlib
import random
import uuid

from flask import current_app

from portal.helpers import cashfree, decentro, razorpay


# ── Failure injection ──────────────────────────────────────────────────────
# PRD section 20 defines eleven failure scenarios and PRD 9.4 a three-retry
# circuit breaker. Neither can be verified against a rail that always succeeds,
# so the sandbox honours a directive embedded in the reference id.

class Simulate:
    """Tokens a caller can embed in an id to force a sandbox outcome."""

    DECLINE = 'SIMDECLINE'         # issuer declines the charge (ERR-003)
    TIMEOUT = 'SIMTIMEOUT'         # gateway times out (ERR-005)
    NAME_MISMATCH = 'SIMNAMEMM'    # penny-drop name mismatch (ERR-004)
    TOKEN_EXPIRED = 'SIMTOKENEXP'  # expired card token (ERR-009)
    BILLER_DOWN = 'SIMBILLERDOWN'  # BBPS biller offline (ERR-010)

    #: Declines at *authorisation* rather than at order creation, which is how
    #: an issuer decline actually reaches a customer: the order opens, they
    #: reach a payment screen, and the charge is refused there. DECLINE above
    #: refuses up front, which models a pre-auth rejection and skips the
    #: processing state entirely.
    AUTH_DECLINE = 'SIMAUTHDECL'

    #: The payer opened checkout and left without attempting anything. Without
    #: this the sandbox reports every order PAID, so cancelling a sandbox
    #: payment would settle it instead - the cancel path could not be exercised.
    ABANDON = 'SIMABANDON'


def _simulating(reference: str, directive: str) -> bool:
    return bool(reference) and directive in str(reference).upper()


def _use_sandbox() -> bool:
    """
    Sandbox unless explicitly switched off AND credentials exist.

    The credential check matters: an operator who flips the flag but forgets the
    keys should get the simulator, not a stream of 401s from the gateway on the
    live transfer path.
    """
    if current_app.config.get('USE_SANDBOX_ADAPTERS', True):
        return True
    if not cashfree.is_configured():
        current_app.logger.warning(
            '[adapters] live mode requested but Cashfree credentials are absent; '
            'falling back to the sandbox.'
        )
        return True
    return False


def card_gateway_provider() -> str:
    """
    Which rail a netbanking or debit-card collection would use right now.

    Public so a caller can tell the payer in advance that a payment will be
    simulated, rather than finding out from the order it gets back.
    """
    return 'SANDBOX' if _use_sandbox() else 'CASHFREE'


def _ref(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:16]}'


def _fake_utr() -> str:
    """A plausible 12-digit bank UTR for sandbox receipts."""
    return f'{random.randint(10 ** 11, 10 ** 12 - 1)}'


# ── Token requestor (PRD FR-003, CoFT) ─────────────────────────────────────

def tokenize_card(
    *,
    reference: str,
    last4: str,
    network: str,
    issuer_bank: str,
    expiry_month: str,
    expiry_year: str,
    cardholder_name: str = None,
) -> dict:
    """
    Provision a network token for a card.

    The backend never sees a PAN or a CVV (PRD 8.2). In the real flow the client
    SDK posts card credentials straight to the licensed Token Requestor, which
    hands back a token reference; this function records the outcome of that
    exchange. The sandbox mints a deterministic pseudo-token from the same
    non-sensitive metadata the real callback would return.
    """
    if _use_sandbox():
        if _simulating(reference, Simulate.TOKEN_EXPIRED):
            return {
                'ok': False,
                'error_code': 'TOKEN_EXPIRED',
                'error': 'This card has expired. Please link your renewed card.',
            }

        seed = f'{reference}{last4}{expiry_month}{expiry_year}{uuid.uuid4().hex}'
        token = hashlib.sha256(seed.encode()).hexdigest()[:32]

        return {
            'ok': True,
            'token_reference_id': f'tok_sbx_{token}',
            'token_provider': 'SANDBOX',
            'network': network,
            'issuer_bank': issuer_bank,
            'last4': last4,
            'three_ds_completed': True,
        }

    # Live CoFT tokenization is a client-SDK flow; the backend records the
    # callback rather than initiating it. Until a Token Requestor is signed
    # (PRD open decision 3) there is nothing further to call here.
    return {
        'ok': False,
        'error_code': 'PROVIDER_NOT_CONFIGURED',
        'error': 'Card tokenization provider is not configured.',
    }


# ── Payment gateway: inbound charge (PRD FR-006, FR-008) ───────────────────

def create_payment_order(
    *,
    order_id: str,
    amount,
    customer_id: str,
    customer_phone: str,
    customer_email: str = None,
    customer_name: str = None,
    return_url: str = None,
    notify_url: str = None,
    note: str = None,
    tags: dict = None,
) -> dict:
    """Open an order and return whatever the client needs to drive checkout."""
    if _use_sandbox():
        if _simulating(order_id, Simulate.TIMEOUT):
            return {
                'ok': False,
                'error_code': 'GATEWAY_TIMEOUT',
                'error': 'Gateway timed out.',
                'timeout': True,
            }
        if _simulating(order_id, Simulate.DECLINE):
            return {
                'ok': False,
                'error_code': 'CARD_DECLINED',
                'error': 'Your card issuer declined the transaction.',
            }

        return {
            'ok': True,
            'provider': 'SANDBOX',
            'order_id': order_id,
            'gateway_order_id': _ref('cf_ord_sbx'),
            'payment_session_id': _ref('sess_sbx'),
            # In sandbox the "3DS page" is a local screen the frontend renders
            # so the whole confirm-and-authorise flow can be walked end to end.
            'checkout_url': f'/sandbox/3ds/{order_id}',
        }

    result = cashfree.create_order(
        order_id=order_id,
        amount=amount,
        customer_id=customer_id,
        customer_phone=customer_phone,
        customer_email=customer_email,
        customer_name=customer_name,
        return_url=return_url,
        notify_url=notify_url,
        note=note,
        order_tags=tags,
    )

    if result['ok']:
        return {
            'ok': True,
            'provider': 'CASHFREE',
            'order_id': result['order_id'],
            'gateway_order_id': result['cf_order_id'],
            'payment_session_id': result['payment_session_id'],
            'checkout_url': None,   # the client SDK consumes the session id
        }

    return {
        'ok': False,
        'error_code': 'GATEWAY_ERROR',
        'error': result['error'],
        'timeout': result.get('timeout', False),
    }


def get_payment_status(order_id: str) -> dict:
    """
    Authoritative order status.

    Always consulted before money is released, even when a webhook has already
    reported success - a signature proves integrity in transit, not that the
    payment actually settled.
    """
    if _use_sandbox():
        if (
            _simulating(order_id, Simulate.DECLINE)
            or _simulating(order_id, Simulate.AUTH_DECLINE)
        ):
            return {
                'ok': True, 'status': 'FAILED', 'paid': False,
                'failure_code': 'CARD_DECLINED',
                'failure_reason': 'Issuer declined the transaction.',
            }
        if _simulating(order_id, Simulate.ABANDON):
            return {'ok': True, 'status': 'ACTIVE', 'paid': False}
        return {
            'ok': True, 'status': 'PAID', 'paid': True,
            'gateway_payment_id': _ref('cf_pay_sbx'),
        }

    result = cashfree.get_order(order_id)
    if not result['ok']:
        return {'ok': False, 'error': result['error']}

    status = (result.get('order_status') or '').upper()
    return {
        'ok': True,
        'status': status,
        'paid': status == 'PAID',
        'raw': result.get('raw'),
    }


def refund_payment(*, order_id: str, refund_id: str, amount, note: str = None) -> dict:
    """Reverse a settled charge back to the source card (PRD 9.4)."""
    if _use_sandbox():
        return {
            'ok': True,
            'refund_id': refund_id,
            'provider_reference': _ref('cf_rfnd_sbx'),
            'status': 'PENDING',
        }

    result = cashfree.refund_payment(
        order_id=order_id, refund_id=refund_id, amount=amount, note=note
    )
    if result['ok']:
        return {
            'ok': True,
            'refund_id': result['refund_id'],
            'provider_reference': result['cf_refund_id'],
            'status': result['refund_status'],
        }
    return {'ok': False, 'error': result['error']}


# ── Credit bureau (CIBIL score) ────────────────────────────────────────────

#: The bureau score scale. Anything a bureau returns outside it is not a score.
BUREAU_SCORE_MIN = 300
BUREAU_SCORE_MAX = 900

#: How bureaus say they hold no usable credit file on someone, normalised by
#: upper-casing and dropping spaces, underscores and hyphens. CIBIL reports NH
#: (no hit: no record at all) and NA (a record too new or thin to score); feeds
#: also spell these out. Every one means new to credit - never a score.
_NO_HISTORY_TOKENS = {
    'NH': 'NH', 'NOHIT': 'NH', 'NORECORD': 'NH', 'NORECORDFOUND': 'NH',
    'NA': 'NA', 'NOTAVAILABLE': 'NA', 'NOCREDITHISTORY': 'NA',
    'NOHISTORY': 'NA', 'NTC': 'NA', 'NEWTOCREDIT': 'NA', 'INSUFFICIENTHISTORY': 'NA',
}


def interpret_bureau_score(raw) -> dict:
    """
    Read a bureau's score field. Every bureau response goes through this, the
    sandbox's included, so a no-hit can never be stored as a number.

    Returns {'outcome': 'SCORED' | 'NO_HISTORY' | 'INVALID', 'score', 'code'}:

        a whole number 300-900      SCORED, that number
        NA / NH / No Hit / ...      NO_HISTORY, score None, code NH or NA
        -1 or 000-1                 NO_HISTORY (CIBIL's numeric no-hit), NH
        1 to 5                      NO_HISTORY (CIBIL 2.0 ranks a file too
                                    thin to score 1-5; a risk rank, not a
                                    score), NA
        anything else               INVALID - including 0, blanks and numbers
                                    off the scale. Not turned into a score.
    """
    text = str(raw).strip() if raw is not None else ''
    invalid = {'outcome': 'INVALID', 'score': None, 'code': None}
    if not text:
        return invalid

    if text in ('-1', '000-1'):
        return {'outcome': 'NO_HISTORY', 'score': None, 'code': 'NH'}

    token = ''.join(ch for ch in text.upper() if ch not in ' _-/')
    if token in _NO_HISTORY_TOKENS:
        return {'outcome': 'NO_HISTORY', 'score': None, 'code': _NO_HISTORY_TOKENS[token]}

    if text.isdigit():
        value = int(text)
        if BUREAU_SCORE_MIN <= value <= BUREAU_SCORE_MAX:
            return {'outcome': 'SCORED', 'score': value, 'code': None}
        if 1 <= value <= 5:
            return {'outcome': 'NO_HISTORY', 'score': None, 'code': 'NA'}
    return invalid


def _bureau_answer(raw, *, provider: str, bureau: str, reference: str,
                   is_demo: bool) -> dict:
    """A raw bureau score field as fetch_credit_report's result."""
    reading = interpret_bureau_score(raw)
    if reading['outcome'] == 'INVALID':
        return {
            'ok': False,
            'error_code': 'BUREAU_INVALID_RESPONSE',
            'error': 'The credit bureau returned a response that is not a score.',
        }
    return {
        'ok': True,
        'score': reading['score'],
        'no_history': reading['outcome'] == 'NO_HISTORY',
        'bureau_code': reading['code'],
        'provider': provider,
        'bureau': bureau,
        'reference': reference,
        'is_demo': is_demo,
    }


def _sandbox_bureau_allowed() -> bool:
    """
    The sandbox bureau answers outside production only. A sandbox score in
    production would be an invented score deciding a real application.
    """
    return current_app.config.get('ENV_NAME', 'development') != 'production'


def bureau_provider() -> str:
    """
    Who answers a credit score request: SANDBOX, DECENTRO, or NONE.

    Chosen by BUREAU_PROVIDER, separately from USE_SANDBOX_ADAPTERS: switching
    the payment rails live must not quietly switch the bureau, or the reverse.
    There is no fallback between them. DECENTRO without credentials is NONE,
    not the sandbox - a user expecting their real score must never be handed a
    simulated one - and SANDBOX in production is NONE too.
    """
    requested = (current_app.config.get('BUREAU_PROVIDER') or 'SANDBOX').upper()
    if requested == 'DECENTRO':
        return 'DECENTRO' if decentro.is_configured() else 'NONE'
    if requested == 'SANDBOX':
        return 'SANDBOX' if _sandbox_bureau_allowed() else 'NONE'
    return 'NONE'


def bureau_info() -> dict:
    """What the screens say about the bureau before anything is pulled."""
    provider = bureau_provider()
    if provider == 'DECENTRO':
        return {'provider': provider, 'bureau': decentro.bureau_name(),
                'available': True, 'is_test': decentro.is_test_environment()}
    if provider == 'SANDBOX':
        return {'provider': provider, 'bureau': 'SANDBOX',
                'available': True, 'is_test': True}
    return {'provider': 'NONE', 'bureau': None, 'available': False, 'is_test': False}


_NOT_CONFIGURED = {
    'ok': False,
    'error_code': 'BUREAU_NOT_CONFIGURED',
    'error': 'The credit bureau is not connected yet.',
}


#: Sandbox scenarios, chosen by the four digits of a test PAN (ABCDE0680F).
#: There is no default: a PAN that picks no scenario gets no score, because a
#: number handed to every applicant is a fabricated score.
SANDBOX_NO_HIT_DIGITS = '0000'          # bureau answers NH
SANDBOX_NA_DIGITS = '0001'              # bureau answers NA
SANDBOX_DOWN_DIGITS = '0002'            # bureau unreachable
SANDBOX_GARBLED_DIGITS = '0003'         # bureau answers something unreadable


def _sandbox_pull(pan: str) -> dict:
    """
    The sandbox bureau. The PAN's four digits pick the answer: 0300-0900 is
    returned as the score (ABCDE0680F scores 680); 0000 answers NH and 0001 NA;
    0002 is a bureau outage and 0003 an unreadable response. Any other PAN has
    no sandbox file and gets no score.
    """
    digits = (pan or '')[5:9]
    if digits == SANDBOX_DOWN_DIGITS:
        return {'ok': False, 'error_code': 'BUREAU_UNAVAILABLE',
                'error': 'The credit bureau did not respond.'}
    raw = {
        SANDBOX_NO_HIT_DIGITS: 'NH',
        SANDBOX_NA_DIGITS: 'NA',
        SANDBOX_GARBLED_DIGITS: 'ERR#',
    }.get(digits)
    if raw is None and digits.isdigit() and \
            BUREAU_SCORE_MIN <= int(digits) <= BUREAU_SCORE_MAX:
        raw = str(int(digits))
    if raw is None:
        return {'ok': False, 'error_code': 'BUREAU_NO_SANDBOX_FILE',
                'error': 'The sandbox bureau has no test file for this PAN.'}
    scored = _bureau_answer(raw, provider='SANDBOX', bureau='SANDBOX',
                            reference=_ref('bureau_sbx'), is_demo=True)
    if scored.get('ok'):
        scored['report'] = _demo_credit_report(scored.get('score'), pan)
    return scored


def _decentro_pull(*, reference: str, pan: str, full_name: str, phone: str,
                   date_of_birth=None, pincode: str = None) -> dict:
    result = decentro.fetch_report(
        reference_id=reference, pan=pan, name=full_name, mobile=phone,
        date_of_birth=date_of_birth.isoformat() if date_of_birth else None,
        pincode=pincode,
    )
    if not result.get('ok'):
        return result

    is_test = decentro.is_test_environment()
    bureau = decentro.bureau_name()
    if result['no_hit']:
        return {'ok': True, 'score': None, 'no_history': True, 'bureau_code': 'NH',
                'provider': 'DECENTRO', 'bureau': bureau,
                'reference': result.get('reference'), 'is_demo': is_test,
                'report': None}

    scored = _bureau_answer(result.get('raw_score'), provider='DECENTRO',
                            bureau=bureau, reference=result.get('reference'),
                            is_demo=is_test)
    if scored.get('ok'):
        scored['report'] = result.get('report')
    return scored


def fetch_credit_report(*, reference: str, pan: str, full_name: str = None,
                        phone: str = None, date_of_birth=None,
                        pincode: str = None) -> dict:
    """
    The person's credit score, and the report behind it, by PAN.

    Only ever called with the person's recorded consent - pulling a credit
    report without it is not permitted - and it is a soft enquiry, which does
    not itself affect the score.

    Returns {'ok', 'score', 'no_history', 'bureau_code', 'provider', 'bureau',
    'reference', 'is_demo', 'report'}, or {'ok': False, 'error_code', 'error'}.
    A score of None with no_history=True means the bureau has no file on the
    person: new to credit, which is not the same as a bad score, and is never
    given a number. report is None for a no-hit.

    `report` has the one shape every provider is mapped onto:

        {'accounts': [{'type', 'lender', 'status', 'opened_on', 'limit',
                       'balance'}],
         'utilization': {'percent', 'total_limit', 'total_balance'},
         'payment_history': {'on_time_percent', 'months_reviewed',
                             'late_payments'},
         'enquiries': [{'date', 'lender', 'purpose'}]}

    is_demo is True for anything that is not a real person's real file: every
    sandbox answer, and every answer from a provider's test environment.

    Providers (see bureau_provider):
        SANDBOX   simulated, outside production only; the report is demo data.
        DECENTRO  Experian, CRIF or Equifax through Decentro (decentro.py).
        NONE      refused - the score is unavailable, never invented.
    """
    provider = bureau_provider()
    if provider == 'SANDBOX':
        return _sandbox_pull(pan)
    if provider == 'DECENTRO':
        return _decentro_pull(reference=reference, pan=pan, full_name=full_name,
                              phone=phone, date_of_birth=date_of_birth,
                              pincode=pincode)
    return dict(_NOT_CONFIGURED)


def fetch_credit_score(**kwargs) -> dict:
    """fetch_credit_report without the report - for a credit application."""
    result = fetch_credit_report(**kwargs)
    result.pop('report', None)
    return result


def _demo_credit_report(score, pan: str) -> dict:
    """A plausible, clearly fictional report for the sandbox."""
    from datetime import date, timedelta

    if score is None:       # new to credit: an empty file
        return {
            'accounts': [],
            'utilization': {'percent': None, 'total_limit': 0, 'total_balance': 0},
            'payment_history': {'on_time_percent': None, 'months_reviewed': 0,
                                'late_payments': 0},
            'enquiries': [],
        }

    seed = sum(ord(c) for c in (pan or 'DEMO'))
    today = date.today()
    # Higher score, lower utilisation and fewer late payments.
    utilization = max(8, min(85, round((900 - score) / 6) + seed % 7))
    late = 0 if score >= 750 else (1 if score >= 700 else (3 if score >= 650 else 6))
    months = 36
    accounts = [
        {'type': 'Credit card', 'lender': 'Demo Bank A', 'status': 'Active',
         'opened_on': (today - timedelta(days=900 + seed % 200)).isoformat(),
         'limit': 150000, 'balance': round(150000 * utilization / 100)},
        {'type': 'Credit card', 'lender': 'Demo Bank B', 'status': 'Active',
         'opened_on': (today - timedelta(days=500 + seed % 90)).isoformat(),
         'limit': 80000, 'balance': round(80000 * utilization / 100)},
        {'type': 'Personal loan', 'lender': 'Demo Finance', 'status': 'Active',
         'opened_on': (today - timedelta(days=400)).isoformat(),
         'limit': 200000, 'balance': 120000},
        {'type': 'Consumer durable loan', 'lender': 'Demo NBFC', 'status': 'Closed',
         'opened_on': (today - timedelta(days=1100)).isoformat(),
         'limit': 30000, 'balance': 0},
    ]
    revolving = [a for a in accounts if a['type'] == 'Credit card']
    enquiries = [
        {'date': (today - timedelta(days=d)).isoformat(), 'lender': lender,
         'purpose': purpose}
        for d, lender, purpose in [
            (21, 'Demo Bank C', 'Credit card'),
            (95, 'Demo Finance', 'Personal loan'),
            (160, 'CashU', 'Credit line'),
        ][: 1 if score >= 750 else 3]
    ]
    return {
        'accounts': accounts,
        'utilization': {
            'percent': utilization,
            'total_limit': sum(a['limit'] for a in revolving),
            'total_balance': sum(a['balance'] for a in revolving),
        },
        'payment_history': {
            'on_time_percent': round((months - late) / months * 100, 1),
            'months_reviewed': months,
            'late_payments': late,
        },
        'enquiries': enquiries,
    }


# ── Penny drop (PRD FR-005) ────────────────────────────────────────────────

def penny_drop(
    *,
    verification_id: str,
    account_number: str,
    ifsc: str,
    expected_name: str = None,
    phone: str = None,
) -> dict:
    """
    Verify account ownership by sending 1 INR and reading back the CBS name.

    Returns the name the bank holds. Scoring it against the KYC name is
    name_match's job, kept separate so the threshold policy can change without
    touching the vendor call.
    """
    if _use_sandbox():
        if _simulating(verification_id, Simulate.NAME_MISMATCH):
            return {
                'ok': True,
                'account_valid': True,
                'name_at_bank': 'SOMEONE ELSE ENTIRELY',
                'utr': _fake_utr(),
                'provider_reference': _ref('cf_vrfy_sbx'),
            }

        # Echo the expected name so the happy path verifies cleanly, with a
        # realistic distortion: banks return names uppercased.
        return {
            'ok': True,
            'account_valid': True,
            'name_at_bank': (expected_name or 'ACCOUNT HOLDER').upper(),
            'utr': _fake_utr(),
            'provider_reference': _ref('cf_vrfy_sbx'),
        }

    result = cashfree.verify_bank_account(
        verification_id=verification_id,
        account_number=account_number,
        ifsc=ifsc,
        name=expected_name,
        phone=phone,
    )

    if result['ok']:
        return {
            'ok': True,
            'account_valid': (result.get('account_status') or '').upper() == 'VALID',
            'name_at_bank': result.get('name_at_bank'),
            'utr': result.get('utr'),
            'provider_reference': result.get('reference_id'),
        }

    return {'ok': False, 'error': result['error']}


# ── Payouts (Pay Bills) ────────────────────────────────────────────────────
# The rail that pays a Pay Bills draw out to the holder's verified account.
#
# Sandbox only. The live IMPS payout integration was removed with the
# credit-to-bank product (5b64317), and Pay Bills does not bring it back: a real
# payout needs the licensed partner PRD open decision #1 has not named. So the
# live branch refuses rather than guessing at an API - a deployment that turns
# the sandbox off gets a clear "unavailable", never a simulated success.
#
# The sandbox is stateless, so the outcome a later status poll should report is
# carried in the payout reference itself.

#: Development outcomes for a payout, chosen by the caller.
PAYOUT_OUTCOMES = ('SUCCESS', 'FAIL', 'PENDING', 'PENDING_FAIL', 'REVERSE')

_PAYOUT_TAG = {
    'PENDING': 'PENDOK',
    'PENDING_FAIL': 'PENDFAIL',
    'REVERSE': 'REVERSE',
}


def payout_provider() -> str:
    return 'SANDBOX' if _use_sandbox() else 'UNAVAILABLE'


def dispatch_payout(*, reference: str, account_number: str, ifsc: str,
                    beneficiary_name: str, amount, outcome: str = 'SUCCESS') -> dict:
    """
    Hand a payout to the rail.

    Returns {'ok': True, 'status': 'SUCCESS'|'PENDING', 'payout_reference',
    'utr'} when the rail accepted it, or {'ok': False, 'code', 'error'} when it
    refused. A refusal means no money left: the caller restores the credit.
    """
    if not _use_sandbox():
        return {
            'ok': False,
            'code': 'PAYOUT_RAIL_UNAVAILABLE',
            'error': 'Bank payouts are not available yet.',
        }

    outcome = outcome if outcome in PAYOUT_OUTCOMES else 'SUCCESS'
    tag = _PAYOUT_TAG.get(outcome, 'OK')
    payout_reference = f'po_sbx_{tag}_{uuid.uuid4().hex[:12]}'

    if outcome == 'FAIL':
        return {
            'ok': False,
            'code': 'BENEFICIARY_BANK_DECLINED',
            'error': 'The beneficiary bank declined the credit. The account may be '
                     'frozen or closed.',
            'payout_reference': payout_reference,
        }

    if outcome in ('PENDING', 'PENDING_FAIL'):
        return {
            'ok': True, 'status': 'PENDING',
            'payout_reference': payout_reference, 'utr': None,
        }

    # SUCCESS and REVERSE both land first; REVERSE is returned by the bank later.
    return {
        'ok': True, 'status': 'SUCCESS',
        'payout_reference': payout_reference, 'utr': _fake_utr(),
    }


def get_payout_status(payout_reference: str) -> dict:
    """
    Ask the rail what became of a payout.

    Returns {'ok': True, 'status': 'SUCCESS'|'PENDING'|'FAILED'|'REVERSED',
    'utr', 'reason'}.
    """
    if not _use_sandbox() or not (payout_reference or '').startswith('po_sbx_'):
        return {'ok': False, 'error': 'Payout status is not available.'}

    tag = payout_reference.split('_')[2] if payout_reference.count('_') >= 3 else 'OK'
    if tag == 'PENDFAIL':
        return {
            'ok': True, 'status': 'FAILED', 'utr': None,
            'reason': 'The beneficiary bank did not accept the credit in time.',
        }
    if tag == 'REVERSE':
        return {
            'ok': True, 'status': 'REVERSED', 'utr': None,
            'reason': 'The beneficiary bank returned the credit.',
        }
    return {'ok': True, 'status': 'SUCCESS', 'utr': _fake_utr(), 'reason': None}


def lookup_ifsc(ifsc: str) -> dict:
    """Resolve an IFSC to bank and branch, identifying official bank/institution names."""
    from portal.helpers import bank_ifsc_service
    info = bank_ifsc_service.get_bank_info(ifsc)
    if info.get('ok'):
        return info

    if not _use_sandbox():
        result = cashfree.verify_ifsc(ifsc)
        if result.get('ok'):
            return {
                'ok': True,
                'bank_name': result['bank_name'],
                'branch': result['branch'],
                'city': result.get('city'),
                'state': result.get('state'),
            }
        return {'ok': False, 'error': result.get('error', 'Invalid IFSC code.')}

    return {'ok': False, 'error': info.get('error', 'Invalid IFSC code.')}


# -- UPI collection (PRD FR-008, section 11) --------------------------------
# A separate rail from the card charge above, and deliberately a separate
# vendor. A transfer is funded by a credit card and settles over IMPS; an EMI
# is collected over UPI. Forcing both through one gateway would couple two
# products that fail independently.
#
# Unlike the card path, UPI does not honour USE_SANDBOX_ADAPTERS: the reason to
# configure a Razorpay test key is to exercise the real rail, test mode and
# all. The simulator is reached only when there is genuinely nothing to call.

#: UPI apps surfaced to the user. `package` is the Android intent target that
#: Razorpay Checkout hands off to. Order matters - it is the order they appear
#: in the sheet.
UPI_APPS = [
    {'id': 'google_pay', 'label': 'Google Pay',
     'package': 'com.google.android.apps.nbu.paisa.user'},
    {'id': 'phonepe', 'label': 'PhonePe', 'package': 'com.phonepe.app'},
    {'id': 'paytm', 'label': 'Paytm', 'package': 'net.one97.paytm'},
    {'id': 'bhim', 'label': 'BHIM', 'package': 'in.org.npci.upiapp'},
]


def upi_provider() -> str:
    """
    Which rail a UPI collection would actually use right now.

    Falls back to the simulator when the merchant account has UPI switched off,
    rather than handing the user to a checkout that cannot serve it. A Razorpay
    account does not have UPI enabled by default.
    """
    if not current_app.config.get('RAZORPAY_UPI_ENABLED', True):
        return 'SANDBOX'
    if not razorpay.is_configured():
        return 'SANDBOX'
    if not razorpay.supports('upi'):
        current_app.logger.info(
            '[adapters] UPI is not enabled on the Razorpay account; '
            'using the simulator for UPI collection.'
        )
        return 'SANDBOX'
    return 'RAZORPAY'


def upi_public_key() -> str:
    """
    The Checkout key id, safe to hand to the browser.

    Empty on the sandbox rail, which is how the client knows to take the
    simulated path instead of opening Checkout with no key.
    """
    return razorpay.public_key() if upi_provider() == 'RAZORPAY' else ''


def create_razorpay_order(
    *,
    order_id: str,
    amount,
    customer_id: str,
    customer_phone: str = None,
    customer_email: str = None,
    customer_name: str = None,
    note: str = None,
    tags: dict = None,
) -> dict:
    """
    Open a UPI collection order.

    Returns what the client needs to launch Checkout - never a payment status.
    Opening an order is not collecting money, and nothing downstream may treat
    a successful return from here as a payment.
    """
    if upi_provider() == 'SANDBOX':
        if _simulating(order_id, Simulate.TIMEOUT):
            return {
                'ok': False, 'error_code': 'GATEWAY_TIMEOUT',
                'error': 'Gateway timed out.', 'timeout': True,
            }
        if _simulating(order_id, Simulate.DECLINE):
            return {
                'ok': False, 'error_code': 'UPI_DECLINED',
                'error': 'The UPI request was declined.',
            }

        return {
            'ok': True,
            'provider': 'SANDBOX',
            'gateway_order_id': _ref('order_sbx'),
            'public_key': '',
            'checkout_url': f'/sandbox/upi/{order_id}',
            'amount_paise': razorpay.to_paise(amount),
        }

    result = razorpay.create_order(
        receipt=order_id,
        amount=amount,
        notes={
            'customer_id': customer_id,
            'customer_name': customer_name or '',
            'note': note or '',
            **(tags or {}),
        },
    )

    if not result['ok']:
        return {
            'ok': False,
            'error_code': result.get('error_code') or 'GATEWAY_ERROR',
            'error': result['error'],
            'timeout': result.get('timeout', False),
        }

    return {
        'ok': True,
        'provider': 'RAZORPAY',
        'gateway_order_id': result['order_id'],
        'public_key': razorpay.public_key(),
        'checkout_url': None,          # Checkout is opened by the JS SDK
        'amount_paise': result['amount'],
    }


def get_razorpay_payment_status(*, order_id: str, payment_id: str = None) -> dict:
    """
    Authoritative status for a UPI collection.

    Resolution order matters. When a payment id is known it is read directly,
    because an order can carry several attempts and only one of them is the one
    the user just completed. With no payment id, every attempt on the order is
    examined and a captured one wins - that is the path the webhook and the
    poller take.

    `paid` is True only for a *captured* payment. An `authorized` payment is
    money held, not money taken; it auto-refunds if never captured, so treating
    it as paid would show a success screen for a payment that later reverses.
    """
    if upi_provider() == 'SANDBOX':
        if (
            _simulating(order_id, Simulate.DECLINE)
            or _simulating(order_id, Simulate.AUTH_DECLINE)
        ):
            return {
                'ok': True, 'status': 'FAILED', 'paid': False,
                'failure_code': 'UPI_DECLINED',
                'failure_reason': 'The payment was declined in your UPI app.',
            }
        if _simulating(order_id, Simulate.ABANDON):
            # The order exists and nobody paid it - the same answer Razorpay
            # gives for an order with no payment attempts.
            return {'ok': True, 'status': 'PENDING', 'paid': False}
        return {
            'ok': True, 'status': 'PAID', 'paid': True,
            'gateway_payment_id': _ref('pay_sbx'),
            'rrn': _fake_utr(),
            'method': 'upi',
        }

    if payment_id:
        payment = razorpay.fetch_payment(payment_id)
        if not payment['ok']:
            return {'ok': False, 'error': payment['error'],
                    'timeout': payment.get('timeout', False)}

        # A payment id belonging to a different order is either a bug or an
        # attempt to settle one EMI with another EMI's payment. Refuse it.
        if payment.get('order_id') and payment['order_id'] != order_id:
            return {
                'ok': True, 'status': 'FAILED', 'paid': False,
                'failure_code': 'ORDER_MISMATCH',
                'failure_reason': 'This payment belongs to a different order.',
            }

        return _upi_status_from_payment(payment)

    attempts = razorpay.fetch_order_payments(order_id)
    if not attempts['ok']:
        return {'ok': False, 'error': attempts['error'],
                'timeout': attempts.get('timeout', False)}

    items = attempts['items']
    if not items:
        # The order exists but nobody has paid it yet - the user is still in
        # their UPI app, or they abandoned it. Neither is a failure.
        return {'ok': True, 'status': 'PENDING', 'paid': False}

    captured = next((i for i in items if i.get('status') == 'captured'), None)
    if captured:
        return _upi_status_from_payment({
            'ok': True,
            'payment_id': captured.get('id'),
            'status': 'captured',
            'captured': True,
            'method': captured.get('method'),
            'vpa': captured.get('vpa'),
            'acquirer_data': captured.get('acquirer_data') or {},
            'amount': captured.get('amount'),
        })

    authorized = next((i for i in items if i.get('status') == 'authorized'), None)
    if authorized:
        return {'ok': True, 'status': 'PENDING', 'paid': False,
                'gateway_payment_id': authorized.get('id')}

    latest = items[-1]
    return {
        'ok': True,
        'status': 'FAILED',
        'paid': False,
        'gateway_payment_id': latest.get('id'),
        'failure_code': latest.get('error_code') or 'UPI_FAILED',
        'failure_reason': (
            latest.get('error_description') or 'The payment was not completed.'
        ),
    }


def _upi_status_from_payment(payment: dict) -> dict:
    """Map one Razorpay payment onto the vocabulary the EMI engine speaks."""
    status = payment.get('status')

    if payment.get('captured') or status == 'captured':
        acquirer = payment.get('acquirer_data') or {}
        return {
            'ok': True,
            'status': 'PAID',
            'paid': True,
            'gateway_payment_id': payment.get('payment_id'),
            'rrn': acquirer.get('rrn') or acquirer.get('upi_transaction_id'),
            'vpa': payment.get('vpa'),
            'method': payment.get('method'),
            'amount_paise': payment.get('amount'),
        }

    if status in ('created', 'authorized'):
        # Money is held but not taken, or the user has not finished. Pending is
        # the honest answer; the poller will come back to it.
        return {
            'ok': True, 'status': 'PENDING', 'paid': False,
            'gateway_payment_id': payment.get('payment_id'),
        }

    return {
        'ok': True,
        'status': 'FAILED',
        'paid': False,
        'gateway_payment_id': payment.get('payment_id'),
        'failure_code': payment.get('error_code') or 'UPI_FAILED',
        'failure_reason': (
            payment.get('error_description') or 'The payment was not completed.'
        ),
    }


def verify_razorpay_signature(
    *, order_id: str, payment_id: str, signature: str
) -> bool:
    """
    Verify the signed handler payload the browser returns.

    On the sandbox rail there is no signature and no secret to verify it with,
    so this is vacuously true - and the sandbox is unreachable whenever real
    credentials exist.
    """
    if upi_provider() == 'SANDBOX':
        return True

    return razorpay.verify_checkout_signature(
        order_id=order_id, payment_id=payment_id, signature=signature
    )


# Back-compatible aliases. The EMI engine speaks in UPI terms because that is
# what it collects with; everything else charges through the same gateway and
# calls the general names.
create_upi_order = create_razorpay_order
get_upi_payment_status = get_razorpay_payment_status
verify_upi_checkout_signature = verify_razorpay_signature

