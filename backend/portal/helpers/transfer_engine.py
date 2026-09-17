"""
portal/helpers/transfer_engine.py
=================================
Credit-facility to bank transfer (PRD FR-006, section 9).

Owns the section 9.3 state machine end to end:

    INITIATED -> RISK_CHECKED -> AUTH_PENDING -> INBOUND_CHARGED -> SUCCEEDED
                      |                                 |
                      v                                 v
                 RISK_FAILED                    PAYOUT_PROCESSING
                                                        |
                                                        v
                                             REVERSAL_INIT -> REVERSED_TO_CARD

Two invariants hold this together:

1. **Charge before payout, always.** Money leaves only after the card charge is
   confirmed against the gateway API - never on a webhook alone, because a
   webhook body is attacker-reachable and its signature proves only that it was
   not altered in transit.

2. **A charged transfer always terminates.** If the payout fails, the circuit
   breaker retries three times and then refunds the card. There is no path
   where CashU keeps a user's money because a rail was down.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy import func

from portal import db
from portal.helpers import (
    adapters, audit, fee_calculator, ledger_engine, risk_engine, settings,
)
from portal.helpers.encryption import decrypt
from portal.helpers.helpers import ErrorCode
from portal.helpers.ledger_engine import Account, DuplicateTransaction
from portal.helpers.settings import Key
from portal.models.base import utcnow
from portal.models.master_transactions import (
    DestType, SourceType, TransactionStatus, TransactionType,
)
from portal.models.notifications import NotificationEvent
from portal.models.transfers import TransferStatus, Transfers


class TransferError(Exception):
    def __init__(self, message: str, code: str = ErrorCode.INTERNAL_ERROR,
                 recovery: str = None, details: dict = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.recovery = recovery
        self.details = details or {}


def _transition(transfer: Transfers, new_status: str, commit: bool = False):
    """
    Move the transfer, refusing any edge the state machine does not define.

    A late or duplicated webhook is the normal case this protects against: it
    must not walk a REVERSED_TO_CARD transfer back into SUCCEEDED.
    """
    if transfer.status == new_status:
        return transfer

    if not transfer.can_transition_to(new_status):
        raise TransferError(
            f'Cannot move transfer {transfer.transfer_id} from '
            f'{transfer.status} to {new_status}.',
            ErrorCode.CONFLICT,
        )

    transfer.status = new_status
    if commit:
        db.session.commit()
    return transfer


# ── Gateway-facing reference ids ───────────────────────────────────────────
# Both are derived from the transfer's UUID, which does two jobs at once: it is
# the idempotency anchor on each rail (replaying one must not charge or pay
# twice), and it lets a callback carrying only the id CashU issued be mapped
# back to the row that owns it.

_ORDER_PREFIX = 'CASHU_TXF_'
_PAYOUT_PREFIX = 'CASHU_PO_'

#: Cashfree caps these references well below a full UUID, so the hyphens are
#: stripped and the first 24 hex characters used. 96 bits of a v4 UUID is far
#: more than enough to stay unique across the transfer table.
_REF_LENGTH = 24


def _short_id(transfer: Transfers) -> str:
    return transfer.transfer_id.replace('-', '')[:_REF_LENGTH]


def order_request_id(transfer: Transfers) -> str:
    """The PG order id CashU sends for the inbound card charge."""
    return f'{_ORDER_PREFIX}{_short_id(transfer)}'


def payout_request_id(transfer: Transfers) -> str:
    """The payout transfer id CashU sends for the outbound IMPS leg."""
    return f'{_PAYOUT_PREFIX}{_short_id(transfer)}'


def transfer_from_payout_request_id(request_id: str):
    """
    Map a payout reference CashU issued back to its transfer.

    Unlike the inbound leg - where gateway_order_id is stored verbatim on the
    row and looked up by equality - the payout reference is not persisted, so
    this is a prefix match on the de-hyphenated UUID. It is narrowed to the
    statuses a payout callback can legitimately concern, which keeps it to the
    handful of in-flight rows rather than a scan of every transfer ever made.

    Returns None for a transfer that has already reached a terminal state; a
    duplicated or late webhook is then a no-op, which is the intent.
    """
    if not request_id or not request_id.startswith(_PAYOUT_PREFIX):
        return None

    prefix = request_id[len(_PAYOUT_PREFIX):].strip()
    if not prefix:
        return None

    return Transfers.query.filter(
        Transfers.status.in_([
            TransferStatus.INBOUND_CHARGED,
            TransferStatus.PAYOUT_PROCESSING,
            TransferStatus.PENDING_RECONCILIATION,
            TransferStatus.REVERSAL_INIT,
        ]),
        func.replace(Transfers.transfer_id, '-', '').like(f'{prefix}%'),
    ).first()


def quote(*, user, amount) -> dict:
    """
    Fee breakdown plus the user's remaining headroom, with nothing reserved.

    Powers the amount screen so the disclosure the PRD requires before 3DS is
    already on screen while the user is still typing.
    """
    breakdown = fee_calculator.calculate_transfer_fee(amount)
    usage = risk_engine.current_usage(user.user_id)

    daily_limit = settings.get_decimal(Key.TRANSFER_DAILY_LIMIT)
    monthly_limit = settings.get_decimal(Key.TRANSFER_MONTHLY_LIMIT)
    full_kyc_above = settings.get_decimal(Key.FULL_KYC_REQUIRED_ABOVE)

    from portal.models.users import KYCTier
    single_max = (
        settings.get_decimal(Key.TRANSFER_MAX_SINGLE_FULL_KYC)
        if user.kyc_tier == KYCTier.FULL
        else settings.get_decimal(Key.TRANSFER_MAX_SINGLE_STANDARD_KYC)
    )

    return {
        **fee_calculator.as_floats(breakdown),
        'limits': {
            'minimum': float(settings.get_decimal(Key.TRANSFER_MIN_AMOUNT)),
            'single_maximum': float(single_max),
            'daily_limit': float(daily_limit),
            'daily_used': float(usage['daily_amount']),
            'daily_remaining': float(max(Decimal('0'), daily_limit - usage['daily_amount'])),
            'monthly_limit': float(monthly_limit),
            'monthly_used': float(usage['monthly_amount']),
            'monthly_remaining': float(
                max(Decimal('0'), monthly_limit - usage['monthly_amount'])
            ),
            'full_kyc_required_above': float(full_kyc_above),
            'kyc_tier': user.kyc_tier,
        },
    }


def initiate(*, user, card, bank_account, amount, idempotency_key: str,
             device_uuid: str = None, ip: str = None) -> Transfers:
    """
    Open a transfer: risk check, price it, and create the gateway order.

    Nothing is charged here. The user still has to complete the 3DS challenge,
    and the card is only debited when the gateway says so.
    """
    amount = Decimal(str(amount))
    if amount <= Decimal('0'):
        raise TransferError('Enter a valid transfer amount.', ErrorCode.VALIDATION_ERROR)

    # Validate card status and available balance
    if not card or card.status != 'ACTIVE':
        raise TransferError('Card is not active.', ErrorCode.VALIDATION_ERROR)

    card_available = Decimal(str(
        card.available_limit if card.available_limit is not None
        else ((card.card_limit or Decimal('0')) - (card.outstanding_amount or Decimal('0')))
    ))
    if card_available < amount:
        raise TransferError('Insufficient card balance.', ErrorCode.VALIDATION_ERROR)

    # Validate bank account
    if not bank_account or not bank_account.is_active or bank_account.deleted_at is not None:
        raise TransferError('Bank account not found.', ErrorCode.NOT_FOUND)

    from portal.helpers import bank_ifsc_service
    valid_ifsc, _ = bank_ifsc_service.validate_ifsc_format(bank_account.ifsc_code)
    if not valid_ifsc:
        raise TransferError('Invalid IFSC code.', ErrorCode.VALIDATION_ERROR)

    # A replay of the same key returns the original rather than opening a
    # second transfer for the same intent (ERR-007).
    existing = Transfers.query.filter_by(idempotency_key=idempotency_key).first()
    if existing:
        current_app.logger.info(
            f'[transfer] idempotent replay for key={idempotency_key} -> '
            f'{existing.transfer_id}'
        )
        return existing

    decision = risk_engine.evaluate_transfer(
        user=user, card=card, bank_account=bank_account, amount=amount
    )

    breakdown = fee_calculator.calculate_transfer_fee(amount)

    transfer = Transfers(
        user_id=user.user_id,
        card_id=card.card_id,
        bank_account_id=bank_account.bank_account_id,
        principal_amount=breakdown['principal_amount'],
        convenience_fee=breakdown['convenience_fee'],
        gst_on_fee=breakdown['gst_on_fee'],
        total_charged_to_card=breakdown['total_charged_to_card'],
        net_payout_amount=breakdown['net_payout_amount'],
        fee_percentage_applied=breakdown['fee_percentage_applied'],
        idempotency_key=idempotency_key,
        status=TransferStatus.INITIATED,
        risk_score=decision.score,
        risk_decision=decision.decision,
        risk_reason=decision.reason,
        device_uuid=device_uuid,
        ip_address=ip,
    )
    db.session.add(transfer)
    db.session.flush()

    if not decision.approved:
        transfer.status = TransferStatus.RISK_FAILED
        transfer.failure_code = decision.error_code
        transfer.failure_reason = decision.reason
        db.session.commit()

        audit.record(
            action='TRANSFER_RISK_REJECTED',
            entity_type='Transfers',
            entity_id=transfer.transfer_id,
            actor_user_id=str(user.user_id),
            after={'amount': float(amount), 'reason': decision.reason},
        )
        raise TransferError(
            decision.reason, decision.error_code,
            recovery=decision.recovery, details=decision.details,
        )

    _transition(transfer, TransferStatus.RISK_CHECKED)

    # Carry the transfer id on the return URL so the status screen knows which
    # transfer to confirm when the issuer hands the user back, without having to
    # trust anything the redirect itself carries. It goes on as a path segment
    # because the client route is /transfer/status/<transfer_id>.
    return_url = (current_app.config.get('CASHFREE_RETURN_URL') or '').rstrip('/')
    if return_url:
        return_url = f'{return_url}/{transfer.transfer_id}'

    order = adapters.create_payment_order(
        order_id=order_request_id(transfer),
        amount=breakdown['total_charged_to_card'],
        customer_id=str(user.user_id),
        customer_phone=user.phone,
        customer_email=user.email,
        customer_name=user.full_name,
        return_url=return_url or None,
        notify_url=current_app.config.get('CASHFREE_NOTIFY_URL') or None,
        note=f'CashU transfer to {bank_account.masked_account()}',
        tags={'transfer_id': transfer.transfer_id, 'type': 'CARD_TO_BANK'},
    )

    if not order['ok']:
        transfer.status = TransferStatus.FAILED
        transfer.failure_code = order.get('error_code', ErrorCode.ERR_005_GATEWAY_TIMEOUT)
        transfer.failure_reason = order.get('error')
        db.session.commit()

        if order.get('timeout'):
            raise TransferError(
                'Payment status is pending confirmation from your bank. '
                'Please do not retry yet.',
                ErrorCode.ERR_005_GATEWAY_TIMEOUT,
                recovery='We will update you shortly.',
            )
        raise TransferError(
            order.get('error') or 'Could not reach the payment gateway.',
            ErrorCode.PROVIDER_ERROR,
        )

    transfer.gateway_provider = order['provider']
    transfer.gateway_order_id = order['order_id']
    transfer.three_ds_url = order.get('checkout_url')
    _transition(transfer, TransferStatus.AUTH_PENDING)

    audit.emit(
        'TransferInitiatedEvent',
        aggregate_type='Transfers',
        aggregate_id=transfer.transfer_id,
        user_id=str(user.user_id),
        payload={
            'amount': float(amount),
            'account': bank_account.account_last4,
        },
    )
    db.session.commit()

    audit.record(
        action='TRANSFER_INITIATED',
        entity_type='Transfers',
        entity_id=transfer.transfer_id,
        actor_user_id=str(user.user_id),
        after={
            'principal': float(breakdown['principal_amount']),
            'total_charged': float(breakdown['total_charged_to_card']),
            'card': card.masked_pan,
            'destination': bank_account.masked_account(),
        },
    )

    # Attach for the response; not persisted.
    transfer.payment_session_id = order.get('payment_session_id')
    return transfer


def confirm_charge(transfer: Transfers, *, gateway_payment_id: str = None) -> Transfers:
    """
    Confirm the card charge against the gateway and post it to the ledger.

    Called from the webhook and from the client return URL, and safe from both:
    the status is always re-read from the gateway API, and a transfer already
    past AUTH_PENDING short-circuits.
    """
    if transfer.status != TransferStatus.AUTH_PENDING:
        return transfer

    status = adapters.get_payment_status(transfer.gateway_order_id)

    if not status.get('ok'):
        current_app.logger.warning(
            f'[transfer] could not read gateway status for '
            f'{transfer.gateway_order_id}: {status.get("error")}'
        )
        return transfer

    if not status.get('paid'):
        transfer.status = TransferStatus.FAILED
        transfer.failure_code = status.get('failure_code', ErrorCode.ERR_002_3DS_FAILED)
        transfer.failure_reason = status.get(
            'failure_reason',
            'Authentication was cancelled or failed with your bank. '
            'No funds were debited.',
        )
        db.session.commit()

        audit.record(
            action='TRANSFER_CHARGE_FAILED',
            entity_type='Transfers',
            entity_id=transfer.transfer_id,
            actor_user_id=str(transfer.user_id),
            after={'reason': transfer.failure_reason},
        )
        return transfer

    # Charge confirmed. Post the double entry and consume the user's headroom
    # in a single atomic unit - a committed charge with no ledger row is the
    # exact drift the nightly self-audit exists to catch.
    try:
        txn = ledger_engine.post(
            user_id=transfer.user_id,
            transaction_type=TransactionType.CARD_TO_BANK_TRANSFER,
            gross_amount=transfer.total_charged_to_card,
            net_amount=transfer.net_payout_amount,
            fee_amount=transfer.convenience_fee,
            tax_amount=transfer.gst_on_fee,
            source_type=SourceType.CREDIT_CARD_TOKEN,
            source_masked_ref=transfer.card.masked_pan,
            dest_type=DestType.BANK_ACCOUNT_IMPS,
            dest_masked_ref=transfer.bank_account.masked_account(),
            gateway_provider=transfer.gateway_provider,
            gateway_ref_no=gateway_payment_id or transfer.gateway_order_id,
            idempotency_key=f'chg_{transfer.idempotency_key}',
            entries=ledger_engine.entries_for_transfer_charge(
                principal=transfer.principal_amount,
                fee=transfer.convenience_fee,
                gst=transfer.gst_on_fee,
                total_charged=transfer.total_charged_to_card,
                card_ref=transfer.card.masked_pan,
                bank_ref=transfer.bank_account.masked_account(),
            ),
            status=TransactionStatus.PROCESSING,
            commit=False,
        )

        transfer.transaction_id = txn.transaction_id
        transfer.gateway_payment_id = gateway_payment_id
        transfer.charged_at = utcnow()
        _transition(transfer, TransferStatus.INBOUND_CHARGED)

        risk_engine.commit_usage(transfer.user_id, transfer.principal_amount, commit=False)
        db.session.commit()

    except DuplicateTransaction as dup:
        # This charge was already posted - a webhook and a return-URL callback
        # racing each other. Adopt the original and carry on.
        db.session.rollback()
        transfer.transaction_id = dup.transaction.transaction_id
        if transfer.status == TransferStatus.AUTH_PENDING:
            transfer.status = TransferStatus.INBOUND_CHARGED
            transfer.charged_at = utcnow()
        db.session.commit()

    audit.record(
        action='TRANSFER_CHARGED',
        entity_type='Transfers',
        entity_id=transfer.transfer_id,
        actor_user_id=str(transfer.user_id),
        after={'total_charged': float(transfer.total_charged_to_card)},
    )

    return dispatch_payout(transfer)


def dispatch_payout(transfer: Transfers) -> Transfers:
    """
    Send the principal to the verified bank account.

    Only reachable once the card charge is confirmed. A failure here does not
    fail the transfer - it enters the retry ladder, and the circuit breaker
    guarantees the user is either paid or refunded.
    """
    if transfer.status not in (
        TransferStatus.INBOUND_CHARGED,
        TransferStatus.PAYOUT_PROCESSING,
        TransferStatus.PENDING_RECONCILIATION,
    ):
        return transfer

    bank = transfer.bank_account

    try:
        account_number = decrypt(bank.account_number_enc)
    except Exception as exc:
        current_app.logger.error(
            f'[transfer] cannot decrypt destination for {transfer.transfer_id}: {exc}'
        )
        transfer.status = TransferStatus.PENDING_RECONCILIATION
        transfer.failure_reason = 'Destination account could not be read.'
        db.session.commit()
        return transfer

    result = adapters.dispatch_payout(
        transfer_id=payout_request_id(transfer),
        amount=transfer.net_payout_amount,
        beneficiary_id=f'BEN_{str(bank.bank_account_id).replace("-", "")[:20]}',
        beneficiary_name=bank.verified_cbs_name or bank.account_holder_name or 'Beneficiary',
        account_number=account_number,
        ifsc=bank.ifsc_code,
        remarks='CashU transfer',
    )

    if result['ok'] and (result.get('status') or '').upper() in ('SUCCESS', 'RECEIVED', 'PENDING'):
        transfer.payout_provider = result.get('provider')
        transfer.payout_reference = result.get('payout_reference')
        transfer.bank_rrn_utr = result.get('utr')
        transfer.payout_dispatched_at = utcnow()

        if (result.get('status') or '').upper() == 'SUCCESS':
            return _settle(transfer)

        _transition(transfer, TransferStatus.PAYOUT_PROCESSING)
        db.session.commit()
        return transfer

    return _handle_payout_failure(transfer, result.get('error') or 'Payout failed.')


def _settle(transfer: Transfers) -> Transfers:
    """
    Payout confirmed: atomic balance updates and finalize transfer.
    Deducts transferred amount from source card available balance.
    Adds transferred amount to destination bank account balance.
    Saves opening and closing balances on the transfer record.
    """
    card = transfer.card
    bank_account = transfer.bank_account
    amount = Decimal(str(transfer.principal_amount))

    try:
        # Check source card balance at settlement
        curr_card_bal = Decimal(str(
            card.available_limit if card.available_limit is not None
            else ((card.card_limit or Decimal('0')) - (card.outstanding_amount or Decimal('0')))
        ))
        if curr_card_bal < amount:
            raise TransferError('Insufficient card balance.', ErrorCode.VALIDATION_ERROR)

        dest_curr_bal = Decimal(str(bank_account.balance if bank_account.balance is not None else Decimal('20000.00')))

        # Snapshots
        source_opening = curr_card_bal
        dest_opening = dest_curr_bal

        source_closing = curr_card_bal - amount
        dest_closing = dest_curr_bal + amount

        # Update card balances
        card.available_limit = source_closing
        card.outstanding_amount = Decimal(str(card.outstanding_amount or Decimal('0'))) + amount

        # Update destination bank account balance
        bank_account.balance = dest_closing

        # Save to transfer audit columns
        transfer.source_opening_balance = source_opening
        transfer.source_closing_balance = source_closing
        transfer.destination_opening_balance = dest_opening
        transfer.destination_closing_balance = dest_closing

        txn = None
        if transfer.transaction_id:
            from portal.models.master_transactions import MasterTransactions
            txn = MasterTransactions.query.get(transfer.transaction_id)

        try:
            ledger_engine.post(
                user_id=transfer.user_id,
                transaction_type=TransactionType.CARD_TO_BANK_TRANSFER,
                gross_amount=transfer.net_payout_amount,
                net_amount=transfer.net_payout_amount,
                source_type=SourceType.CREDIT_CARD_TOKEN,
                source_masked_ref=transfer.card.masked_pan,
                dest_type=DestType.BANK_ACCOUNT_IMPS,
                dest_masked_ref=transfer.bank_account.masked_account(),
                gateway_provider=transfer.payout_provider or 'SANDBOX',
                bank_rrn_utr=transfer.bank_rrn_utr,
                idempotency_key=f'pay_{transfer.idempotency_key}',
                entries=ledger_engine.entries_for_transfer_payout(
                    principal=transfer.net_payout_amount,
                    bank_ref=transfer.bank_account.masked_account(),
                ),
                status=TransactionStatus.SUCCEEDED,
                commit=False,
            )
        except DuplicateTransaction:
            pass

        if txn:
            txn.status = TransactionStatus.SUCCEEDED
            txn.bank_rrn_utr = transfer.bank_rrn_utr

        transfer.status = TransferStatus.SUCCEEDED
        transfer.payout_completed_at = utcnow()

        audit.emit(
            'TransferSucceededEvent',
            aggregate_type='Transfers',
            aggregate_id=transfer.transfer_id,
            user_id=str(transfer.user_id),
            payload={
                'event': NotificationEvent.TRANSFER_SUCCEEDED,
                'amount': float(transfer.net_payout_amount),
                'account': transfer.bank_account.account_last4,
                'utr': transfer.bank_rrn_utr,
            },
        )

        db.session.commit()

        audit.record(
            action='TRANSFER_SUCCEEDED',
            entity_type='Transfers',
            entity_id=transfer.transfer_id,
            actor_user_id=str(transfer.user_id),
            after={
                'amount': float(transfer.net_payout_amount),
                'utr': transfer.bank_rrn_utr,
                'card_balance_after': float(source_closing),
                'bank_balance_after': float(dest_closing),
            },
        )
        return transfer

    except TransferError:
        db.session.rollback()
        raise
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(f'[transfer] settlement failed for {transfer.transfer_id}: {exc}')
        raise TransferError('Transfer failed. No balance was changed.', ErrorCode.INTERNAL_ERROR)


def _handle_payout_failure(transfer: Transfers, reason: str) -> Transfers:
    """
    Circuit breaker (PRD 9.4).

    Three retries at 2, 5 and 15 minutes; then refund the card. The card is
    already charged at this point, so "give up" is not an option - the only
    acceptable terminal states are paid or refunded.
    """
    max_retries = settings.get_int(Key.PAYOUT_MAX_RETRIES)
    backoff = settings.get_list_int(Key.PAYOUT_RETRY_BACKOFF_MINUTES)

    transfer.payout_retry_count = (transfer.payout_retry_count or 0) + 1
    transfer.failure_code = ErrorCode.ERR_006_PAYOUT_FAILED
    transfer.failure_reason = str(reason)[:500]

    if transfer.payout_retry_count <= max_retries:
        delay = backoff[min(transfer.payout_retry_count - 1, len(backoff) - 1)]
        transfer.next_retry_at = utcnow() + timedelta(minutes=delay)

        if transfer.status != TransferStatus.PAYOUT_PROCESSING:
            _transition(transfer, TransferStatus.PAYOUT_PROCESSING)
        db.session.commit()

        current_app.logger.warning(
            f'[transfer] payout attempt {transfer.payout_retry_count} failed for '
            f'{transfer.transfer_id}; retry at {transfer.next_retry_at}'
        )
        return transfer

    current_app.logger.error(
        f'[transfer] payout exhausted {max_retries} retries for '
        f'{transfer.transfer_id}; reversing to card.'
    )
    return reverse_to_card(transfer, reason='Payout failed after maximum retries.')


def reverse_to_card(transfer: Transfers, *, reason: str) -> Transfers:
    """
    Refund the card and post the compensating entries (PRD 9.4 step iii).

    The user is told exactly what happened - PRD ERR-006 requires the message to
    explain that the card was charged and the money is coming back, not a bare
    "transfer failed".
    """
    if transfer.status not in (
        TransferStatus.PAYOUT_PROCESSING,
        TransferStatus.INBOUND_CHARGED,
        TransferStatus.PENDING_RECONCILIATION,
        TransferStatus.REVERSAL_INIT,
    ):
        raise TransferError(
            f'Transfer {transfer.transfer_id} cannot be reversed from '
            f'{transfer.status}.',
            ErrorCode.CONFLICT,
        )

    if transfer.status != TransferStatus.REVERSAL_INIT:
        _transition(transfer, TransferStatus.REVERSAL_INIT)
    db.session.commit()

    refund = adapters.refund_payment(
        order_id=transfer.gateway_order_id,
        refund_id=f'RFND_{transfer.transfer_id.replace("-", "")[:24]}',
        amount=transfer.total_charged_to_card,
        note=reason,
    )

    if not refund.get('ok'):
        # The refund itself failed. Park it for a human rather than pretending
        # it settled - this is precisely what the recon console is for.
        transfer.status = TransferStatus.PENDING_RECONCILIATION
        transfer.failure_reason = f'Refund failed: {refund.get("error")}'
        db.session.commit()
        current_app.logger.error(
            f'[transfer] REFUND FAILED for {transfer.transfer_id}: '
            f'{refund.get("error")} - manual intervention required.'
        )
        return transfer

    from portal.models.master_transactions import MasterTransactions

    original = (
        MasterTransactions.query.get(transfer.transaction_id)
        if transfer.transaction_id else None
    )
    if original:
        try:
            ledger_engine.reverse(
                original,
                reason=reason,
                idempotency_key=f'rev_{transfer.idempotency_key}',
                commit=False,
            )
        except DuplicateTransaction:
            db.session.rollback()

    risk_engine.release_usage(transfer.user_id, transfer.principal_amount, commit=False)

    transfer.reversal_reference = refund.get('provider_reference')
    transfer.reversed_at = utcnow()
    transfer.status = TransferStatus.REVERSED_TO_CARD

    audit.emit(
        'TransferReversedEvent',
        aggregate_type='Transfers',
        aggregate_id=transfer.transfer_id,
        user_id=str(transfer.user_id),
        payload={
            'event': NotificationEvent.TRANSFER_FAILED,
            'amount': float(transfer.total_charged_to_card),
            'reason': reason,
        },
    )
    db.session.commit()

    audit.record(
        action='TRANSFER_REVERSED',
        entity_type='Transfers',
        entity_id=transfer.transfer_id,
        actor_user_id=str(transfer.user_id),
        after={'reason': reason, 'refund_ref': transfer.reversal_reference},
    )
    return transfer


def apply_payout_callback(transfer: Transfers, *, reported_status: str = None,
                          utr: str = None, reason: str = None) -> Transfers:
    """
    Resolve an in-flight payout from a gateway callback.

    The webhook says what happened; this re-reads the payout from the provider
    before acting on it, for the same reason confirm_charge re-reads the order -
    a valid signature proves the body was not altered in transit, not that the
    money actually moved.

    Safe to call repeatedly. A transfer already past PAYOUT_PROCESSING falls
    straight through, so a duplicated or out-of-order webhook cannot re-settle
    a reversed transfer or re-reverse a settled one.
    """
    if transfer.status not in (
        TransferStatus.INBOUND_CHARGED,
        TransferStatus.PAYOUT_PROCESSING,
        TransferStatus.PENDING_RECONCILIATION,
    ):
        return transfer

    authoritative = adapters.get_payout_status(payout_request_id(transfer))

    if authoritative.get('ok'):
        status = (authoritative.get('status') or '').upper()
        utr = authoritative.get('utr') or utr
    else:
        # Provider unreachable. Fall back to what the (signature-verified)
        # webhook reported rather than leaving the transfer stuck - the retry
        # ladder and the recon job are the backstop if this call is wrong.
        current_app.logger.warning(
            f'[transfer] payout status unreadable for {transfer.transfer_id}: '
            f'{authoritative.get("error")}; falling back to webhook status.'
        )
        status = (reported_status or '').upper()

    if status == 'SUCCESS':
        transfer.bank_rrn_utr = utr or transfer.bank_rrn_utr
        if not transfer.payout_dispatched_at:
            transfer.payout_dispatched_at = utcnow()
        return _settle(transfer)

    if status in ('FAILED', 'REVERSED', 'REJECTED', 'ERROR'):
        return _handle_payout_failure(
            transfer, reason or f'Payout {status.lower()} at the beneficiary bank.'
        )

    # RECEIVED / PENDING / anything unrecognised - still in flight. Record the
    # UTR if the rail has issued one and let the retry ladder own the outcome.
    if utr and not transfer.bank_rrn_utr:
        transfer.bank_rrn_utr = utr
        db.session.commit()

    return transfer


def retry_pending_payouts(limit: int = 50) -> dict:
    """
    Scheduler entry point for the retry ladder.

    Picks up transfers whose next_retry_at has passed and pushes each one
    through dispatch_payout again.
    """
    due = Transfers.query.filter(
        Transfers.status == TransferStatus.PAYOUT_PROCESSING,
        Transfers.next_retry_at.isnot(None),
        Transfers.next_retry_at <= utcnow(),
    ).limit(limit).all()

    processed, settled, reversed_count = 0, 0, 0

    for transfer in due:
        processed += 1
        try:
            transfer.next_retry_at = None
            result = dispatch_payout(transfer)
            if result.status == TransferStatus.SUCCEEDED:
                settled += 1
            elif result.status == TransferStatus.REVERSED_TO_CARD:
                reversed_count += 1
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error(
                f'[transfer] retry failed for {transfer.transfer_id}: {exc}'
            )

    return {
        'processed': processed,
        'settled': settled,
        'reversed': reversed_count,
    }


def new_idempotency_key() -> str:
    return uuid.uuid4().hex
