"""
portal/helpers/razorpay.py
==========================
Razorpay REST client - UPI collection for EMI payments (PRD FR-008).

Called over plain `requests` rather than the vendor SDK, exactly as
`cashfree.py` is, so the dependency surface stays at one HTTP library and the
failure modes are ours to shape rather than the SDK's.

Three things about Razorpay drive the design here:

1. **Money is integer paise.** Every amount crossing this boundary is converted
   with Decimal quantisation, never float arithmetic - `int(12345.6 * 100)` is
   1234559 on this hardware, and that is a real rupee lost on a real EMI.

2. **Two different signatures.** The checkout handler returns an HMAC over
   `order_id|payment_id` keyed by the API secret; webhooks carry an HMAC over
   the raw body keyed by a *separate* webhook secret. They are not
   interchangeable, and both are verified with compare_digest.

3. **A signature is not a settlement.** Verifying either one proves the message
   was not forged. It does not prove money moved. Every caller re-reads the
   payment from this API before the ledger is touched.
"""

import hashlib
import hmac
from decimal import Decimal, ROUND_HALF_UP

import requests
from flask import current_app

#: A UPI collect request can legitimately sit unanswered for minutes, but that
#: waiting happens on the user's phone, not on this socket. Any single API call
#: taking longer than this has failed.
_TIMEOUT = 30

_BASE_URL = 'https://api.razorpay.com/v1'


class RazorpayError(Exception):
    """Raised only for configuration faults, never for a declined payment."""


def _config() -> dict:
    cfg = current_app.config
    return {
        'key_id': cfg.get('RAZORPAY_KEY_ID', ''),
        'key_secret': cfg.get('RAZORPAY_KEY_SECRET', ''),
        'webhook_secret': cfg.get('RAZORPAY_WEBHOOK_SECRET', ''),
    }


def is_configured() -> bool:
    """True when real Razorpay credentials are present."""
    cfg = _config()
    return bool(cfg['key_id'] and cfg['key_secret'])


def public_key() -> str:
    """
    The key id, which is the only credential the browser may ever see.

    Checkout needs it to open. The secret never leaves this process - it signs
    and verifies here and nowhere else.
    """
    return _config()['key_id']


def is_test_mode() -> bool:
    return public_key().startswith('rzp_test_')


def to_paise(amount) -> int:
    """
    Rupees to integer paise, half-up, without ever touching a float.

    Razorpay rejects a non-integer amount, and a binary float cannot hold
    1234.35 exactly. Decimal quantisation is the only safe conversion.
    """
    rupees = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return int(rupees * 100)


def to_rupees(paise) -> Decimal:
    return (Decimal(int(paise)) / Decimal(100)).quantize(Decimal('0.01'))


def _request(method: str, path: str, payload: dict = None, params: dict = None) -> dict:
    """
    One HTTP call, normalised to {ok, status_code, data, error, timeout}.

    Network faults come back as ok=False rather than raising, so the caller can
    park a payment as PENDING and let the poller resolve it - which is the
    gateway-timeout path, not an exception path.
    """
    cfg = _config()
    if not is_configured():
        return {
            'ok': False, 'status_code': 503, 'data': {},
            'error': 'Razorpay is not configured.', 'timeout': False,
        }

    url = f'{_BASE_URL}{path}'

    try:
        response = requests.request(
            method, url,
            auth=(cfg['key_id'], cfg['key_secret']),
            json=payload,
            params=params,
            timeout=_TIMEOUT,
        )
    except requests.Timeout:
        current_app.logger.error(f'[razorpay] timeout calling {path}')
        return {
            'ok': False, 'status_code': 504, 'data': {},
            'error': 'Payment gateway timed out.', 'timeout': True,
        }
    except requests.RequestException as exc:
        current_app.logger.error(f'[razorpay] transport error calling {path}: {exc}')
        return {
            'ok': False, 'status_code': 502, 'data': {},
            'error': 'Payment gateway is unreachable.', 'timeout': False,
        }

    try:
        body = response.json()
    except ValueError:
        body = {'raw': response.text[:2000]}

    if not isinstance(body, dict):
        body = {}

    ok = 200 <= response.status_code < 300
    error_body = body.get('error') or {}

    if not ok:
        # Log the code and the gateway's own description. Never the payload -
        # it carries the customer's phone number and VPA.
        current_app.logger.warning(
            f'[razorpay] {method} {path} -> {response.status_code} '
            f'{error_body.get("code", "")} {error_body.get("description", "")}'
        )

    return {
        'ok': ok,
        'status_code': response.status_code,
        'data': body,
        'error': None if ok else (
            error_body.get('description') or 'Payment gateway error.'
        ),
        'error_code': None if ok else error_body.get('code'),
        'timeout': False,
    }


# -- Orders -----------------------------------------------------------------

def create_order(
    *,
    receipt: str,
    amount,
    notes: dict = None,
    currency: str = 'INR',
) -> dict:
    """
    Open an order for the amount the user is about to pay.

    `payment_capture=1` makes an authorised UPI payment capture immediately.
    Without it the money sits authorised and silently auto-refunds days later,
    which would show the user a success screen for a payment that quietly
    reversed itself.

    `receipt` is our own payment id, and Razorpay indexes it - it is the thread
    back from a stray dashboard entry to the row that created it.
    """
    result = _request('POST', '/orders', payload={
        'amount': to_paise(amount),
        'currency': currency,
        'receipt': receipt[:40],
        'payment_capture': 1,
        'notes': {k: str(v)[:250] for k, v in (notes or {}).items()},
    })

    if not result['ok']:
        return {
            'ok': False,
            'error': result['error'],
            'error_code': result.get('error_code'),
            'timeout': result.get('timeout', False),
        }

    data = result['data']
    return {
        'ok': True,
        'order_id': data.get('id'),
        'amount': data.get('amount'),
        'currency': data.get('currency'),
        'status': data.get('status'),
        'receipt': data.get('receipt'),
    }


def fetch_order(order_id: str) -> dict:
    """Order status: created, attempted, or paid."""
    result = _request('GET', f'/orders/{order_id}')
    if not result['ok']:
        return {
            'ok': False, 'error': result['error'],
            'timeout': result.get('timeout', False),
        }

    data = result['data']
    return {
        'ok': True,
        'order_id': data.get('id'),
        'status': (data.get('status') or '').lower(),
        'amount_paid': data.get('amount_paid'),
        'amount': data.get('amount'),
        'raw': data,
    }


def fetch_order_payments(order_id: str) -> dict:
    """
    Every payment attempt against an order, newest last.

    A user who fails once and retries inside the same checkout produces several
    attempts on one order, so "did this order get paid" cannot be answered by
    looking at a single payment id.
    """
    result = _request('GET', f'/orders/{order_id}/payments')
    if not result['ok']:
        return {
            'ok': False, 'error': result['error'],
            'timeout': result.get('timeout', False),
        }

    return {'ok': True, 'items': result['data'].get('items') or []}


def fetch_payment(payment_id: str) -> dict:
    """
    One payment: created, authorized, captured, refunded, or failed.

    This is the authoritative read. Nothing in this codebase marks an EMI paid
    without a `captured` coming back from here.
    """
    result = _request('GET', f'/payments/{payment_id}')
    if not result['ok']:
        return {
            'ok': False, 'error': result['error'],
            'timeout': result.get('timeout', False),
        }

    data = result['data']
    return {
        'ok': True,
        'payment_id': data.get('id'),
        'order_id': data.get('order_id'),
        'status': (data.get('status') or '').lower(),
        'amount': data.get('amount'),
        'method': data.get('method'),
        'vpa': data.get('vpa'),
        'acquirer_data': data.get('acquirer_data') or {},
        'error_code': data.get('error_code'),
        'error_description': data.get('error_description'),
        'error_reason': data.get('error_reason'),
        'captured': data.get('status') == 'captured',
        'raw': data,
    }


def refund_payment(*, payment_id: str, amount=None, notes: dict = None) -> dict:
    """Refund a captured payment - used when we collect but the biller rejects."""
    payload = {'notes': {k: str(v)[:250] for k, v in (notes or {}).items()}}
    if amount is not None:
        payload['amount'] = to_paise(amount)

    result = _request('POST', f'/payments/{payment_id}/refund', payload=payload)
    if not result['ok']:
        return {'ok': False, 'error': result['error']}

    data = result['data']
    return {
        'ok': True,
        'refund_id': data.get('id'),
        'status': data.get('status'),
        'amount': data.get('amount'),
    }


# -- Signatures -------------------------------------------------------------

def verify_checkout_signature(
    *, order_id: str, payment_id: str, signature: str
) -> bool:
    """
    Verify the handler payload Checkout returns in the browser.

    HMAC-SHA256 of `order_id|payment_id`, keyed by the API secret, hex encoded.

    This proves the browser did not invent the payment id. It does *not* prove
    the payment captured - a caller that stopped here would mark an EMI paid on
    a correctly-signed replay of an older failed attempt. Every caller re-reads
    `fetch_payment` afterwards.
    """
    cfg = _config()
    if not cfg['key_secret']:
        current_app.logger.error('[razorpay] no API secret; refusing to verify.')
        return False

    if not (order_id and payment_id and signature):
        return False

    try:
        expected = hmac.new(
            cfg['key_secret'].encode('utf-8'),
            f'{order_id}|{payment_id}'.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        # compare_digest, not ==, so a timing side channel cannot leak the
        # signature byte by byte.
        return hmac.compare_digest(expected, str(signature))
    except Exception as exc:
        current_app.logger.error(f'[razorpay] checkout signature errored: {exc}')
        return False


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """
    Verify X-Razorpay-Signature: hex(HMAC-SHA256(rawBody, webhook_secret)).

    Note the key: the *webhook* secret set in the Razorpay dashboard, not the
    API secret. Using the wrong one rejects every genuine delivery.

    The raw bytes must be passed. Re-serialising parsed JSON changes key order
    and whitespace, and the signature stops matching.
    """
    cfg = _config()
    secret = cfg['webhook_secret']

    if not secret:
        current_app.logger.error(
            '[razorpay] no webhook secret configured; refusing the webhook.'
        )
        return False

    if not signature:
        return False

    try:
        body = raw_body if isinstance(raw_body, bytes) else str(raw_body).encode('utf-8')
        expected = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, str(signature))
    except Exception as exc:
        current_app.logger.error(f'[razorpay] webhook signature errored: {exc}')
        return False
