"""
portal/routes/webhooks/routes.py
================================
Signed Cashfree callbacks - Payment Gateway, Payouts and Verification (PRD 21).

These endpoints are unauthenticated and internet-reachable, which makes them the
softest target on the platform: without the signature check below, anyone who
learns the URL could POST "payment succeeded" and trigger a real IMPS payout.

Four rules hold, and every handler here obeys all four:

1. **Verify before parsing.** The HMAC is computed over the exact bytes Cashfree
   sent. Re-serialising parsed JSON changes key order and whitespace and the
   signature stops matching, so the raw body is read first and the parsed dict
   is only trusted afterwards.

2. **Reject stale deliveries.** A valid signature is replayable forever without
   a freshness bound, so anything outside the timestamp window is refused.

3. **Never act on what the webhook claims.** The body is treated as a hint that
   *something* changed; the engines re-read the authoritative status from the
   provider API before money moves. A signature proves the body was not altered
   in transit - not that the payment settled.

4. **Acknowledge once handled.** Cashfree retries any non-2xx, so a verified
   delivery that concerns nothing we own still returns 200. Only an
   authentication failure answers 4xx.
"""

import json
from datetime import datetime, timezone

from flask import request
from flask_restx import Resource

from portal.helpers import (
    audit, cashfree, credit_engine, emi_engine, qr_payment_engine, razorpay,
)
from portal import db
from portal.helpers.helpers import ErrorCode, failure, success
from portal.models.credit_transactions import (
    CreditTransactions, CreditTransactionStatus, CreditTransactionType,
)
from portal.models.emi_payments import EMIPaymentState, EMIPayments
from portal.models.qr_payments import QRPayments, QRPaymentState

from . import logger, ns

#: How old a delivery may be before it is refused. Cashfree retries well inside
#: this, so the window is generous enough to absorb clock skew between their
#: sender and this host without giving a captured payload a long replay life.
MAX_SKEW_SECONDS = 300


# -- Authentication --------------------------------------------------------

def _parse_timestamp(raw: str):
    """
    Cashfree has sent both epoch seconds and ISO-8601 across API versions.

    Returns an aware UTC datetime, or None when it cannot be read - which is
    treated as an authentication failure rather than waved through.
    """
    if not raw:
        return None

    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except (TypeError, ValueError):
        pass

    try:
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        return None

    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _authenticate():
    """
    Verify a delivery and return (payload, error_response).

    On success error_response is None. On failure payload is None and the
    caller returns the error verbatim - no handler proceeds on a partial pass.
    """
    raw_body = request.get_data()
    signature = request.headers.get('x-webhook-signature')
    timestamp = request.headers.get('x-webhook-timestamp')

    if not cashfree.verify_webhook_signature(raw_body, timestamp, signature):
        logger.error(
            f'[webhook] REJECTED bad signature from {request.remote_addr} '
            f'for {request.path}'
        )
        return None, failure(
            ErrorCode.UNAUTHORIZED, 'Invalid webhook signature.', 401
        )

    sent_at = _parse_timestamp(timestamp)
    if sent_at is None:
        logger.error(f'[webhook] REJECTED unreadable timestamp: {timestamp!r}')
        return None, failure(
            ErrorCode.UNAUTHORIZED, 'Invalid webhook timestamp.', 401
        )

    age = abs((datetime.now(timezone.utc) - sent_at).total_seconds())
    if age > MAX_SKEW_SECONDS:
        logger.error(
            f'[webhook] REJECTED stale delivery: {age:.0f}s old '
            f'(limit {MAX_SKEW_SECONDS}s)'
        )
        return None, failure(
            ErrorCode.UNAUTHORIZED,
            'Webhook timestamp is outside the accepted window.',
            401,
        )

    try:
        payload = json.loads(raw_body.decode('utf-8')) if raw_body else {}
    except (UnicodeDecodeError, ValueError) as exc:
        logger.error(f'[webhook] signature valid but body is not JSON: {exc}')
        return None, failure(
            ErrorCode.VALIDATION_ERROR, 'Webhook body could not be parsed.', 400
        )

    return payload, None


def _acknowledged(message: str, **extra):
    """
    A 200 that stops Cashfree retrying.

    Used for verified deliveries that concern nothing this platform owns - an
    order placed by another product on the same merchant account, or a callback
    for a payment that already reached a terminal state.
    """
    return success({'handled': True, **extra}, message)


# -- Verification Suite: penny drop ----------------------------------------

@ns.route('/cashfree/verification')
class CashfreeVerificationWebhook(Resource):
    @ns.doc('cashfree_verification_webhook')
    def post(self):
        """
        Penny-drop callback (PRD FR-005).

        Bank-account verification runs against Cashfree's *synchronous*
        endpoint, so the result is already recorded by the time this fires and
        the name match has been scored. This handler exists so an async delivery
        is authenticated and auditable rather than dropped - it records what
        arrived and does not re-decide payout eligibility, because doing so from
        a callback would bypass the name-similarity check that makes an account
        eligible in the first place.
        """
        payload, error = _authenticate()
        if error:
            return error

        data = payload.get('data') or {}
        event_type = payload.get('type') or 'UNKNOWN'
        verification_id = data.get('verification_id') or data.get('verificationId')

        logger.info(
            f'[webhook] verification {event_type} for {verification_id}: '
            f'{data.get("account_status")}'
        )

        audit.record(
            action='WEBHOOK_VERIFICATION_RECEIVED',
            entity_type='PennyDropVerifications',
            entity_id=verification_id,
            after={
                'event': event_type,
                'account_status': data.get('account_status'),
                'name_at_bank': data.get('name_at_bank'),
            },
            notes='Cashfree verification callback',
        )

        return _acknowledged(
            'Verification callback recorded.', verification_id=verification_id
        )


# -- Operability -----------------------------------------------------------

@ns.route('/cashfree/health')
class WebhookHealth(Resource):
    @ns.doc('webhook_health')
    def get(self):
        """
        Reachability probe for the Cashfree dashboard's endpoint test.

        Reports whether a webhook secret is configured, because the single most
        common cause of "every delivery returns 401" is that it is not.
        """
        return success({
            'endpoints': [
                '/v1/webhooks/cashfree/payments',
                '/v1/webhooks/cashfree/payouts',
                '/v1/webhooks/cashfree/verification',
            ],
            'signature_verification': 'enabled',
            'credentials_configured': cashfree.is_configured(),
            'max_skew_seconds': MAX_SKEW_SECONDS,
        }, 'Webhook receiver is reachable.')


# -- Razorpay: UPI collection for EMI payments ------------------------------

#: Deliveries this endpoint acts on. Everything else verified is acknowledged
#: and dropped - Razorpay sends the full event stream for the account, and a
#: 4xx on an event we simply do not care about would put the endpoint into
#: their retry-and-disable path.
_RAZORPAY_ACTIONABLE = {
    'payment.captured',
    'payment.failed',
    'payment.authorized',
    'order.paid',
}


def _authenticate_razorpay():
    """
    Verify a Razorpay delivery and return (payload, error_response).

    Razorpay signs the raw body with the dashboard webhook secret and sends no
    timestamp header, so freshness is taken from `created_at` inside the signed
    body - which the signature already protects from tampering.
    """
    raw_body = request.get_data()
    signature = request.headers.get('X-Razorpay-Signature')

    if not razorpay.verify_webhook_signature(raw_body, signature):
        logger.error(
            f'[webhook] REJECTED bad Razorpay signature from '
            f'{request.remote_addr} for {request.path}'
        )
        return None, failure(
            ErrorCode.UNAUTHORIZED, 'Invalid webhook signature.', 401
        )

    try:
        payload = json.loads(raw_body.decode('utf-8')) if raw_body else {}
    except (UnicodeDecodeError, ValueError) as exc:
        logger.error(f'[webhook] Razorpay signature valid but body is not JSON: {exc}')
        return None, failure(
            ErrorCode.VALIDATION_ERROR, 'Webhook body could not be parsed.', 400
        )

    created_at = payload.get('created_at')
    if created_at is not None:
        sent_at = _parse_timestamp(created_at)
        if sent_at is None:
            logger.error(f'[webhook] Razorpay created_at unreadable: {created_at!r}')
            return None, failure(
                ErrorCode.UNAUTHORIZED, 'Invalid webhook timestamp.', 401
            )

        age = abs((datetime.now(timezone.utc) - sent_at).total_seconds())
        if age > MAX_SKEW_SECONDS:
            logger.error(
                f'[webhook] REJECTED stale Razorpay delivery: {age:.0f}s old '
                f'(limit {MAX_SKEW_SECONDS}s)'
            )
            return None, failure(
                ErrorCode.UNAUTHORIZED,
                'Webhook timestamp is outside the accepted window.',
                401,
            )

    return payload, None


def _handle_razorpay_qr(event: str, order_id: str, rzp_payment_id: str):
    """
    Resolve a Razorpay delivery that belongs to a scanned QR payment.

    The webhook is the authoritative confirmation: the browser callback is a
    hint, and a payment is only settled here or by the engine re-reading the
    order from Razorpay. Never by what the client reports.
    """
    payment = QRPayments.query.filter_by(gateway_order_id=order_id).first()

    if not payment:
        # Neither an EMI nor a QR payment. The merchant account may serve more
        # than this platform, so acknowledge rather than error.
        logger.info(f'[webhook] no EMI or QR payment for order {order_id} ({event})')
        return _acknowledged('No matching payment.', order_id=order_id)

    logger.info(
        f'[webhook] {event} for QR payment {payment.qr_payment_id} '
        f'(status {payment.status})'
    )

    if payment.status in QRPaymentState.TERMINAL:
        return _acknowledged(
            'QR payment already in a terminal state.',
            qr_payment_id=payment.qr_payment_id,
            status=payment.status,
        )

    try:
        payment = qr_payment_engine.confirm(
            payment, gateway_payment_id=rzp_payment_id
        )
    except Exception as exc:
        db.session.rollback()
        logger.error(
            f'[webhook] QR confirm failed for {payment.qr_payment_id}: {exc}'
        )
        return _acknowledged(
            'Received; the payment could not be advanced and has been logged.',
            qr_payment_id=payment.qr_payment_id,
        )

    audit.record(
        action='QR_PAYMENT_WEBHOOK',
        entity_type='QRPayments',
        entity_id=payment.qr_payment_id,
        after={'event': event, 'status': payment.status},
    )

    return _acknowledged(
        'QR payment callback processed.',
        qr_payment_id=payment.qr_payment_id,
        status=payment.status,
    )


def _handle_razorpay_credit_bill(event: str, bill, rzp_payment_id: str):
    """
    Resolve a delivery for a credit card bill payment.

    What makes a bill payment survive the payer closing the browser straight
    after paying: no verify call arrives then, and this is what restores their
    credit. The body is still only a hint - settle_bill_payment re-reads the
    payment from Razorpay, so a delivery claiming `captured` cannot restore
    credit for a payment Razorpay's own API says failed.
    """
    logger.info(
        f'[webhook] {event} for credit bill payment '
        f'{bill.credit_transaction_id} (status {bill.status})'
    )

    if bill.status != CreditTransactionStatus.PROCESSING:
        return _acknowledged(
            'Payment already resolved.',
            credit_transaction_id=bill.credit_transaction_id,
            status=bill.status,
        )

    try:
        bill = credit_engine.settle_bill_payment(
            bill, gateway_payment_id=rzp_payment_id,
        )
    except Exception as exc:
        # 200 anyway: a retry replays the same fault, and the bill-payment
        # poller already owns recovery.
        db.session.rollback()
        logger.exception(
            f'[webhook] settle failed for {bill.credit_transaction_id}: {exc}'
        )
        return _acknowledged(
            'Received; the payment could not be advanced and has been logged.',
            credit_transaction_id=bill.credit_transaction_id,
        )

    return _acknowledged(
        'Credit bill payment callback processed.',
        credit_transaction_id=bill.credit_transaction_id,
        status=bill.status,
    )


@ns.route('/razorpay')
class RazorpayWebhook(Resource):
    @ns.doc('razorpay_webhook')
    def post(self):
        """
        UPI collection callback for EMI payments (PRD FR-008).

        This is what makes the flow survive the user. If they authorise the
        payment and then kill the browser, no verify call ever arrives - this
        delivery is the only thing that credits the EMI, and it is why an
        interrupted payment resolves itself instead of stranding money.

        It obeys the same four rules as the Cashfree handlers above. The one
        worth restating: the body is a hint that something changed, never the
        thing acted on. `confirm_payment` re-reads the payment from Razorpay
        before the ledger is touched, so a delivery claiming `captured` cannot
        settle an EMI that Razorpay's own API says failed.
        """
        payload, error = _authenticate_razorpay()
        if error:
            return error

        event = payload.get('event') or 'UNKNOWN'
        entities = (payload.get('payload') or {})
        payment_entity = (entities.get('payment') or {}).get('entity') or {}
        order_entity = (entities.get('order') or {}).get('entity') or {}

        if event not in _RAZORPAY_ACTIONABLE:
            return _acknowledged(f'Event {event} needs no action.')

        order_id = payment_entity.get('order_id') or order_entity.get('id')
        rzp_payment_id = payment_entity.get('id')

        if not order_id:
            logger.warning(f'[webhook] Razorpay {event} carried no order id')
            return _acknowledged('No order id in payload; nothing to do.')

        payment = EMIPayments.query.filter_by(gateway_order_id=order_id).first()

        if not payment:
            # Several products collect through the same Razorpay account, so an
            # order that is not an EMI payment may be a credit card bill, or a
            # scanned QR payment.
            bill = CreditTransactions.query.filter_by(
                gateway_order_id=order_id,
                transaction_type=CreditTransactionType.PAYMENT,
            ).first()
            if bill:
                return _handle_razorpay_credit_bill(event, bill, rzp_payment_id)
            return _handle_razorpay_qr(event, order_id, rzp_payment_id)

        logger.info(
            f'[webhook] {event} for EMI payment {payment.payment_id} '
            f'(status {payment.status})'
        )

        if payment.status in EMIPaymentState.TERMINAL:
            # A late duplicate, or the browser already resolved it. Both are
            # normal; the row is finished either way.
            return _acknowledged(
                'Payment already in a terminal state.',
                payment_id=payment.payment_id,
                status=payment.status,
            )

        try:
            # No signature is passed: the handler signature belongs to the
            # browser flow. The payment id is a lookup hint and confirm_payment
            # re-reads it from the API regardless.
            payment = emi_engine.confirm_payment(
                payment, gateway_payment_id=rzp_payment_id
            )
        except Exception as exc:
            # Answer 200 anyway. A retry replays the same fault, and the
            # pending-payment poller already owns the recovery path.
            logger.exception(
                f'[webhook] confirm_payment failed for {payment.payment_id}: {exc}'
            )
            return _acknowledged(
                'Received; the payment could not be advanced and has been logged.',
                payment_id=payment.payment_id,
            )

        audit.record(
            action='WEBHOOK_UPI_PAYMENT_RECEIVED',
            entity_type='EMIPayments',
            entity_id=payment.payment_id,
            after={'event': event, 'status': payment.status},
            notes=f'Razorpay callback for order {order_id}',
        )

        return _acknowledged(
            'UPI callback processed.',
            payment_id=payment.payment_id,
            status=payment.status,
        )
