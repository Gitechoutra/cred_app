"""
portal/helpers/helpers.py
=========================
Response envelopes, error codes and small shared utilities.

Every route answers in the same shape so the React client has exactly one
parsing path for success and one for failure.
"""

import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from flask import request


# ── Error codes ────────────────────────────────────────────────────────────
# Machine-readable codes the client switches on. The ERR-0xx values map
# directly onto the PRD section 20 error matrix so a support agent reading a
# log line can find the row in the spec.

class ErrorCode:
    # Auth
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    OTP_EXPIRED = "OTP_EXPIRED"
    OTP_INVALID = "OTP_INVALID"
    OTP_MAX_RETRY = "OTP_MAX_RETRY"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    DEVICE_MISMATCH = "DEVICE_MISMATCH"
    MPIN_INVALID = "MPIN_INVALID"

    # Validation
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"

    # PRD section 20 matrix
    ERR_001_INVALID_CARD = "ERR-001"
    ERR_002_3DS_FAILED = "ERR-002"
    ERR_003_INSUFFICIENT_LIMIT = "ERR-003"
    ERR_004_NAME_MISMATCH = "ERR-004"
    ERR_005_GATEWAY_TIMEOUT = "ERR-005"
    ERR_006_PAYOUT_FAILED = "ERR-006"
    ERR_007_DUPLICATE = "ERR-007"
    ERR_008_MANDATE_BOUNCED = "ERR-008"
    ERR_009_TOKEN_EXPIRED = "ERR-009"
    ERR_010_BILLER_OFFLINE = "ERR-010"
    ERR_011_VELOCITY_ABUSE = "ERR-011"

    # Compliance gates
    KYC_REQUIRED = "KYC_REQUIRED"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    ACCOUNT_NOT_VERIFIED = "ACCOUNT_NOT_VERIFIED"
    INSTRUMENT_NOT_PERMITTED = "INSTRUMENT_NOT_PERMITTED"
    FEATURE_DISABLED = "FEATURE_DISABLED"

    # Server
    INTERNAL_ERROR = "INTERNAL_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class JSONEncoderMixin(json.JSONEncoder):
    """Decimal and datetime handling for payloads assembled by hand."""

    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, uuid.UUID):
            return str(o)
        return super().default(o)


def success(data=None, message: str = "Success", status: int = 200, **extra):
    body = {"success": True, "message": message, "data": data}
    body.update(extra)
    return body, status


def failure(
    code: str,
    message: str,
    status: int = 400,
    details=None,
    recovery: str = None,
):
    """
    Error envelope.

    `message` is the user-facing string - the PRD section 20 matrix specifies
    the exact wording for each error, and those strings go here rather than
    being invented in the frontend. `recovery` is the suggested next action
    from the same table.
    """
    body = {
        "success": False,
        "error": {"code": code, "message": message},
    }
    if details is not None:
        body["error"]["details"] = details
    if recovery:
        body["error"]["recovery"] = recovery
    return body, status


def paginated(items, page: int, per_page: int, total: int, **extra):
    body = {
        "success": True,
        "data": items,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page if per_page else 0,
            "has_next": page * per_page < total,
            "has_prev": page > 1,
        },
    }
    body.update(extra)
    return body, 200


# ── Request context ────────────────────────────────────────────────────────

def client_ip() -> str:
    """
    Caller IP, honouring the proxy chain.

    X-Forwarded-For is client-controlled and trivially spoofed, so this is fine
    for logging and coarse rate limiting but must never be the only thing
    gating a money movement.
    """
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def user_agent() -> str:
    return (request.headers.get('User-Agent') or '')[:500]


def device_uuid() -> str:
    return request.headers.get('X-Device-UUID', '')


def idempotency_key() -> str:
    return request.headers.get('X-Idempotency-Key', '')


def correlation_id() -> str:
    """
    Per-request trace id (PRD NFR-006 X-Correlation-ID), generated when the
    caller does not supply one so every log line for a request can be joined.
    """
    return request.headers.get('X-Correlation-ID') or str(uuid.uuid4())


# ── Formatting ─────────────────────────────────────────────────────────────

def to_float(value):
    return float(value) if value is not None else None


def money_str(value) -> str:
    """Indian-format currency for notification copy: 1,42,850.00 not 142,850.00."""
    if value is None:
        return "0.00"
    amount = f"{float(value):.2f}"
    whole, _, frac = amount.partition('.')
    negative = whole.startswith('-')
    whole = whole.lstrip('-')

    if len(whole) > 3:
        last3 = whole[-3:]
        rest = whole[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        whole = ','.join(groups + [last3])

    return f"{'-' if negative else ''}{whole}.{frac}"


def iso(value):
    """
    ISO 8601, with the zone stated for a timestamp.

    Timestamps are stored as naive UTC (see models.base.utcnow). Serialised
    without an offset, a browser parses them as *local* time, so every time of
    day showed five and a half hours early in India. A date carries no time and
    is passed through untouched.
    """
    if not value:
        return None
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.isoformat() + 'Z'
    return value.isoformat()
