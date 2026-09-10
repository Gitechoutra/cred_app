"""
portal/helpers/emi_engine.py
============================
Manual EMI payment (PRD FR-008, section 11).

Lifecycle:

    INITIATED -> PROCESSING -> SUCCESSFUL -> SETTLED
                     |             |
                  PENDING       REVERSED -> REFUNDED
                (poll 15m/24h)

The one rule that is enforced structurally rather than by a check: a credit card
can never pay a loan EMI. RBI prohibits servicing debt from a revolving credit
line (PRD 11.1), so CREDIT_CARD is simply absent from the PaymentMode
vocabulary - there is no value a caller could pass that would select it.
"""

from datetime import timedelta
from decimal import Decimal

from flask import current_app

from portal import db
from portal.helpers import (
    adapters, audit, emi_provider_adapter, ledger_engine, settings,
)
from portal.helpers.encryption import decrypt
from portal.helpers.helpers import ErrorCode
from portal.helpers.ledger_engine import DuplicateTransaction
from portal.models.base import utcnow
from portal.models.emi_obligations import (
    AutoPayStatus, EMIObligations, EMIPaymentStatus,
)
from portal.models.emi_payments import EMIPaymentState, EMIPayments, PaymentMode
from portal.models.master_transactions import (
    DestType, SourceType, TransactionStatus, TransactionType,
)
from portal.models.notifications import NotificationEvent


class EMIPaymentError(Exception):
    def __init__(self, message: str, code: str = ErrorCode.INTERNAL_ERROR,
                 recovery: str = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.recovery = recovery


_SOURCE_BY_MODE = {
    PaymentMode.UPI_INTENT: SourceType.UPI_VPA,
    PaymentMode.UPI_COLLECT: SourceType.UPI_VPA,
    PaymentMode.NETBANKING: SourceType.NETBANKING,
    PaymentMode.DEBIT_CARD: SourceType.DEBIT_CARD,
}


def initiate_payment(
    *,
    user,
    obligation: EMIObligations,
    amount,
    payment_mode: str,
    idempotency_key: str,
    is_auto_pay: bool = False,
    mandate_id: str = None,
) -> EMIPayments:
    """
    Open an EMI payment and create the collection order.

    Nothing is posted to the ledger yet - the user has not paid. The ledger
    entry is written when the gateway confirms collection.
    """
    amount = Decimal(str(amount))

    existing = EMIPayments.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        return existing

    if payment_mode not in PaymentMode.CHOICES:
        # Reached only by a hand-crafted request; the UI cannot offer a card.
        raise EMIPaymentError(
            'Credit cards cannot be used to pay loan EMIs. Please use UPI, '
            'netbanking or a debit card.',
            ErrorCode.INSTRUMENT_NOT_PERMITTED,
        )

    if not settings.flag_enabled(settings.Flag.EMI_MANUAL_PAY, str(user.user_id)):
        raise EMIPaymentError(
            'EMI payments are temporarily unavailable.', ErrorCode.FEATURE_DISABLED
        )

    payment = EMIPayments(
        emi_id=obligation.emi_id,
        user_id=user.user_id,
        amount=amount,
        payment_mode=payment_mode,
        is_auto_pay=is_auto_pay,
        mandate_id=mandate_id,
        idempotency_key=idempotency_key,
        status=EMIPaymentState.INITIATED,
        installment_number=(
            (obligation.total_tenure or 0) - (obligation.tenure_remaining or 0) + 1
            if obligation.total_tenure else None
        ),
        due_date=obligation.next_due_date,
    )
    db.session.add(payment)
    db.session.flush()

    order = adapters.create_payment_order(
        order_id=f'CASHU_EMI_{payment.payment_id.replace("-", "")[:24]}',
        amount=amount,
        customer_id=str(user.user_id),
        customer_phone=user.phone,
        customer_email=user.email,
        customer_name=user.full_name,
        note=f'{obligation.provider_name} EMI',
        tags={'emi_id': obligation.emi_id, 'type': 'EMI_PAYMENT'},
    )

    if not order['ok']:
        payment.status = EMIPaymentState.FAILED
        payment.failure_code = order.get('error_code')
        payment.failure_reason = order.get('error')
        db.session.commit()
        raise EMIPaymentError(
            order.get('error') or 'Could not reach the payment gateway.',
            ErrorCode.PROVIDER_ERROR,
        )

    payment.gateway_provider = order['provider']
    payment.gateway_order_id = order['order_id']
    payment.checkout_url = order.get('checkout_url')
    payment.status = EMIPaymentState.PROCESSING

    obligation.payment_status = EMIPaymentStatus.PROCESSING
    db.session.commit()

    audit.record(
        action='EMI_PAYMENT_INITIATED',
        entity_type='EMIPayments',
        entity_id=payment.payment_id,
        actor_user_id=str(user.user_id),
        after={
            'amount': float(amount),
            'provider': obligation.provider_name,
            'mode': payment_mode,
        },
    )

    payment.payment_session_id = order.get('payment_session_id')
    return payment


def confirm_payment(payment: EMIPayments) -> EMIPayments:
    """
    Confirm collection, post the ledger entry, and forward to the biller.

    Safe to call repeatedly - a payment past PROCESSING returns unchanged, so a
    webhook and a return-URL callback racing each other cannot double-post.
    """
    if payment.status not in (EMIPaymentState.PROCESSING, EMIPaymentState.PENDING):
        return payment

    status = adapters.get_payment_status(payment.gateway_order_id)

    if not status.get('ok'):
        # Cannot tell yet. Park it for the poller rather than guessing.
        return _mark_pending(payment, 'Awaiting confirmation from the bank.')

    if not status.get('paid'):
        payment.status = EMIPaymentState.FAILED
        payment.failure_code = status.get('failure_code', ErrorCode.ERR_002_3DS_FAILED)
        payment.failure_reason = status.get(
            'failure_reason', 'The payment was declined by your bank.'
        )
        obligation = payment.obligation
        obligation.payment_status = (
            EMIPaymentStatus.OVERDUE
            if obligation.next_due_date and obligation.next_due_date < utcnow().date()
            else EMIPaymentStatus.DUE
        )
        db.session.commit()
        return payment

    obligation = payment.obligation

    try:
        txn = ledger_engine.post(
            user_id=payment.user_id,
            transaction_type=(
                TransactionType.EMI_AUTO_PAY if payment.is_auto_pay
                else TransactionType.EMI_MANUAL_PAY
            ),
            gross_amount=payment.amount,
            net_amount=payment.amount,
            source_type=_SOURCE_BY_MODE.get(payment.payment_mode, SourceType.UPI_VPA),
            source_masked_ref=payment.payment_mode.replace('_', ' ').title(),
            dest_type=DestType.BBPS_BILLER_COLLECTION,
            dest_masked_ref=(
                f'{obligation.provider_name} ({obligation.masked_loan_account()})'
            ),
            gateway_provider=payment.gateway_provider,
            gateway_ref_no=payment.gateway_order_id,
            idempotency_key=f'emi_{payment.idempotency_key}',
            entries=ledger_engine.entries_for_emi_payment(
                amount=payment.amount,
                source_ref=payment.payment_mode,
                biller_ref=obligation.provider_name,
            ),
            status=TransactionStatus.PROCESSING,
            commit=False,
        )
        payment.transaction_id = txn.transaction_id
    except DuplicateTransaction as dup:
        db.session.rollback()
        payment.transaction_id = dup.transaction.transaction_id

    payment.status = EMIPaymentState.SUCCESSFUL
    payment.paid_at = utcnow()
    db.session.commit()

    return _forward_to_biller(payment)


def _forward_to_biller(payment: EMIPayments) -> EMIPayments:
    """
    Hand the collected payment to the lender over BBPS.

    A biller that is slow to acknowledge does not fail the payment - the user's
    money is collected and the obligation is served; the acknowledgement is
    chased by the poller.
    """
    obligation = payment.obligation

    result = emi_provider_adapter.submit_payment(
        provider=obligation.provider,
        loan_account_no=decrypt(obligation.loan_account_no_enc),
        amount=payment.amount,
        reference=payment.payment_id,
        payment_mode=payment.payment_mode,
    )

    if not result.get('ok'):
        current_app.logger.warning(
            f'[emi] biller submission deferred for {payment.payment_id}: '
            f'{result.get("error")}'
        )
        return _mark_pending(payment, result.get('error'))

    payment.bbps_rrn = result.get('bbps_rrn')
    payment.biller_ack_utr = result.get('biller_ack_utr')
    payment.status = EMIPaymentState.SETTLED
    payment.settled_at = utcnow()
    payment.next_poll_at = None

    _advance_obligation(obligation, payment)

    if payment.transaction_id:
        from portal.models.master_transactions import MasterTransactions
        txn = MasterTransactions.query.get(payment.transaction_id)
        if txn:
            txn.status = TransactionStatus.SUCCEEDED
            txn.bank_rrn_utr = payment.bbps_rrn

    audit.emit(
        'EMIPaidEvent',
        aggregate_type='EMIPayments',
        aggregate_id=payment.payment_id,
        user_id=str(payment.user_id),
        payload={
            'event': (
                NotificationEvent.AUTOPAY_SUCCEEDED if payment.is_auto_pay
                else NotificationEvent.EMI_PAID
            ),
            'amount': float(payment.amount),
            'provider': obligation.provider_name,
            'utr': payment.bbps_rrn,
        },
    )
    db.session.commit()

    audit.record(
        action='EMI_PAYMENT_SETTLED',
        entity_type='EMIPayments',
        entity_id=payment.payment_id,
        actor_user_id=str(payment.user_id),
        after={'amount': float(payment.amount), 'rrn': payment.bbps_rrn},
    )
    return payment


def _advance_obligation(obligation: EMIObligations, payment: EMIPayments):
    """Roll the loan forward one installment."""
    obligation.payment_status = EMIPaymentStatus.PAID
    obligation.last_paid_date = utcnow().date()

    if obligation.tenure_remaining and obligation.tenure_remaining > 0:
        obligation.tenure_remaining -= 1

    if obligation.outstanding_bal:
        obligation.outstanding_bal = max(
            Decimal('0'), Decimal(str(obligation.outstanding_bal)) - payment.amount
        )

    if obligation.tenure_remaining == 0:
        obligation.is_active = False
        obligation.closed_at = utcnow()
        obligation.next_due_date = None
    else:
        obligation.next_due_date = emi_provider_adapter.next_due_date(
            obligation.due_day_of_month, after=utcnow().date()
        )


def _mark_pending(payment: EMIPayments, reason: str = None) -> EMIPayments:
    """
    Park a payment for the polling worker (PRD FR-008: every 15 minutes for up
    to 24 hours).
    """
    payment.status = EMIPaymentState.PENDING
    payment.failure_reason = str(reason)[:500] if reason else None
    payment.next_poll_at = utcnow() + timedelta(minutes=15)
    db.session.commit()
    return payment


def poll_pending_payments(limit: int = 100) -> dict:
    """Scheduler entry point for the FR-008 polling worker."""
    due = EMIPayments.query.filter(
        EMIPayments.status == EMIPaymentState.PENDING,
        EMIPayments.next_poll_at.isnot(None),
        EMIPayments.next_poll_at <= utcnow(),
    ).limit(limit).all()

    resolved, abandoned, still_pending = 0, 0, 0

    for payment in due:
        payment.poll_attempts = (payment.poll_attempts or 0) + 1

        # 96 attempts at 15 minutes is the PRD's 24-hour ceiling.
        if payment.poll_attempts > 96:
            payment.status = EMIPaymentState.FAILED
            payment.failure_code = ErrorCode.ERR_010_BILLER_OFFLINE
            payment.failure_reason = (
                'Biller did not confirm the payment within 24 hours.'
            )
            payment.next_poll_at = None
            abandoned += 1
            db.session.commit()
            continue

        try:
            confirm_payment(payment)
            if payment.status == EMIPaymentState.SETTLED:
                resolved += 1
            else:
                payment.next_poll_at = utcnow() + timedelta(minutes=15)
                still_pending += 1
                db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error(
                f'[emi] poll failed for {payment.payment_id}: {exc}'
            )

    return {
        'checked': len(due),
        'resolved': resolved,
        'abandoned': abandoned,
        'pending': still_pending,
    }


def refresh_overdue_flags() -> int:
    """Flag obligations whose due date has passed unpaid."""
    today = utcnow().date()
    updated = EMIObligations.query.filter(
        EMIObligations.is_active.is_(True),
        EMIObligations.next_due_date.isnot(None),
        EMIObligations.next_due_date < today,
        EMIObligations.payment_status.in_(
            [EMIPaymentStatus.DUE, EMIPaymentStatus.PAID]
        ),
    ).update({'payment_status': EMIPaymentStatus.OVERDUE}, synchronize_session=False)
    db.session.commit()
    return updated
