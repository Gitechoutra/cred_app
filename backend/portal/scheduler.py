"""
portal/scheduler.py
===================
APScheduler registrations (version1.md 7.3).

Two of these jobs are the only reason a stuck payment ever un-sticks, so a
word on why they exist rather than just what they do:

- **payment_status_poll** catches the collections no callback ever resolved. A
  webhook can be lost, and a card charged against a payment this platform still
  reads as pending is real money in limbo, so every in-flight payment is
  re-read against the gateway on a cycle regardless of what did or did not
  arrive.

- **ledger_self_audit** is the D1 mitigation. MySQL gives weaker isolation
  guarantees than the PRD's PostgreSQL, so correctness rests on application
  discipline; this job is what proves that discipline held overnight.

Every job body runs inside an app context and swallows its own exceptions. An
unhandled error inside an APScheduler job kills that job's future runs, and a
silently dead retry ladder is far more dangerous than a logged failure.
"""

import json
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger('cashu')

#: All cron jobs are expressed in IST. The platform is domestic-only (PRD open
#: question 6 is closed: domestic INR), and the regulatory pre-debit notice is
#: specified in local time, so scheduling in UTC would drift it by 5.5 hours.
TIMEZONE = 'Asia/Kolkata'

scheduler = BackgroundScheduler(timezone=TIMEZONE)


def _job(app, name, fn, *args, **kwargs):
    """
    Run one job inside an app context, logging rather than propagating.

    APScheduler removes a job whose function raises repeatedly, so letting an
    exception escape would quietly disable the retry ladder - the failure mode
    this whole module exists to prevent.
    """
    def runner():
        with app.app_context():
            try:
                result = fn(*args, **kwargs)
                if result:
                    logger.info(f'[scheduler] {name}: {result}')
                else:
                    logger.debug(f'[scheduler] {name}: nothing to do')
            except Exception as exc:
                from portal import db
                db.session.rollback()
                logger.exception(f'[scheduler] {name} FAILED: {exc}')

    runner.__name__ = name
    return runner


# -- Money: the collection rails -------------------------------------------

def _poll_pending_payments():
    from portal.helpers import emi_engine
    return emi_engine.poll_pending_payments()


# -- Credit line billing ---------------------------------------------------

def _cut_credit_statements():
    """
    Cut a statement for every account whose cycle ends today.

    Idempotent through the UNIQUE (credit_account_id, period_end) constraint, so
    a retry after a partial failure finishes the job rather than double-billing
    the accounts it already reached. Each account is cut in its own try block for
    the same reason: one account whose data is somehow bad must not stop every
    other cardholder's statement from being issued.
    """
    from datetime import date

    from portal import db
    from portal.helpers import credit_engine
    from portal.models.credit_accounts import CreditAccounts, CreditAccountStatus

    today = date.today()
    accounts = CreditAccounts.query.filter(
        CreditAccounts.status.in_([
            CreditAccountStatus.ACTIVE, CreditAccountStatus.BLOCKED,
        ]),
        CreditAccounts.statement_day == today.day,
    ).all()

    issued = 0
    for account in accounts:
        try:
            credit_engine.cut_statement(account, as_of=today)
            issued += 1
        except Exception as exc:
            db.session.rollback()
            logger.error(
                f'[scheduler] statement failed for '
                f'{account.credit_account_id}: {exc}'
            )

    # A blocked account is still billed. The balance is owed whether or not the
    # card can spend, and skipping it would quietly forgive it.
    return {'accounts': len(accounts), 'statements_issued': issued} if accounts         else None


def _credit_overdue_and_fees():
    from portal.helpers import credit_engine
    return credit_engine.mark_overdue_and_charge_fees()


# -- Ledger integrity ------------------------------------------------------

def _ledger_self_audit():
    from portal.helpers import ledger_engine

    report = ledger_engine.self_audit()

    # Drift means a money path wrote outside ledger_engine.post(), or a
    # transaction committed half-posted. Neither is survivable quietly.
    if report and not report.get('healthy'):
        logger.critical(
            f'[scheduler] LEDGER DRIFT DETECTED: '
            f'{report.get("unbalanced_count", 0)} unbalanced and '
            f'{report.get("orphan_count", 0)} orphaned transaction(s). '
            f'Investigate immediately.'
        )
    return report


# -- Outbox drain (D4) -----------------------------------------------------

def _drain_domain_events(limit: int = 100):
    """
    Push queued domain events out as notifications.

    The outbox stands in for Kafka: audit.emit() writes the event in the same
    transaction as the state change, and this job is the consumer. At-least-once
    delivery, so a notification may repeat after a crash - which is the right
    trade against silently losing a payment-succeeded message.
    """
    from portal import db
    from portal.helpers import audit, notify
    from portal.models.base import utcnow
    from portal.models.domain_events import DomainEvents, EventStatus
    from portal.models.users import Users

    due = DomainEvents.query.filter(
        DomainEvents.status.in_([EventStatus.PENDING, EventStatus.FAILED]),
        DomainEvents.next_attempt_at <= utcnow(),
    ).order_by(DomainEvents.created_on.asc()).limit(limit).all()

    if not due:
        return None

    sent, failed = 0, 0

    for event in due:
        try:
            payload = json.loads(event.payload) if event.payload else {}
            notification_event = payload.get('event')

            if not notification_event or not event.user_id:
                # Not every domain event is user-facing; mark it done rather
                # than retrying something that will never dispatch.
                event.status = EventStatus.PROCESSED
                event.processed_at = utcnow()
                continue

            user = Users.query.get(event.user_id)
            if not user:
                event.status = EventStatus.PROCESSED
                event.processed_at = utcnow()
                continue

            notify.dispatch(user, notification_event, payload, commit=False)

            event.status = EventStatus.PROCESSED
            event.processed_at = utcnow()
            sent += 1

        except Exception as exc:
            failed += 1
            audit.schedule_retry(event, str(exc))

    db.session.commit()
    return {'sent': sent, 'failed': failed}


# -- Mandates (PRD 12) -----------------------------------------------------

def _mandate_predebit_notices():
    from portal.helpers import mandate_engine
    return mandate_engine.send_predebit_notices()


def _mandate_execute():
    from portal.helpers import mandate_engine
    scheduled = mandate_engine.schedule_due_debits()
    executed = mandate_engine.execute_due_attempts()
    return {'scheduled': scheduled, 'executed': executed}


def _mandate_retry():
    from portal.helpers import mandate_engine
    return mandate_engine.execute_due_attempts()


# -- Housekeeping ----------------------------------------------------------

def _emi_overdue_sweep():
    from portal.helpers import emi_engine
    return {'flagged_overdue': emi_engine.refresh_overdue_flags()}


def _janitor():
    from portal.helpers import otp, rate_limit
    return {
        'otp_rows_purged': otp.purge_expired(),
        'rate_limit_rows_purged': rate_limit.purge_expired(),
    }


# -- Registration ----------------------------------------------------------

def init_scheduler(app):
    """
    Register every job and start the scheduler.

    Called from InitApp only in the reloader's child process, so the dev server
    does not run each job twice.
    """
    if scheduler.running:
        logger.warning('[scheduler] already running; skipping registration.')
        return scheduler

    jobs = [
        # -- Money: must run, and run often ------------------------------
        ('payment_status_poll', _poll_pending_payments,
         IntervalTrigger(minutes=15)),

        # -- Outbox ------------------------------------------------------
        ('domain_event_drain', _drain_domain_events,
         IntervalTrigger(minutes=1)),

        # -- Credit line billing (IST) -----------------------------------
        # Just after midnight, so a statement dated today includes everything
        # that happened yesterday and nothing that happens today.
        ('credit_statement_cut', _cut_credit_statements,
         CronTrigger(hour=0, minute=20, timezone=TIMEZONE)),
        # After the cut, so a statement issued this morning is not immediately
        # examined for being overdue.
        ('credit_overdue_sweep', _credit_overdue_and_fees,
         CronTrigger(hour=1, minute=0, timezone=TIMEZONE)),

        # -- Mandates (regulatory timing; IST) ---------------------------
        ('mandate_predebit_notice', _mandate_predebit_notices,
         CronTrigger(hour=10, minute=0, timezone=TIMEZONE)),
        ('mandate_execute', _mandate_execute,
         CronTrigger(hour=4, minute=0, timezone=TIMEZONE)),
        ('mandate_retry_midday', _mandate_retry,
         CronTrigger(hour=11, minute=30, timezone=TIMEZONE)),
        ('mandate_retry_evening', _mandate_retry,
         CronTrigger(hour=18, minute=0, timezone=TIMEZONE)),

        # -- Integrity & housekeeping ------------------------------------
        ('ledger_self_audit', _ledger_self_audit,
         CronTrigger(hour=2, minute=30, timezone=TIMEZONE)),
        ('emi_due_reminder', _emi_overdue_sweep,
         CronTrigger(hour=9, minute=0, timezone=TIMEZONE)),
        ('janitor', _janitor,
         IntervalTrigger(hours=1)),
    ]

    for name, fn, trigger in jobs:
        scheduler.add_job(
            func=_job(app, name, fn),
            trigger=trigger,
            id=name,
            name=name,
            replace_existing=True,
            # A job that missed its window because the process was down should
            # still run once on start-up rather than be skipped entirely.
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )

    scheduler.start()

    logger.info(
        f'[scheduler] started with {len(jobs)} jobs '
        f'({", ".join(name for name, _, _ in jobs)})'
    )

    import atexit

    def _shutdown():
        # Already stopped is the normal case when something else shut the
        # scheduler down first; raising here would noise up every clean exit.
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass

    atexit.register(_shutdown)

    return scheduler
