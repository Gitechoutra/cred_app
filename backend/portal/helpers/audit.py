"""
portal/helpers/audit.py
=======================
Immutable audit writes (PRD 17.1) and the domain-event outbox (NFR-004).

Two rules hold this together:

1. An audit row is never written with raw PII. Everything is masked at the
   boundary, so a leaked audit log cannot become a leaked identity database.
2. A domain event is written in the *same* database transaction as the state
   change that produced it, and is not committed here. That is what makes the
   outbox reliable: either the transfer and its notification both commit, or
   neither does.
"""

import json
from datetime import datetime, timedelta

from flask import has_request_context

from portal import db
from portal.helpers.helpers import client_ip, correlation_id, user_agent
from portal.logger import audit_logger
from portal.models.audit_logs import AdminActivityLogs, AuditLogs
from portal.models.base import utcnow
from portal.models.domain_events import DomainEvents

#: Never persisted to an audit row, at any nesting depth.
_REDACT_KEYS = {
    'password', 'mpin', 'otp', 'otp_hash', 'cvv', 'card_number', 'pan',
    'pan_number', 'aadhaar', 'aadhaar_number', 'account_number',
    'loan_account_no', 'refresh_token', 'access_token', 'signature',
    'secret', 'api_key', 'mpin_hash', 'token_reference_id',
}


def _scrub(value, depth: int = 0):
    """Recursively mask sensitive keys before anything is serialized."""
    if depth > 6:
        return '<max-depth>'

    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k).lower() in _REDACT_KEYS:
                out[k] = '<redacted>'
            else:
                out[k] = _scrub(v, depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        return [_scrub(v, depth + 1) for v in value[:50]]

    if isinstance(value, datetime):
        return value.isoformat()

    return value


def _dump(value) -> str:
    if value is None:
        return None
    try:
        return json.dumps(_scrub(value), default=str)[:8000]
    except Exception:
        return json.dumps({'unserializable': str(type(value))})


def record(
    action: str,
    entity_type: str = None,
    entity_id: str = None,
    actor_user_id: str = None,
    actor_role: str = None,
    before: dict = None,
    after: dict = None,
    notes: str = None,
    on_behalf_of: str = None,
    commit: bool = True,
):
    """
    Write an audit row.

    Audit failure must never break the action being audited - a user should not
    see their transfer fail because the log sink hiccuped. The exception is
    swallowed and mirrored to the file logger so the event is not lost.
    """
    try:
        entry = AuditLogs(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            on_behalf_of_user_id=on_behalf_of,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            before_state=_dump(before),
            after_state=_dump(after),
            notes=notes[:1000] if notes else None,
        )

        if has_request_context():
            entry.ip_address = client_ip()
            entry.user_agent = user_agent()
            entry.correlation_id = correlation_id()

        db.session.add(entry)
        if commit:
            db.session.commit()

        audit_logger().info(
            f"{action} entity={entity_type}:{entity_id} actor={actor_user_id}"
        )
        return entry

    except Exception as exc:
        db.session.rollback()
        audit_logger().error(f"AUDIT WRITE FAILED action={action}: {exc}")
        return None


def record_admin(
    admin_user_id: str,
    admin_role: str,
    module: str,
    action: str,
    target_type: str = None,
    target_id: str = None,
    amount: float = None,
    justification: str = None,
    payload: dict = None,
    commit: bool = True,
):
    """
    Log an administrative action.

    PRD 16.1 requires maker-checker on reversals above 25,000 INR. The flag is
    set here from the amount so the approval requirement is derived from the
    money involved rather than remembered at each call site.
    """
    try:
        activity = AdminActivityLogs(
            admin_user_id=admin_user_id,
            admin_role=admin_role,
            module=module,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id else None,
            amount_involved=amount,
            requires_maker_checker=bool(amount and float(amount) > 25000),
            justification=justification[:1000] if justification else None,
            payload=_dump(payload),
        )
        if has_request_context():
            activity.ip_address = client_ip()

        db.session.add(activity)
        if commit:
            db.session.commit()

        audit_logger().info(
            f"ADMIN {module}.{action} by={admin_user_id} target={target_type}:{target_id}"
        )
        return activity

    except Exception as exc:
        db.session.rollback()
        audit_logger().error(f"ADMIN AUDIT FAILED {module}.{action}: {exc}")
        return None


def emit(
    event_type: str,
    aggregate_type: str = None,
    aggregate_id: str = None,
    user_id: str = None,
    payload: dict = None,
):
    """
    Queue a domain event on the outbox.

    Deliberately does NOT commit. The caller commits it together with the state
    change, which is the entire point of the outbox pattern - a notification
    for a rolled-back transfer is worse than no notification at all.
    """
    event = DomainEvents(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id) if aggregate_id else None,
        user_id=str(user_id) if user_id else None,
        payload=_dump(payload or {}),
        next_attempt_at=utcnow(),
    )

    if has_request_context():
        event.correlation_id = correlation_id()

    db.session.add(event)
    return event


def schedule_retry(event: DomainEvents, error: str):
    """Exponential backoff, then the dead-letter queue for a human to look at."""
    event.attempts += 1
    event.last_error = str(error)[:1000]

    if event.attempts >= event.max_attempts:
        from portal.models.domain_events import EventStatus
        event.status = EventStatus.DEAD_LETTER
        audit_logger().error(
            f"EVENT DEAD-LETTERED {event.event_type} id={event.event_id}: {error}"
        )
    else:
        from portal.models.domain_events import EventStatus
        event.status = EventStatus.PENDING
        event.next_attempt_at = utcnow() + timedelta(minutes=2 ** event.attempts)
