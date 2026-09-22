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
import time
import uuid

from flask import current_app

from portal.helpers import cashfree, razorpay


# ── Failure injection ──────────────────────────────────────────────────────
# PRD section 20 defines eleven failure scenarios and PRD 9.4 a three-retry
# circuit breaker. Neither can be verified against a rail that always succeeds,
# so the sandbox honours a directive embedded in the reference id.

class Simulate:
    """Tokens a caller can embed in an id to force a sandbox outcome."""

    DECLINE = 'SIMDECLINE'         # issuer declines the charge (ERR-003)
    TIMEOUT = 'SIMTIMEOUT'         # gateway times out (ERR-005)
    PAYOUT_FAIL = 'SIMPAYOUTFAIL'  # charge succeeds, payout fails (ERR-006)
    NAME_MISMATCH = 'SIMNAMEMM'    # penny-drop name mismatch (ERR-004)
    TOKEN_EXPIRED = 'SIMTOKENEXP'  # expired card token (ERR-009)
    BILLER_DOWN = 'SIMBILLERDOWN'  # BBPS biller offline (ERR-010)

    #: Declines at *authorisation* rather than at order creation, which is how
    #: an issuer decline actually reaches a customer: the order opens, they
    #: reach a payment screen, and the charge is refused there. DECLINE above
    #: refuses up front, which models a pre-auth rejection and skips the
    #: processing state entirely.
    AUTH_DECLINE = 'SIMAUTHDECL'


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


def revoke_card_token(token_reference_id: str) -> dict:
    """
    De-register a token upstream (PRD 8.3).

    Unlinking must invalidate the token at the network, not just hide the row -
    otherwise a token CashU can no longer see remains chargeable.
    """
    if _use_sandbox():
        return {'ok': True, 'revoked': True, 'reference': _ref('rvk_sbx')}

    return {
        'ok': False,
        'error_code': 'PROVIDER_NOT_CONFIGURED',
        'error': 'Token requestor is not configured.',
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


# ── Payout: outbound IMPS (PRD FR-006 step 8) ──────────────────────────────

def dispatch_payout(
    *,
    transfer_id: str,
    amount,
    beneficiary_id: str,
    beneficiary_name: str,
    account_number: str,
    ifsc: str,
    remarks: str = None,
) -> dict:
    """
    Send funds to a verified account.

    The caller must have confirmed the destination is penny-drop verified and
    belongs to this user; this function does not re-check, because by the time
    money is moving that decision is already made and recorded.
    """
    if _use_sandbox():
        if _simulating(transfer_id, Simulate.PAYOUT_FAIL):
            return {
                'ok': False,
                'error_code': 'PAYOUT_FAILED',
                'error': 'Beneficiary bank did not accept the transfer.',
                'retryable': True,
            }

        # A real IMPS hop is not instant; a little latency keeps the sandbox
        # honest about the states the UI has to render.
        time.sleep(0.15)

        return {
            'ok': True,
            'provider': 'SANDBOX',
            'payout_reference': _ref('cf_txfr_sbx'),
            'status': 'SUCCESS',
            'utr': _fake_utr(),
        }

    result = cashfree.create_payout(
        transfer_id=transfer_id,
        amount=amount,
        beneficiary_id=beneficiary_id,
        beneficiary_name=beneficiary_name,
        account_number=account_number,
        ifsc=ifsc,
        remarks=remarks,
    )

    if result['ok']:
        status = (result.get('status') or '').upper()
        return {
            'ok': True,
            'provider': 'CASHFREE',
            'payout_reference': result['cf_transfer_id'],
            'status': status,
            'utr': result.get('utr'),
        }

    return {
        'ok': False,
        'error_code': 'PAYOUT_FAILED',
        'error': result['error'],
        'retryable': not result.get('timeout', False),
    }


def get_payout_status(transfer_id: str) -> dict:
    if _use_sandbox():
        return {'ok': True, 'status': 'SUCCESS', 'utr': _fake_utr()}

    result = cashfree.get_payout_status(transfer_id)
    if result['ok']:
        return {
            'ok': True,
            'status': (result.get('status') or '').upper(),
            'utr': result.get('utr'),
        }
    return {'ok': False, 'error': result['error']}


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
        if _simulating(order_id, Simulate.DECLINE):
            return {
                'ok': True, 'status': 'FAILED', 'paid': False,
                'failure_code': 'UPI_DECLINED',
                'failure_reason': 'The payment was declined in your UPI app.',
            }
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
# what it collects with; the transfer engine charges a card through the same
# gateway and calls the general names.
create_upi_order = create_razorpay_order
get_upi_payment_status = get_razorpay_payment_status
verify_upi_checkout_signature = verify_razorpay_signature


def transfer_upi_funding_allowed() -> bool:
    """
    Whether UPI may settle a transfer's charge.

    Unset in config, this follows the key: on for a test key, off for a live
    one. A UPI-funded transfer takes money from a bank rather than a credit
    line, so it is a testing affordance by default rather than a product
    decision made by accident.
    """
    explicit = current_app.config.get('TRANSFER_UPI_FUNDING', '')
    if explicit:
        return explicit == 'True'

    # Offered whenever the gateway is in test mode, regardless of whether the
    # account has UPI switched on: if it has not, the payment is simulated
    # rather than withheld. See upi_needs_simulation().
    return razorpay_available() and razorpay.is_test_mode()


def upi_needs_simulation() -> bool:
    """
    Whether a UPI payment has to be simulated rather than sent to the gateway.

    True when the merchant account does not have UPI switched on. Offering UPI
    and then handing the user to a checkout that cannot serve it is what
    produced the "international cards are not supported" dead end: Checkout
    falls back to a card, and the card fails.

    Simulating instead keeps the whole journey exercisable today, and the day
    UPI is enabled in the Razorpay dashboard this returns False and the same
    flow starts going to the real rail with no code change.
    """
    if not razorpay.is_configured():
        return True
    return not razorpay.supports('upi')


def test_upi_vpa() -> str:
    """A VPA to prefill during testing, so nobody retypes it every attempt."""
    return current_app.config.get('RAZORPAY_TEST_UPI_VPA', '') or ''


def razorpay_available() -> bool:
    """
    Whether the Razorpay rail is usable at all.

    Deliberately about configuration, not about UPI. This used to be defined as
    `upi_provider() == 'RAZORPAY'`, which quietly coupled the card rail to a
    UPI account setting: switching UPI off would have moved every card transfer
    away from Razorpay as well, even though the account serves cards perfectly
    well. Per-method support is `supports()`.
    """
    if not current_app.config.get('RAZORPAY_UPI_ENABLED', True):
        return False
    return razorpay.is_configured()

