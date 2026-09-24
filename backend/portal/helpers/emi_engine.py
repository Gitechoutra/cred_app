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
    adapters, audit, emi_provider_adapter, error_recorder, ledger_engine,
    settings,
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


#: The two modes that collect over UPI rather than the card gateway. They take
#: a different vendor, a different order shape and a different confirmation
#: path, so the branch is named once here rather than repeated as a tuple
#: literal at each site.
_UPI_MODES = (PaymentMode.UPI_INTENT, PaymentMode.UPI_COLLECT)


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
    upi_app: str = None,
    upi_vpa: str = None,
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

    # One open manual attempt per obligation.
    #
    # Without this, a user who closes the UPI app and taps Pay again opens a
    # second order against the same installment, and if both get paid the EMI
    # is collected twice. The idempotency key does not help here: a deliberate
    # retry is a genuinely new request with a new key.
    #
    # Auto-pay is exempt in both directions. A mandate debit is scheduled by us
    # rather than tapped by the user, and it must not be blocked by an
    # abandoned manual attempt or block one in turn.
    if not is_auto_pay:
        in_flight = EMIPayments.query.filter(
            EMIPayments.emi_id == obligation.emi_id,
            EMIPayments.is_auto_pay.is_(False),
            EMIPayments.status.notin_(EMIPaymentState.TERMINAL),
        ).first()

        if in_flight:
            raise EMIPaymentError(
                'A payment for this EMI is already in progress.',
                ErrorCode.CONFLICT,
                recovery=(
                    'Wait for it to finish, or cancel it and start again.'
                ),
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

    reference = f'CASHU_EMI_{payment.payment_id.replace("-", "")[:24]}'
    collection = dict(
        order_id=reference,
        amount=amount,
        customer_id=str(user.user_id),
        customer_phone=user.phone,
        customer_email=user.email,
        customer_name=user.full_name,
        note=f'{obligation.provider_name} EMI',
        tags={'emi_id': obligation.emi_id, 'type': 'EMI_PAYMENT'},
    )

    # UPI collects over its own rail. Netbanking and debit card stay on the
    # card gateway, untouched.
    is_upi = payment_mode in _UPI_MODES
    order = (
        adapters.create_upi_order(**collection) if is_upi
        else adapters.create_payment_order(**collection)
    )

    if not order['ok']:
        payment.status = EMIPaymentState.FAILED
        payment.failure_code = order.get('error_code')
        payment.failure_reason = order.get('error')
        db.session.commit()

        error_recorder.record(
            user_id=payment.user_id,
            code=payment.failure_code,
            reason=payment.failure_reason,
            reference_type='EMIPayments',
            reference_id=payment.payment_id,
            payment_method=payment_mode,
            gateway=order.get('provider'),
            amount=amount,
            transaction_status=payment.status,
            gateway_response=order,
        )
        raise EMIPaymentError(
            order.get('error') or 'Could not reach the payment gateway.',
            ErrorCode.PROVIDER_ERROR,
        )

    payment.gateway_provider = order['provider']
    payment.gateway_order_id = order.get('gateway_order_id') or order.get('order_id')
    payment.checkout_url = order.get('checkout_url')
    payment.upi_app = upi_app if is_upi else None
    # The address the user asked us to collect from. `confirm_payment`
    # overwrites it with whatever actually paid, which may differ.
    if is_upi and upi_vpa:
        payment.upi_vpa = upi_vpa
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

    # Transient, not columns: the key id and paise amount are what Checkout
    # needs to open, and they are derivable from config and the row. Storing
    # them would be duplicating state that can go stale.
    payment.payment_session_id = order.get('payment_session_id')
    payment.checkout_key = order.get('public_key')
    payment.checkout_amount_paise = order.get('amount_paise')
    return payment


def confirm_payment(
    payment: EMIPayments,
    *,
    gateway_payment_id: str = None,
    signature: str = None,
) -> EMIPayments:
    """
    Confirm collection, post the ledger entry, and forward to the biller.

    Safe to call repeatedly, and safe to call concurrently. Three callers race
    for every UPI payment - the browser returning from the UPI app, the webhook
    Razorpay sends, and the poller sweeping PENDING rows - and any two of them
    can arrive in the same second.

    The status check alone does not make that safe: two callers can both read
    PROCESSING before either writes, and both go on to post a ledger entry. So
    the row is re-read under `FOR UPDATE` first. The second caller blocks,
    then wakes to find SUCCESSFUL and returns without doing anything.

    `gateway_payment_id` and `signature` come from the browser handler when
    present. The signature is verified before the id is used - an unverified id
    is discarded rather than trusted - and even a verified one only selects
    which payment to read. Whether money moved is decided by the gateway API,
    never by the caller.
    """
    # Re-read under a row lock. See the docstring: without this, two concurrent
    # confirmations both observe PROCESSING and both post to the ledger.
    # populate_existing() is load-bearing. The caller has already loaded this
    # row through an ordinary query, so it is in the session's identity map;
    # without it SQLAlchemy takes the lock and then discards the row it just
    # read in favour of the stale attributes already loaded. The lock would be
    # held while the status check below reads a value from before it - which is
    # exactly the double-post this lock exists to prevent.
    locked = (
        EMIPayments.query
        .filter_by(payment_id=payment.payment_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is not None:
        payment = locked

    if payment.status not in (EMIPaymentState.PROCESSING, EMIPaymentState.PENDING):
        db.session.commit()   # release the lock; nothing to do
        return payment

    if payment.payment_mode in _UPI_MODES:
        if gateway_payment_id and signature:
            if adapters.verify_upi_checkout_signature(
                order_id=payment.gateway_order_id,
                payment_id=gateway_payment_id,
                signature=signature,
            ):
                payment.gateway_signature = signature
            else:
                # Correct-looking payload, wrong signature. Someone is either
                # replaying or guessing; drop the id and let the order-level
                # lookup below decide from the gateway's own records.
                current_app.logger.error(
                    f'[emi] bad checkout signature for payment '
                    f'{payment.payment_id}; ignoring the supplied payment id.'
                )
                gateway_payment_id = None

        status = adapters.get_upi_payment_status(
            order_id=payment.gateway_order_id,
            payment_id=gateway_payment_id,
        )
    else:
        status = adapters.get_payment_status(payment.gateway_order_id)

    if status.get('ok') and status.get('status') == 'PENDING' and not status.get('paid'):
        # The user has not finished in their UPI app yet. Not a failure, and
        # emphatically not a success - park it for the poller.
        if status.get('gateway_payment_id'):
            payment.gateway_payment_id = status['gateway_payment_id']
        return _mark_pending(
            payment, 'Waiting for confirmation from your UPI app.'
        )

    if not status.get('ok'):
        # Cannot tell yet. Park it for the poller rather than guessing.
        return _mark_pending(payment, 'Awaiting confirmation from the bank.')

    if not status.get('paid'):
        # A failed attempt still gets its gateway id recorded - support needs
        # to be able to look up the declined payment when the user calls.
        if status.get('gateway_payment_id'):
            payment.gateway_payment_id = status['gateway_payment_id']
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

        error_recorder.record(
            user_id=payment.user_id,
            code=payment.failure_code,
            reason=payment.failure_reason,
            reference_type='EMIPayments',
            reference_id=payment.payment_id,
            transaction_id=payment.transaction_id,
            payment_method=payment.payment_mode,
            gateway=payment.gateway_provider,
            amount=payment.amount,
            transaction_status=payment.status,
            gateway_response=status.get('raw') or status,
        )
        return payment

    obligation = payment.obligation

    # Capture the gateway's identifiers before the ledger entry, so a failure
    # partway through still leaves the row traceable back to the collection.
    if status.get('gateway_payment_id'):
        payment.gateway_payment_id = status['gateway_payment_id']
    if status.get('vpa'):
        payment.upi_vpa = status['vpa']
    if status.get('rrn'):
        payment.upi_rrn = status['rrn']

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


def cancel_payment(payment: EMIPayments) -> EMIPayments:
    """
    Abandon an attempt the user backed out of, so they can start a clean one.

    Closing the UPI app is not the same as not paying. A user routinely taps
    away *after* authorising, and the debit lands seconds later - so this never
    cancels on the user's say-so. It asks the gateway what actually happened
    and only cancels when the gateway has no payment attempt to show, or when
    every attempt on the order failed.

    If money did move, this resolves the payment properly instead: the caller
    gets back a SUCCESSFUL or PENDING row, and the EMI is credited exactly as
    it would have been had the user waited on the screen.

    Cancelling is what releases the in-flight guard in `initiate_payment`, so
    this is the supported way to retry rather than accumulating dead orders.
    """
    # populate_existing() is load-bearing. The caller has already loaded this
    # row through an ordinary query, so it is in the session's identity map;
    # without it SQLAlchemy takes the lock and then discards the row it just
    # read in favour of the stale attributes already loaded. The lock would be
    # held while the status check below reads a value from before it - which is
    # exactly the double-post this lock exists to prevent.
    locked = (
        EMIPayments.query
        .filter_by(payment_id=payment.payment_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is not None:
        payment = locked

    if payment.status in EMIPaymentState.TERMINAL:
        db.session.commit()   # release the lock
        return payment

    if payment.payment_mode in _UPI_MODES:
        status = adapters.get_upi_payment_status(
            order_id=payment.gateway_order_id
        )
    else:
        status = adapters.get_payment_status(payment.gateway_order_id)

    if not status.get('ok'):
        # The gateway is unreachable, so we cannot prove nothing was collected.
        # Park it rather than cancelling an attempt that may well have paid.
        return _mark_pending(
            payment, 'Could not reach the payment gateway to confirm.'
        )

    if status.get('paid'):
        # They paid and then closed the sheet. Settle it.
        db.session.commit()   # release before confirm re-locks
        return confirm_payment(payment)

    if status.get('gateway_payment_id') and status.get('status') == 'PENDING':
        # An attempt exists and is still live - the bank has not answered yet.
        # Cancelling now would orphan a debit that may still land.
        return _mark_pending(
            payment, 'Your bank has not confirmed this payment yet.'
        )

    payment.status = EMIPaymentState.CANCELLED
    payment.failure_code = 'USER_CANCELLED'
    payment.failure_reason = 'You cancelled this payment.'
    payment.next_poll_at = None

    obligation = payment.obligation
    if obligation:
        obligation.payment_status = (
            EMIPaymentStatus.OVERDUE
            if obligation.next_due_date and obligation.next_due_date < utcnow().date()
            else EMIPaymentStatus.DUE
        )

    db.session.commit()

    audit.record(
        action='EMI_PAYMENT_CANCELLED',
        entity_type='EMIPayments',
        entity_id=payment.payment_id,
        actor_user_id=str(payment.user_id),
        after={'status': payment.status},
    )

    return payment


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
