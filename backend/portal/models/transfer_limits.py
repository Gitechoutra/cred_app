from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class TransferLimitCounters(db.Model, TimestampMixin, CRUDMixin):
    """
    Rolling spend counters for the PRD section 9.2 caps.

    One row per user per window bucket. Counting rows in `transfers` on every
    request would work but degrades as history grows; a counter row keyed by
    bucket makes the limit check a single indexed read.

    Buckets: DAILY uses YYYY-MM-DD, MONTHLY uses YYYY-MM.
    """

    __tablename__ = 'transfer_limit_counters'
    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'window_type', 'window_key', name='uq_user_window'
        ),
    )

    counter_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    window_type = db.Column(db.String(10), nullable=False)   # DAILY | MONTHLY
    window_key = db.Column(db.String(10), nullable=False)

    total_amount = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    transfer_count = db.Column(db.Integer, default=0, nullable=False)

    def __repr__(self):
        return f"<LimitCounter {self.user_id} {self.window_type} {self.window_key}>"


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
