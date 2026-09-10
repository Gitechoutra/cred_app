"""
tests/test_cashfree_webhooks.py
===============================
The security boundary on the Cashfree callback endpoints.

These endpoints are unauthenticated and internet-reachable, so the signature
check is the only thing standing between a stranger and a real IMPS payout.
Everything here exercises that check and the reference-id round trip; none of it
touches the database, because every assertion below is about a request that must
be rejected (or acknowledged as irrelevant) *before* any query runs.
"""

import hashlib
import hmac
import json
import time
from base64 import b64encode

import pytest

from portal import InitApp
from portal.helpers import transfer_engine

SECRET = 'test-webhook-secret'

PAYMENTS = '/v1/webhooks/cashfree/payments'
PAYOUTS = '/v1/webhooks/cashfree/payouts'


@pytest.fixture(scope='module')
def app():
    application = InitApp().app()
    application.config['CASHFREE_WEBHOOK_SECRET'] = SECRET
    return application


@pytest.fixture
def client(app):
    return app.test_client()


def sign(body: bytes, timestamp: str, secret: str = SECRET) -> str:
    """Reproduce Cashfree's x-webhook-signature over the exact bytes sent."""
    digest = hmac.new(
        secret.encode('utf-8'),
        f'{timestamp}{body.decode("utf-8")}'.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    return b64encode(digest).decode('utf-8')


def post(client, url, payload, *, timestamp=None, signature=None, secret=SECRET):
    body = json.dumps(payload).encode('utf-8')
    timestamp = timestamp if timestamp is not None else str(int(time.time()))
    return client.post(
        url,
        data=body,
        content_type='application/json',
        headers={
            'x-webhook-timestamp': timestamp,
            'x-webhook-signature': (
                signature if signature is not None else sign(body, timestamp, secret)
            ),
        },
    )


# -- Signature verification ------------------------------------------------

def test_valid_signature_is_accepted(client):
    """A correctly signed delivery is processed rather than refused."""
    response = post(client, PAYMENTS, {'type': 'PAYMENT_SUCCESS_WEBHOOK', 'data': {}})
    assert response.status_code == 200
    assert response.get_json()['success'] is True


def test_forged_signature_is_refused(client):
    """The whole point: an attacker who knows the URL still cannot get in."""
    response = post(client, PAYMENTS, {'type': 'PAYMENT_SUCCESS_WEBHOOK', 'data': {}},
                    signature='ZmFrZS1zaWduYXR1cmU=')
    assert response.status_code == 401


def test_signature_from_wrong_secret_is_refused(client):
    response = post(client, PAYMENTS, {'data': {}}, secret='not-the-real-secret')
    assert response.status_code == 401


def test_missing_signature_is_refused(client):
    body = json.dumps({'data': {}}).encode('utf-8')
    response = client.post(
        PAYMENTS, data=body, content_type='application/json',
        headers={'x-webhook-timestamp': str(int(time.time()))},
    )
    assert response.status_code == 401


def test_tampered_body_is_refused(client):
    """
    A signature covers the bytes, not the intent.

    Sign a ₹1 order, then swap the body for a ₹100,000 one - the classic
    amount-inflation attack, and it must not survive.
    """
    honest = json.dumps({'data': {'order': {'order_amount': 1}}}).encode('utf-8')
    timestamp = str(int(time.time()))
    forged = json.dumps({'data': {'order': {'order_amount': 100000}}}).encode('utf-8')

    response = client.post(
        PAYMENTS, data=forged, content_type='application/json',
        headers={
            'x-webhook-timestamp': timestamp,
            'x-webhook-signature': sign(honest, timestamp),
        },
    )
    assert response.status_code == 401


# -- Replay protection -----------------------------------------------------

def test_stale_delivery_is_refused(client):
    """A captured payload stays valid forever without a freshness bound."""
    stale = str(int(time.time()) - 3600)
    response = post(client, PAYMENTS, {'data': {}}, timestamp=stale)
    assert response.status_code == 401


def test_future_dated_delivery_is_refused(client):
    future = str(int(time.time()) + 3600)
    response = post(client, PAYMENTS, {'data': {}}, timestamp=future)
    assert response.status_code == 401


def test_unreadable_timestamp_is_refused(client):
    response = post(client, PAYMENTS, {'data': {}}, timestamp='not-a-timestamp')
    assert response.status_code == 401


def test_iso_timestamp_is_accepted(client):
    """Cashfree has sent ISO-8601 as well as epoch seconds across versions."""
    from datetime import datetime, timezone
    iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    response = post(client, PAYMENTS, {'data': {}}, timestamp=iso)
    assert response.status_code == 200


# -- Payout reference round trip -------------------------------------------

class _FakeTransfer:
    def __init__(self, transfer_id):
        self.transfer_id = transfer_id


def test_payout_reference_round_trips():
    """
    The payout id must survive the trip to Cashfree and back.

    It is not stored on the row - it is derived from the UUID - so if the shape
    ever changes on one side only, every payout callback silently stops
    matching its transfer and money quietly strands mid-flight.
    """
    transfer = _FakeTransfer('3f2504e0-4f89-41d3-9a0c-0305e82c3301')

    payout_id = transfer_engine.payout_request_id(transfer)
    assert payout_id == 'CASHU_PO_3f2504e04f8941d39a0c0305'

    order_id = transfer_engine.order_request_id(transfer)
    assert order_id == 'CASHU_TXF_3f2504e04f8941d39a0c0305'

    # The prefix the resolver strips back off must be the same one it sent.
    assert payout_id[len('CASHU_PO_'):] in transfer.transfer_id.replace('-', '')


def test_payout_resolver_ignores_foreign_references(app):
    """A reference this platform never issued must not resolve to a transfer."""
    with app.app_context():
        assert transfer_engine.transfer_from_payout_request_id(None) is None
        assert transfer_engine.transfer_from_payout_request_id('') is None
        assert transfer_engine.transfer_from_payout_request_id('SOMEONE_ELSE_123') is None
        assert transfer_engine.transfer_from_payout_request_id('CASHU_PO_') is None


# -- Handler behaviour on a verified delivery ------------------------------

def test_payout_without_transfer_id_is_acknowledged(client):
    """
    Verified but unusable deliveries answer 200.

    Cashfree retries any non-2xx, so answering 4xx here would buy an endless
    redelivery loop for a payload that will never become processable.
    """
    response = post(client, PAYOUTS, {'type': 'TRANSFER_SUCCESS', 'data': {}})
    assert response.status_code == 200
    assert response.get_json()['data']['handled'] is True


def test_webhook_health_reports_configuration(client):
    response = client.get('/v1/webhooks/cashfree/health')
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['signature_verification'] == 'enabled'
    assert PAYMENTS in data['endpoints']
