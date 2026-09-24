"""
portal/helpers/mandate_engine.py
================================
NPCI e-Mandate / UPI AutoPay engine (PRD FR-009, section 12).

Four regulatory obligations from the PRD 12.2 compliance checklist are enforced
here, not left to the caller:

  AFA at registration    a mandate starts PENDING_AFA and cannot debit until an
                         additional-factor challenge completes
  Pre-debit notice       dispatched at least 24h before every debit; the RBI
                         e-mandate framework makes this non-negotiable
  User revocation        pause or cancel available up to 24h before the debit
  Post-debit confirmation  sent on every execution, success or failure

The retry ladder (12.3) is deliberately spread across the day rather than
retried immediately: attempt 2 lands at 11:30 the next morning because the
common failure is an account that is empty before payday, and a retry ten
minutes later would just bounce again and cost the user a second bounce charge.
"""

from datetime import date, timedelta
from decimal import Decimal

from flask import current_app

from portal import db
from portal.helpers import audit, emi_fees, emi_provider_adapter, settings
from portal.helpers.helpers import ErrorCode
from portal.helpers.settings import Key
from portal.models.auto_pay_mandates import (
    AutoPayMandates, MandateFrequency, MandateStatus, MandateType,
)
from portal.models.base import utcnow
from portal.models.emi_obligations import AutoPayStatus, EMIPaymentStatus
from portal.models.mandate_debit_attempts import (
    DebitAttemptResult, MandateDebitAttempts,
)
from portal.models.notifications import NotificationEvent

#: PRD 12.3 ladder: (attempt number, days after due date, hour, minute)
RETRY_LADDER = [
    (1, 0, 4, 0),     # due date, 04:00 IST
    (2, 1, 11, 30),   # T+1, 11:30 IST - post-salary window
    (3, 2, 18, 0),    # T+2, 18:00 IST - final
]


class MandateError(Exception):
    def __init__(self, message: str, code: str = ErrorCode.INTERNAL_ERROR):
        super().__init__(message)
        self.message = message
        self.code = code


def choose_type(emi_amount) -> str:
    """
    Pick the rail (PRD 12.1).

    UPI AutoPay up to 15,000 needs no per-debit OTP, which is a materially
    better experience; above that only e-NACH is available.
    """
    amount = Decimal(str(emi_amount))
    upi_max = settings.get_decimal(Key.UPI_AUTOPAY_MAX_AMOUNT)
    return MandateType.UPI_AUTOPAY if amount <= upi_max else MandateType.ENACH


def register(
    *,
    user,
    obligation,
    max_amount=None,
    bank_account_id: str = None,
    upi_vpa: str = None,
    frequency: str = MandateFrequency.MONTHLY,
    end_date: date = None,
) -> AutoPayMandates:
    """
    Create a mandate in PENDING_AFA.

    It cannot debit anything until complete_afa() runs - which is the point: RBI
    requires an additional-factor challenge at registration, and a mandate that
    could debit before that challenge would be an unauthorised standing
    instruction.
    """
    existing = AutoPayMandates.query.filter_by(emi_id=obligation.emi_id).first()
    if existing and existing.status in (MandateStatus.ACTIVE, MandateStatus.PENDING_AFA):
        raise MandateError(
            'An auto-pay mandate already exists for this EMI.', ErrorCode.CONFLICT
        )

    if not settings.flag_enabled(settings.Flag.EMI_AUTO_PAY, str(user.user_id)):
        raise MandateError(
            'Auto-pay is temporarily unavailable.', ErrorCode.FEATURE_DISABLED
        )

    minimum_cap = emi_fees.mandate_cap(obligation.emi_amount)
    cap = Decimal(str(max_amount)) if max_amount else minimum_cap

    if cap < minimum_cap:
        raise MandateError(
            f'The mandate limit must be at least Rs. {minimum_cap:,.2f} '
            f'(110% of your EMI) to absorb interest adjustments.',
            ErrorCode.VALIDATION_ERROR,
        )

    mandate_type = choose_type(obligation.emi_amount)
    enach_max = settings.get_decimal(Key.ENACH_MAX_AMOUNT)
    if cap > enach_max:
        raise MandateError(
            f'The mandate limit cannot exceed Rs. {enach_max:,.2f}.',
            ErrorCode.VALIDATION_ERROR,
        )

    if existing:
        mandate = existing
        mandate.status = MandateStatus.PENDING_AFA
    else:
        mandate = AutoPayMandates(user_id=user.user_id, emi_id=obligation.emi_id)
        db.session.add(mandate)

    mandate.mandate_type = mandate_type
    mandate.bank_account_id = bank_account_id
    mandate.upi_vpa = upi_vpa
    mandate.max_amount = cap
    mandate.frequency = frequency
    mandate.start_date = utcnow().date()
    mandate.end_date = end_date
    mandate.next_debit_date = obligation.next_due_date or (
        emi_provider_adapter.next_due_date(obligation.due_day_of_month)
    )
    mandate.consecutive_failures = 0

    db.session.commit()

    audit.record(
        action='MANDATE_REGISTRATION_STARTED',
        entity_type='AutoPayMandates',
        entity_id=mandate.mandate_id,
        actor_user_id=str(user.user_id),
        after={
            'type': mandate_type,
            'cap': float(cap),
            'emi': obligation.provider_name,
        },
    )
    return mandate


def complete_afa(mandate: AutoPayMandates, *, provider_reference: str = None) -> AutoPayMandates:
    """
    Activate a mandate once the AFA challenge succeeds.

    NPCI issues the Unique Mandate Number here; it is what every pre-debit
    notice and debit instruction references thereafter.
    """
    if mandate.status != MandateStatus.PENDING_AFA:
        raise MandateError(
            f'Mandate is {mandate.status}; only a PENDING_AFA mandate can be '
            'activated.',
            ErrorCode.CONFLICT,
        )

    import uuid
    mandate.mandate_umn = f'CASHU{uuid.uuid4().hex[:16].upper()}'
    mandate.provider_reference = provider_reference
    mandate.status = MandateStatus.ACTIVE
    mandate.afa_completed_at = utcnow()
    mandate.activated_at = utcnow()

    obligation = mandate.obligation
    obligation.auto_pay_status = AutoPayStatus.ACTIVE

    db.session.commit()

    audit.record(
        action='MANDATE_ACTIVATED',
        entity_type='AutoPayMandates',
        entity_id=mandate.mandate_id,
        actor_user_id=str(mandate.user_id),
        after={'umn': mandate.mandate_umn},
    )
    return mandate


def pause(mandate: AutoPayMandates, reason: str = None) -> AutoPayMandates:
    """
    Pause a mandate (PRD 12.2 user revocation facility).

    Refused inside 24 hours of the debit: by then the instruction is with the
    sponsor bank and stopping it is no longer within CashU's control. Saying so
    is better than accepting the pause and letting the debit happen anyway.
    """
    if mandate.status != MandateStatus.ACTIVE:
        raise MandateError(f'Mandate is {mandate.status}.', ErrorCode.CONFLICT)

    if mandate.next_debit_date:
        hours_remaining = (
            (mandate.next_debit_date - utcnow().date()).days * 24
        )
        if hours_remaining < 24:
            raise MandateError(
                'This mandate cannot be paused within 24 hours of the scheduled '
                'debit. Please contact your bank directly.',
                ErrorCode.CONFLICT,
            )

    mandate.status = MandateStatus.PAUSED
    mandate.paused_at = utcnow()
    mandate.obligation.auto_pay_status = AutoPayStatus.PAUSED
    db.session.commit()

    audit.record(
        action='MANDATE_PAUSED',
        entity_type='AutoPayMandates',
        entity_id=mandate.mandate_id,
        actor_user_id=str(mandate.user_id),
        notes=reason,
    )
    return mandate


def resume(mandate: AutoPayMandates) -> AutoPayMandates:
    if mandate.status != MandateStatus.PAUSED:
        raise MandateError(f'Mandate is {mandate.status}.', ErrorCode.CONFLICT)

    mandate.status = MandateStatus.ACTIVE
    mandate.paused_at = None
    mandate.obligation.auto_pay_status = AutoPayStatus.ACTIVE
    mandate.next_debit_date = emi_provider_adapter.next_due_date(
        mandate.obligation.due_day_of_month
    )
    db.session.commit()

    audit.record(
        action='MANDATE_RESUMED',
        entity_type='AutoPayMandates',
        entity_id=mandate.mandate_id,
        actor_user_id=str(mandate.user_id),
    )
    return mandate


def revoke(mandate: AutoPayMandates, reason: str = None) -> AutoPayMandates:
    mandate.status = MandateStatus.REVOKED
    mandate.revoked_at = utcnow()
    mandate.revoked_reason = reason
    mandate.next_debit_date = None
    mandate.obligation.auto_pay_status = AutoPayStatus.NOT_CONFIGURED
    db.session.commit()

    audit.record(
        action='MANDATE_REVOKED',
        entity_type='AutoPayMandates',
        entity_id=mandate.mandate_id,
        actor_user_id=str(mandate.user_id),
        notes=reason,
    )
    return mandate


# ── Scheduled jobs ─────────────────────────────────────────────────────────

def send_predebit_notices() -> dict:
    """
    Dispatch T-48h pre-debit notices (PRD 12.2).

    The most compliance-sensitive job in the platform: RBI requires notice at
    least 24 hours before a recurring debit, and CashU sends at 48 to leave the
    user a working day to fund the account.

    predebit_notice_sent_for guards against a double send if the scheduler
    reruns, without which a restart would notify every user twice.
    """
    notice_hours = settings.get_int(Key.MANDATE_PREDEBIT_NOTICE_HOURS)
    target_date = utcnow().date() + timedelta(hours=notice_hours)

    due = AutoPayMandates.query.filter(
        AutoPayMandates.status == MandateStatus.ACTIVE,
        AutoPayMandates.next_debit_date == target_date,
        db.or_(
            AutoPayMandates.predebit_notice_sent_for.is_(None),
            AutoPayMandates.predebit_notice_sent_for != target_date,
        ),
    ).all()

    sent = 0
    for mandate in due:
        try:
            obligation = mandate.obligation
            account_ref = (
                mandate.upi_vpa
                or (mandate.bank_account_id and '****')
                or 'your account'
            )

            audit.emit(
                'MandatePreDebitEvent',
                aggregate_type='AutoPayMandates',
                aggregate_id=mandate.mandate_id,
                user_id=str(mandate.user_id),
                payload={
                    'event': NotificationEvent.AUTOPAY_PREDEBIT,
                    'amount': float(obligation.emi_amount),
                    'account': account_ref,
                    'due_date': target_date.isoformat(),
                    'provider': obligation.provider_name,
                    'umn': mandate.mandate_umn,
                },
            )

            mandate.predebit_notice_sent_for = target_date
            db.session.commit()
            sent += 1

        except Exception as exc:
            db.session.rollback()
            current_app.logger.error(
                f'[mandate] pre-debit notice failed for {mandate.mandate_id}: {exc}'
            )

    return {'due': len(due), 'sent': sent}


def schedule_due_debits() -> dict:
    """
    Create attempt-1 rows for mandates due today.

    Scheduling rather than debiting immediately keeps the ladder restartable:
    the attempt rows record what was planned, so a crashed scheduler resumes
    without double-debiting or silently skipping a cycle.
    """
    today = utcnow().date()

    due = AutoPayMandates.query.filter(
        AutoPayMandates.status == MandateStatus.ACTIVE,
        AutoPayMandates.next_debit_date == today,
    ).all()

    scheduled = 0
    for mandate in due:
        existing = MandateDebitAttempts.query.filter_by(
            mandate_id=mandate.mandate_id, cycle_date=today, attempt_number=1
        ).first()
        if existing:
            continue

        _, day_offset, hour, minute = RETRY_LADDER[0]
        db.session.add(MandateDebitAttempts(
            mandate_id=mandate.mandate_id,
            emi_id=mandate.emi_id,
            cycle_date=today,
            attempt_number=1,
            scheduled_at=utcnow().replace(hour=hour, minute=minute, second=0, microsecond=0),
            amount=mandate.obligation.emi_amount,
            result=DebitAttemptResult.SCHEDULED,
        ))
        scheduled += 1

    db.session.commit()
    return {'due': len(due), 'scheduled': scheduled}


def execute_due_attempts(limit: int = 100) -> dict:
    """Run scheduled debit attempts whose time has come."""
    from portal.helpers import emi_engine
    from portal.models.emi_payments import PaymentMode

    due = MandateDebitAttempts.query.filter(
        MandateDebitAttempts.result == DebitAttemptResult.SCHEDULED,
        MandateDebitAttempts.scheduled_at <= utcnow(),
    ).limit(limit).all()

    succeeded, failed = 0, 0

    for attempt in due:
        mandate = attempt.mandate

        if not mandate or mandate.status != MandateStatus.ACTIVE:
            attempt.result = DebitAttemptResult.SKIPPED
            attempt.executed_at = utcnow()
            db.session.commit()
            continue

        try:
            payment = emi_engine.initiate_payment(
                user=mandate.user,
                obligation=mandate.obligation,
                amount=attempt.amount,
                payment_mode=(
                    PaymentMode.UPI_COLLECT
                    if mandate.mandate_type == MandateType.UPI_AUTOPAY
                    else PaymentMode.NETBANKING
                ),
                idempotency_key=(
                    f'mnd_{mandate.mandate_id[:8]}_{attempt.cycle_date}_'
                    f'{attempt.attempt_number}'
                ),
                is_auto_pay=True,
                mandate_id=mandate.mandate_id,
            )
            emi_engine.confirm_payment(payment)

            from portal.models.emi_payments import EMIPaymentState

            if payment.status in (EMIPaymentState.SETTLED, EMIPaymentState.SUCCESSFUL):
                attempt.result = DebitAttemptResult.SUCCESS
                attempt.payment_id = payment.payment_id
                mandate.last_debit_date = utcnow().date()
                mandate.consecutive_failures = 0
                mandate.next_debit_date = emi_provider_adapter.next_due_date(
                    mandate.obligation.due_day_of_month
                )
                succeeded += 1
            else:
                _fail_attempt(attempt, mandate, payment.failure_reason)
                failed += 1

            attempt.executed_at = utcnow()
            db.session.commit()

        except Exception as exc:
            db.session.rollback()
            current_app.logger.error(
                f'[mandate] debit attempt {attempt.attempt_id} failed: {exc}'
            )
            try:
                _fail_attempt(attempt, mandate, str(exc))
                attempt.executed_at = utcnow()
                db.session.commit()
                failed += 1
            except Exception:
                db.session.rollback()

    return {'executed': len(due), 'succeeded': succeeded, 'failed': failed}


def _fail_attempt(attempt: MandateDebitAttempts, mandate: AutoPayMandates, reason: str):
    """
    Record a bounced debit and schedule the next rung, or give up.

    After the third failure the mandate is disabled for the cycle and the user
    is prompted to pay manually - continuing to retry would only accumulate
    bounce charges against them.
    """
    attempt.result = DebitAttemptResult.INSUFFICIENT_FUNDS
    attempt.failure_reason = str(reason)[:500] if reason else None
    mandate.consecutive_failures = (mandate.consecutive_failures or 0) + 1

    next_rung = next(
        (r for r in RETRY_LADDER if r[0] == attempt.attempt_number + 1), None
    )

    if next_rung:
        number, day_offset, hour, minute = next_rung
        scheduled_at = utcnow().replace(
            hour=hour, minute=minute, second=0, microsecond=0
        ) + timedelta(days=day_offset - (attempt.attempt_number - 1))

        db.session.add(MandateDebitAttempts(
            mandate_id=mandate.mandate_id,
            emi_id=mandate.emi_id,
            cycle_date=attempt.cycle_date,
            attempt_number=number,
            scheduled_at=scheduled_at,
            amount=attempt.amount,
            result=DebitAttemptResult.SCHEDULED,
        ))

        audit.emit(
            'MandateDebitFailedEvent',
            aggregate_type='AutoPayMandates',
            aggregate_id=mandate.mandate_id,
            user_id=str(mandate.user_id),
            payload={
                'event': NotificationEvent.AUTOPAY_FAILED,
                'amount': float(attempt.amount),
                'provider': mandate.obligation.provider_name,
                'retry_date': scheduled_at.date().isoformat(),
            },
        )
    else:
        mandate.obligation.auto_pay_status = AutoPayStatus.FAILED
        mandate.obligation.payment_status = EMIPaymentStatus.OVERDUE
        mandate.next_debit_date = emi_provider_adapter.next_due_date(
            mandate.obligation.due_day_of_month
        )

        audit.emit(
            'MandateExhaustedEvent',
            aggregate_type='AutoPayMandates',
            aggregate_id=mandate.mandate_id,
            user_id=str(mandate.user_id),
            payload={
                'event': NotificationEvent.AUTOPAY_FAILED,
                'amount': float(attempt.amount),
                'provider': mandate.obligation.provider_name,
                'retry_date': 'manual payment required',
            },
        )
