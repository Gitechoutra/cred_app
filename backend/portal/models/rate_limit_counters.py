"""
portal/models/rate_limit_counters.py
====================================
Sliding-window rate limiting, the MySQL stand-in for Redis.

Rehomed from transfer_limits, which went with the transfer product. This
counter is not about transfers at all - it backs the OTP, login and payment
throttles - so it outlived the module it happened to live in.
"""

from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk


class RateLimitCounters(db.Model, TimestampMixin, CRUDMixin):
    """
    Sliding-window rate limiting (PRD 17.1), the MySQL stand-in for Redis.

    Keyed by an opaque scope string - "auth:ip:1.2.3.4", "otp:phone:98...",
    "txn:user:<uuid>" - plus a time bucket. The janitor job sweeps old buckets.
    """

    __tablename__ = 'rate_limit_counters'
    __table_args__ = (
        db.UniqueConstraint('scope', 'bucket', name='uq_scope_bucket'),
        db.Index('ix_rate_bucket_start', 'bucket_start'),
    )

    counter_id = uuid_pk()

    scope = db.Column(db.String(200), nullable=False, index=True)
    bucket = db.Column(db.String(30), nullable=False)
    bucket_start = db.Column(db.DateTime, nullable=False)

    hits = db.Column(db.Integer, default=0, nullable=False)

    def __repr__(self):
        return f"<RateLimit {self.scope} {self.bucket} hits={self.hits}>"
