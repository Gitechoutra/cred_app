"""
portal/helpers/cashfree.py
==========================
Cashfree REST client - Payment Gateway, Payouts, and the Verification Suite.

Called over plain `requests` rather than an SDK on purpose: the surface CashU
needs is small, the signature verification is security-critical enough to want
in plain sight, and pinning an SDK adds a dependency that churns faster than
the REST contract does.

Cashfree covers three of the PRD section 21 integrations at once:
  - Payment Gateway  inbound card charge with 3DS2  (FR-006, FR-008)
  - Payouts          outbound IMPS/UPI disbursement (FR-006)
  - Verification     bank account penny-drop        (FR-005)

Every method returns a normalised dict so a swap to another vendor touches only
this file. Nothing here raises on an HTTP error - a gateway failure is an
expected business outcome, not an exception, and the caller must be able to
move the transfer into the right state rather than 500.
"""

import hashlib
import hmac
import json
from base64 import b64encode

import requests
from flask import current_app

_TIMEOUT = 30   # seconds; a 3DS order creation that takes longer has failed

_BASE_URLS = {
    'SANDBOX': 'https://sandbox.cashfree.com',
    'PRODUCTION': 'https://api.cashfree.com',
}

class CashfreeError(Exception):
    """Raised only for configuration faults, never for a declined payment."""


def _config():
    cfg = current_app.config
    env = (cfg.get('CASHFREE_ENV') or 'SANDBOX').upper()
    return {
        'env': env,
        'base_url': _BASE_URLS.get(env, _BASE_URLS['SANDBOX']),
        'app_id': cfg.get('CASHFREE_APP_ID', ''),
        'secret': cfg.get('CASHFREE_SECRET_KEY', ''),
        'api_version': cfg.get('CASHFREE_API_VERSION', '2023-08-01'),
        'webhook_secret': cfg.get('CASHFREE_WEBHOOK_SECRET', ''),
    }


def is_configured() -> bool:
    """True when real PG credentials are present."""
    cfg = _config()
    return bool(cfg['app_id'] and cfg['secret'])


def _headers(cfg: dict) -> dict:
    return {
        'Content-Type': 'application/json',
        'x-api-version': cfg['api_version'],
        'x-client-id': cfg['app_id'],
        'x-client-secret': cfg['secret'],
    }


def _request(method: str, url: str, headers: dict, payload: dict = None) -> dict:
    """
    One HTTP call, normalised.

    Returns {ok, status_code, data, error}. Network faults come back as ok=False
    rather than propagating, so the caller can mark a transfer PENDING and let
    the poller resolve it - which is exactly the ERR-005 gateway-timeout path.
    """
    try:
        response = requests.request(
            method, url, headers=headers, json=payload, timeout=_TIMEOUT
        )
    except requests.Timeout:
        current_app.logger.error(f'[cashfree] timeout calling {url}')
        return {
            'ok': False, 'status_code': 504, 'data': {},
            'error': 'Gateway timed out', 'timeout': True,
        }
    except requests.RequestException as exc:
        current_app.logger.error(f'[cashfree] transport error calling {url}: {exc}')
        return {
            'ok': False, 'status_code': 502, 'data': {},
            'error': f'Gateway unreachable: {exc}',
        }

    try:
        body = response.json()
    except ValueError:
        body = {'raw': response.text[:2000]}

    ok = 200 <= response.status_code < 300

    if not ok:
        # Log the code and the message, never the request payload - it can hold
        # a beneficiary account number.
        current_app.logger.warning(
            f'[cashfree] {method} {url} -> {response.status_code} '
            f'{body.get("message") or body.get("error") or ""}'
        )

    return {
        'ok': ok,
        'status_code': response.status_code,
        'data': body,
        'error': None if ok else (body.get('message') or body.get('error') or 'Gateway error'),
    }


# ── Payment Gateway: inbound ───────────────────────────────────────────────

def create_order(
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
    order_tags: dict = None,
) -> dict:
    """
    Create a PG order and get back a payment_session_id.

    The client SDK takes that session id and drives the hosted checkout,
    including the 3DS2 challenge (PRD FR-006 step 6). Card credentials go
    client -> Cashfree directly; they never traverse this backend, which is
    what keeps CashU inside PCI DSS SAQ-A (PRD section 18).
    """
    cfg = _config()

    payload = {
        'order_id': order_id,
        'order_amount': float(amount),
        'order_currency': 'INR',
        'customer_details': {
            'customer_id': str(customer_id),
            'customer_phone': str(customer_phone),
        },
        'order_meta': {},
    }

    if customer_email:
        payload['customer_details']['customer_email'] = customer_email
    if customer_name:
        payload['customer_details']['customer_name'] = customer_name
    if return_url:
        payload['order_meta']['return_url'] = return_url
    if notify_url:
        payload['order_meta']['notify_url'] = notify_url
    if note:
        payload['order_note'] = note[:200]
    if order_tags:
        payload['order_tags'] = {k: str(v)[:255] for k, v in order_tags.items()}

    result = _request('POST', f"{cfg['base_url']}/pg/orders", _headers(cfg), payload)

    if result['ok']:
        data = result['data']
        return {
            'ok': True,
            'order_id': data.get('order_id'),
            'cf_order_id': str(data.get('cf_order_id') or ''),
            'payment_session_id': data.get('payment_session_id'),
            'order_status': data.get('order_status'),
            'raw': data,
        }

    return {
        'ok': False,
        'error': result['error'],
        'status_code': result['status_code'],
        'timeout': result.get('timeout', False),
        'raw': result['data'],
    }


def get_order(order_id: str) -> dict:
    """
    Authoritative order status.

    The webhook is a convenience; this is the source of truth. Anything that
    credits a user or dispatches a payout confirms here first, because a
    webhook body is attacker-reachable and a signature check only proves the
    body was not tampered with in transit.
    """
    cfg = _config()
    result = _request('GET', f"{cfg['base_url']}/pg/orders/{order_id}", _headers(cfg))

    if result['ok']:
        data = result['data']
        return {
            'ok': True,
            'order_id': data.get('order_id'),
            'order_status': data.get('order_status'),   # PAID | ACTIVE | EXPIRED
            'order_amount': data.get('order_amount'),
            'raw': data,
        }

    return {'ok': False, 'error': result['error'], 'raw': result['data']}


def get_order_payments(order_id: str) -> dict:
    """Payment attempts for an order - used to read the decline reason."""
    cfg = _config()
    result = _request(
        'GET', f"{cfg['base_url']}/pg/orders/{order_id}/payments", _headers(cfg)
    )

    if result['ok']:
        payments = result['data'] if isinstance(result['data'], list) else []
        return {'ok': True, 'payments': payments}

    return {'ok': False, 'error': result['error'], 'payments': []}


def refund_payment(*, order_id: str, refund_id: str, amount, note: str = None) -> dict:
    """
    Refund to the source card.

    This is the tail of the PRD 9.4 circuit breaker: the card was charged, the
    IMPS payout failed three times, and the money must go back where it came
    from rather than sitting in a clearing account.
    """
    cfg = _config()
    payload = {
        'refund_amount': float(amount),
        'refund_id': refund_id,
        'refund_note': (note or 'Transfer reversal')[:100],
        'refund_speed': 'STANDARD',
    }

    result = _request(
        'POST', f"{cfg['base_url']}/pg/orders/{order_id}/refunds",
        _headers(cfg), payload,
    )

    if result['ok']:
        data = result['data']
        return {
            'ok': True,
            'refund_id': data.get('refund_id'),
            'cf_refund_id': str(data.get('cf_refund_id') or ''),
            'refund_status': data.get('refund_status'),
            'raw': data,
        }

    return {'ok': False, 'error': result['error'], 'raw': result['data']}


# ── Webhook verification ───────────────────────────────────────────────────

def verify_webhook_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    """
    Verify x-webhook-signature: base64(HMAC-SHA256(timestamp + rawBody, secret)).

    This is the security boundary for the entire inbound money path. A webhook
    endpoint is unauthenticated and internet-reachable, so without this check
    anyone could POST "payment succeeded" and trigger a real payout. The raw
    request body must be passed - re-serializing the parsed JSON changes key
    order and whitespace, and the signature stops matching.
    """
    cfg = _config()
    secret = cfg['webhook_secret'] or cfg['secret']

    if not secret:
        current_app.logger.error(
            '[cashfree] no webhook secret configured; refusing the webhook.'
        )
        return False

    if not signature or not timestamp:
        return False

    try:
        body_text = raw_body.decode('utf-8') if isinstance(raw_body, bytes) else str(raw_body)
        digest = hmac.new(
            secret.encode('utf-8'),
            f'{timestamp}{body_text}'.encode('utf-8'),
            hashlib.sha256,
        ).digest()
        expected = b64encode(digest).decode('utf-8')
        # compare_digest, not ==, so a timing side channel cannot leak the
        # signature byte by byte.
        return hmac.compare_digest(expected, signature)
    except Exception as exc:
        current_app.logger.error(f'[cashfree] signature verification errored: {exc}')
        return False


# ── Verification Suite: penny drop ─────────────────────────────────────────

def verify_bank_account(
    *,
    verification_id: str,
    account_number: str,
    ifsc: str,
    name: str = None,
    phone: str = None,
) -> dict:
    """
    Penny-drop a bank account and read back the CBS-registered name (FR-005).

    Cashfree sends 1 INR and returns the account holder name as the bank holds
    it. That name is what the similarity check compares against the KYC PAN
    name to prove the account belongs to this user - the PMLA control that stops
    a third-party payout.
    """
    cfg = _config()

    payload = {
        'verification_id': verification_id,
        'bank_account': account_number,
        'ifsc': ifsc,
    }
    if name:
        payload['name'] = name
    if phone:
        payload['phone'] = phone

    result = _request(
        'POST', f"{cfg['base_url']}/verification/bank-account/sync",
        _headers(cfg), payload,
    )

    if result['ok']:
        data = result['data']
        return {
            'ok': True,
            'verification_id': data.get('verification_id'),
            'reference_id': str(data.get('reference_id') or ''),
            'account_status': data.get('account_status'),   # VALID | INVALID
            'name_at_bank': data.get('name_at_bank'),
            'utr': data.get('utr'),
            'raw': data,
        }

    return {'ok': False, 'error': result['error'], 'raw': result['data']}


def verify_ifsc(ifsc: str) -> dict:
    """Resolve an IFSC to its bank and branch (FR-005 step 1)."""
    cfg = _config()
    result = _request(
        'GET', f"{cfg['base_url']}/verification/ifsc/{ifsc}", _headers(cfg)
    )

    if result['ok']:
        data = result['data']
        return {
            'ok': True,
            'bank_name': data.get('BANK'),
            'branch': data.get('BRANCH'),
            'city': data.get('CITY'),
            'state': data.get('STATE'),
            'raw': data,
        }

    return {'ok': False, 'error': result['error'], 'raw': result['data']}
