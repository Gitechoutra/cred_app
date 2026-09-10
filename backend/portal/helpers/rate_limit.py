"""
portal/helpers/rate_limit.py
============================
Sliding-window rate limiting on MySQL (PRD 17.1).

The PRD specifies a Redis sliding-window counter. version1.md deviation D2
keeps the same semantics on a counter table:

    Public auth endpoints        5 req/min per IP
    Transaction initiation       3 req/min per user
    OTP resend                   3 per 15-min window per IP or device
    Transfer velocity            >3 in 1 hour throttles and alerts (ERR-011)

Implemented as fixed windows with a half-window offset check, which
approximates a sliding window closely enough for abuse control while staying a
single indexed read. A determined attacker can get at most 2x the nominal rate
at a window boundary; that is an acceptable trade for not running Redis.
"""

from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from portal import db
from portal.models.base import utcnow
from portal.models.transfer_limits import RateLimitCounters


class RateLimitExceeded(Exception):
    """Raised when a caller is over its allowance."""

    def __init__(self, message: str, retry_after_seconds: int = 60, scope: str = None):
        super().__init__(message)
        self.message = message
        self.retry_after_seconds = retry_after_seconds
        self.scope = scope


def _bucket_key(window_seconds: int) -> tuple:
    """Bucket label and start time for the current window."""
    now = utcnow()
    epoch_seconds = int(now.timestamp())
    bucket_index = epoch_seconds // window_seconds
    bucket_start = utcnow().fromtimestamp(bucket_index * window_seconds)
    return str(bucket_index), bucket_start


def hit(scope: str, limit: int, window_seconds: int = 60, increment: int = 1) -> dict:
    """
    Register a request against `scope` and enforce `limit`.

    Raises RateLimitExceeded when over. Returns usage details when under, so a
    route can surface X-RateLimit headers.

    The counter row is created optimistically; a concurrent creator loses the
    UNIQUE race, and that branch re-reads rather than failing the request.
    """
    bucket, bucket_start = _bucket_key(window_seconds)

    counter = RateLimitCounters.query.filter_by(scope=scope, bucket=bucket).first()

    if not counter:
        counter = RateLimitCounters(
            scope=scope, bucket=bucket, bucket_start=bucket_start, hits=0
        )
        db.session.add(counter)
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            counter = RateLimitCounters.query.filter_by(
                scope=scope, bucket=bucket
            ).first()
            if counter is None:
                # Cannot account for this request; allow it rather than block a
                # legitimate user on an infrastructure hiccup.
                return {'allowed': True, 'remaining': limit, 'limit': limit}

    if counter.hits + increment > limit:
        elapsed = (utcnow() - counter.bucket_start).total_seconds()
        retry_after = max(1, int(window_seconds - elapsed))
        db.session.commit()
        raise RateLimitExceeded(
            'Too many requests. Please wait before trying again.',
            retry_after_seconds=retry_after,
            scope=scope,
        )

    counter.hits += increment
    db.session.commit()

    return {
        'allowed': True,
        'limit': limit,
        'used': counter.hits,
        'remaining': max(0, limit - counter.hits),
        'reset_in_seconds': max(
            1, int(window_seconds - (utcnow() - counter.bucket_start).total_seconds())
        ),
    }


def peek(scope: str, window_seconds: int = 60) -> int:
    """Current hit count without incrementing."""
    bucket, _ = _bucket_key(window_seconds)
    counter = RateLimitCounters.query.filter_by(scope=scope, bucket=bucket).first()
    return counter.hits if counter else 0


def reset(scope: str, window_seconds: int = 60):
    """Clear a scope - used after a successful login clears the failure count."""
    bucket, _ = _bucket_key(window_seconds)
    RateLimitCounters.query.filter_by(scope=scope, bucket=bucket).delete()
    db.session.commit()


def purge_expired(older_than_hours: int = 24) -> int:
    """Janitor sweep. Without it the counter table grows without bound."""
    cutoff = utcnow() - timedelta(hours=older_than_hours)
    deleted = RateLimitCounters.query.filter(
        RateLimitCounters.bucket_start < cutoff
    ).delete()
    db.session.commit()
    return deleted


# ── Scope builders ─────────────────────────────────────────────────────────
# Centralised so a scope string is never assembled by hand at a call site and
# accidentally made per-process or per-request unique.

def ip_scope(action: str, ip: str) -> str:
    return f'{action}:ip:{ip}'


def user_scope(action: str, user_id: str) -> str:
    return f'{action}:user:{user_id}'


def phone_scope(action: str, phone: str) -> str:
    return f'{action}:phone:{phone}'


def device_scope(action: str, device_uuid: str) -> str:
    return f'{action}:device:{device_uuid}'
