"""
portal/helpers/qr_payment_engine.py
===================================
Scanned UPI payments to a merchant.

Follows the EMI payment engine rather than the transfer engine, because the
shape is the same: collect over UPI, confirm from the gateway, post the ledger
entry once, never on the client's word. What differs is the destination - a
third party's address rather than the user's own account - so none of the
penny-drop or card-limit machinery applies.

The two rules that carry over unchanged:

- confirmation re-reads the payment from the gateway before the ledger moves;
- confirmation takes a row lock first, because the browser, the webhook and the
  poller can all arrive at once.
"""

from decimal import Decimal

from flask import current_app

from portal import db
from portal.helpers import adapters, audit, error_recorder, ledger_engine, upi_qr
from portal.helpers.helpers import ErrorCode
from portal.helpers.ledger_engine import DuplicateTransaction
from portal.models.base import utcnow
from portal.models.master_transactions import (
    DestType, SourceType, TransactionStatus, TransactionType,
)
from portal.models.qr_payments import QRPaymentState, QRPayments


class QRPaymentError(Exception):
    def __init__(self, message, code=ErrorCode.INTERNAL_ERROR, recovery=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.recovery = recovery


def initiate(*, user, details: dict, amount, idempotency_key: str) -> QRPayments:
    """
    Open a scanned payment.

    `details` is the validated output of upi_qr.parse - never raw scanned text.
    `amount` is what the user confirmed: the QR's figure when it carried one,
    otherwise what they typed.

    Nothing is posted to the ledger here. The user has not paid yet.
    """
    amount = Decimal(str(amount))

    existing = QRPayments.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        return existing

    # A QR that fixes the amount must not be paid for a different one. The
    # client shows the field disabled, but the client is not the enforcement.
    if details.get('amount_locked'):
        if amount != Decimal(str(details['amount'])):
            raise QRPaymentError(
                'This QR code is for a fixed amount and it cannot be changed.',
                ErrorCode.VALIDATION_ERROR,
            )

    payment = QRPayments(
        user_id=user.user_id,
        payee_vpa=details['vpa'],
        payee_name=details.get('payee_name'),
        amount=amount,
        amount_from_qr=bool(details.get('amount_locked')),
        note=details.get('note'),
        payee_reference=details.get('reference'),
        idempotency_key=idempotency_key,
        status=QRPaymentState.INITIATED,
    )
    db.session.add(payment)
    db.session.flush()

    reference = f'CASHU_QR_{payment.qr_payment_id.replace("-", "")[:24]}'

    order = adapters.create_razorpay_order(
        order_id=reference,
        amount=amount,
        customer_id=str(user.user_id),
        customer_phone=user.phone,
        customer_email=user.email,
        customer_name=user.full_name,
        note=f'Payment to {details.get("payee_name") or details["vpa"]}',
        tags={'type': 'QR_UPI_PAYMENT', 'qr_payment_id': payment.qr_payment_id},
    )

    if not order['ok']:
        payment.status = QRPaymentState.FAILED
        payment.failure_code = order.get('error_code')
        payment.failure_reason = order.get('error')
        db.session.commit()

        error_recorder.record(
            user_id=user.user_id,
            code=payment.failure_code,
            reason=payment.failure_reason,
            reference_type='QRPayments',
            reference_id=payment.qr_payment_id,
            payment_method='UPI_QR',
            gateway=order.get('provider'),
            amount=amount,
            transaction_status=payment.status,
            gateway_response=order,
        )

        raise QRPaymentError(
            order.get('error') or 'Could not reach the payment gateway.',
            ErrorCode.PROVIDER_ERROR,
        )

    payment.gateway_provider = order['provider']
    payment.gateway_order_id = order.get('gateway_order_id') or order.get('order_id')
    payment.status = QRPaymentState.PROCESSING
    db.session.commit()

    audit.record(
        action='QR_PAYMENT_INITIATED',
        entity_type='QRPayments',
        entity_id=payment.qr_payment_id,
        actor_user_id=str(user.user_id),
        after={
            'amount': float(amount),
            'payee': upi_qr.masked_vpa(details['vpa']),
        },
    )

    # Transient, for the response only.
    payment.checkout_key = order.get('public_key')
    payment.checkout_amount_paise = order.get('amount_paise')
    return payment


def confirm(payment: QRPayments, *, gateway_payment_id=None, signature=None):
    """
    Confirm collection and post the ledger entry.

    Safe to call repeatedly and concurrently: the row is re-read under a lock
    before the status is examined, so two callers cannot both post.
    """
    # populate_existing() is load-bearing. The caller has already loaded this
    # row through an ordinary query, so it is in the session's identity map;
    # without it SQLAlchemy takes the lock and then discards the row it just
    # read in favour of the stale attributes already loaded. The lock would be
    # held while the status check below reads a value from before it - which is
    # exactly the double-post this lock exists to prevent.
    locked = (
        QRPayments.query
        .filter_by(qr_payment_id=payment.qr_payment_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is not None:
        payment = locked

    if payment.status in QRPaymentState.TERMINAL:
        db.session.commit()
        return payment

    if gateway_payment_id and signature:
        if adapters.verify_razorpay_signature(
            order_id=payment.gateway_order_id,
            payment_id=gateway_payment_id,
            signature=signature,
        ):
            payment.gateway_signature = signature
        else:
            current_app.logger.error(
                f'[qr] bad checkout signature for {payment.qr_payment_id}; '
                f'ignoring the supplied payment id.'
            )
            gateway_payment_id = None

    status = adapters.get_razorpay_payment_status(
        order_id=payment.gateway_order_id,
        payment_id=gateway_payment_id,
    )

    if not status.get('ok'):
        return _park(payment, 'Waiting for confirmation from your bank.')

    if status.get('status') == 'PENDING' and not status.get('paid'):
        if status.get('gateway_payment_id'):
            payment.gateway_payment_id = status['gateway_payment_id']
        return _park(payment, 'Waiting for confirmation from your UPI app.')

    if not status.get('paid'):
        payment.status = QRPaymentState.FAILED
        payment.failure_code = status.get('failure_code', 'UPI_FAILED')
        payment.failure_reason = status.get(
            'failure_reason', 'The payment was not completed.'
        )
        if status.get('gateway_payment_id'):
            payment.gateway_payment_id = status['gateway_payment_id']
        db.session.commit()

        error_recorder.record(
            user_id=payment.user_id,
            code=payment.failure_code,
            reason=payment.failure_reason,
            reference_type='QRPayments',
            reference_id=payment.qr_payment_id,
            payment_method='UPI_QR',
            gateway=payment.gateway_provider,
            amount=payment.amount,
            transaction_status=payment.status,
            gateway_response=status.get('raw') or status,
        )
        return payment

    if status.get('gateway_payment_id'):
        payment.gateway_payment_id = status['gateway_payment_id']
    if status.get('vpa'):
        payment.payer_vpa = status['vpa']
    if status.get('rrn'):
        payment.upi_rrn = status['rrn']

    try:
        txn = ledger_engine.post(
            user_id=payment.user_id,
            transaction_type=TransactionType.QR_UPI_PAYMENT,
            gross_amount=payment.amount,
            net_amount=payment.amount,
            source_type=SourceType.UPI_VPA,
            source_masked_ref=upi_qr.masked_vpa(payment.payer_vpa or 'UPI'),
            dest_type=DestType.MERCHANT_VPA,
            dest_masked_ref=(
                payment.payee_name or upi_qr.masked_vpa(payment.payee_vpa)
            ),
            gateway_provider=payment.gateway_provider,
            gateway_ref_no=payment.gateway_payment_id or payment.gateway_order_id,
            idempotency_key=f'qr_{payment.idempotency_key}',
            entries=ledger_engine.entries_for_qr_payment(
                amount=payment.amount,
                payer_ref=upi_qr.masked_vpa(payment.payer_vpa or 'UPI'),
                payee_ref=payment.payee_name or upi_qr.masked_vpa(payment.payee_vpa),
            ),
            status=TransactionStatus.SUCCEEDED,
            commit=False,
        )
        payment.transaction_id = txn.transaction_id
    except DuplicateTransaction as dup:
        db.session.rollback()
        payment.transaction_id = dup.transaction.transaction_id

    payment.status = QRPaymentState.SUCCESSFUL
    payment.paid_at = utcnow()
    db.session.commit()

    audit.record(
        action='QR_PAYMENT_COMPLETED',
        entity_type='QRPayments',
        entity_id=payment.qr_payment_id,
        actor_user_id=str(payment.user_id),
        after={'amount': float(payment.amount), 'status': payment.status},
    )
    return payment


def cancel(payment: QRPayments) -> QRPayments:
    """
    Abandon a scan the user backed out of.

    Asks the gateway first, exactly as the EMI path does: closing a UPI sheet
    after approving is common, and the debit still lands.
    """
    # populate_existing() is load-bearing. The caller has already loaded this
    # row through an ordinary query, so it is in the session's identity map;
    # without it SQLAlchemy takes the lock and then discards the row it just
    # read in favour of the stale attributes already loaded. The lock would be
    # held while the status check below reads a value from before it - which is
    # exactly the double-post this lock exists to prevent.
    locked = (
        QRPayments.query
        .filter_by(qr_payment_id=payment.qr_payment_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is not None:
        payment = locked

    if payment.status in QRPaymentState.TERMINAL:
        db.session.commit()
        return payment

    status = adapters.get_razorpay_payment_status(
        order_id=payment.gateway_order_id
    )

    if not status.get('ok'):
        return _park(payment, 'Could not reach the payment gateway to confirm.')

    if status.get('paid'):
        db.session.commit()
        return confirm(payment)

    if status.get('gateway_payment_id') and status.get('status') == 'PENDING':
        return _park(payment, 'Your bank has not confirmed this payment yet.')

    payment.status = QRPaymentState.CANCELLED
    payment.failure_code = 'USER_CANCELLED'
    payment.failure_reason = 'You cancelled this payment.'
    db.session.commit()
    return payment


def _park(payment: QRPayments, reason: str) -> QRPayments:
    payment.status = QRPaymentState.PENDING
    payment.failure_reason = str(reason)[:500]
    db.session.commit()
    return payment
