"""
portal/helpers/error_recorder.py
================================
Writes a failure down, once, without ever being the reason a request fails.

Every call site here sits on a path that has already gone wrong. If recording
the failure could itself raise, a declined card would turn into a 500 and the
user would lose the explanation as well as the payment - so `record` swallows
everything and logs instead. A diagnostic table is not worth an outage.

Deduplication is on (reference_id, error_code): a payment that is confirmed by
both the webhook and the browser fails twice and should still be one row, or
the admin view fills with the same event and "repeated failures" stops meaning
anything.
"""

from flask import current_app

from portal import db
from portal.helpers import error_catalog
from portal.models.transaction_errors import TransactionErrors


def record(
    *,
    user_id,
    code=None,
    reason=None,
    reference_type=None,
    reference_id=None,
    transaction_id=None,
    payment_method=None,
    gateway=None,
    amount=None,
    transaction_status=None,
    gateway_response=None,
):
    """
    Record one failure and return the row, or None if it could not be written.

    `reason` is the provider's own text. It is kept for support and is also
    what the classifier falls back to when the code is unmapped, which is how
    an unrecognised gateway error still produces a sensible explanation.
    """
    try:
        verdict = error_catalog.classify(code=code, reason=reason)

        if reference_id:
            existing = TransactionErrors.query.filter_by(
                reference_id=reference_id,
                error_code=verdict['code'],
            ).first()
            if existing:
                return existing

        row = TransactionErrors(
            user_id=str(user_id),
            transaction_id=transaction_id,
            reference_type=reference_type,
            reference_id=reference_id,
            error_code=verdict['code'],
            error_type=verdict['type'],
            error_message=verdict['message'][:300],
            # The provider's words, for an agent. Never shown to the user.
            error_reason=(str(reason)[:500] if reason else None),
            payment_method=payment_method,
            gateway=gateway,
            amount=amount,
            transaction_status=transaction_status,
            gateway_response=error_catalog.sanitize_gateway_payload(gateway_response),
            is_retryable=verdict['retryable'],
        )

        db.session.add(row)
        db.session.commit()
        return row

    except Exception as exc:
        # Never propagate. See the module docstring.
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.error(
            f'[error_recorder] could not record failure {code}: {exc}'
        )
        return None


def latest_for(reference_type: str, reference_id: str):
    """The most recent failure recorded against one payment."""
    return (
        TransactionErrors.query
        .filter_by(reference_type=reference_type, reference_id=reference_id)
        .order_by(TransactionErrors.created_on.desc())
        .first()
    )


def to_dict(row, detailed: bool = False) -> dict:
    """
    Serialise for the client.

    `gateway_response` and `error_reason` are withheld unless `detailed`, which
    only the admin routes pass. They are sanitised, but a raw acquirer payload
    is noise to a customer and an invitation to paste it into a support chat.
    """
    if not row:
        return None

    verdict = error_catalog.classify(code=row.error_code, reason=row.error_reason)

    data = {
        'error_id': row.error_id,
        'transaction_id': row.transaction_id,
        'reference_type': row.reference_type,
        'reference_id': row.reference_id,
        'error_code': row.error_code,
        'error_type': row.error_type,
        'error_message': row.error_message,
        'payment_method': row.payment_method,
        'amount': float(row.amount) if row.amount is not None else None,
        'transaction_status': row.transaction_status,
        'is_retryable': bool(row.is_retryable),
        'actions': verdict['actions'],
        'created_at': row.created_on.isoformat() if row.created_on else None,
        'is_resolved': bool(row.is_resolved),
    }

    if detailed:
        data['error_reason'] = row.error_reason
        data['gateway'] = row.gateway
        data['gateway_response'] = row.gateway_response
        data['resolved_at'] = row.resolved_at.isoformat() if row.resolved_at else None
        data['resolved_by'] = row.resolved_by
        data['resolution_notes'] = row.resolution_notes
        data['support_ticket_id'] = row.support_ticket_id

    return data
