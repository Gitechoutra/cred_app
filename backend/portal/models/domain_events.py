from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk


class EventStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"

    CHOICES = [PENDING, PROCESSING, PROCESSED, FAILED, DEAD_LETTER]


class DomainEvents(db.Model, TimestampMixin, CRUDMixin):
    """
    Transactional outbox (PRD NFR-004 calls for Kafka with an outbox pattern to
    avoid dual-write inconsistency).

    The event row is written inside the same database transaction as the state
    change that produced it. Either both commit or neither does, so a transfer
    can never succeed without its notification being queued, and a notification
    can never fire for a transfer that rolled back. A scheduler job drains the
    table.
    """

    __tablename__ = 'domain_events'
    __table_args__ = (
        db.Index('ix_event_status_created', 'status', 'created_on'),
    )

    event_id = uuid_pk()

    event_type = db.Column(db.String(80), nullable=False, index=True)
    aggregate_type = db.Column(db.String(80), nullable=True)
    aggregate_id = db.Column(db.String(36), nullable=True, index=True)
    user_id = db.Column(db.String(36), nullable=True, index=True)

    payload = db.Column(db.Text, nullable=True)     # JSON

    status = db.Column(db.String(20), default=EventStatus.PENDING, nullable=False)
    attempts = db.Column(db.Integer, default=0)
    max_attempts = db.Column(db.Integer, default=5)
    next_attempt_at = db.Column(db.DateTime, nullable=True, index=True)

    processed_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.String(1000), nullable=True)

    correlation_id = db.Column(db.String(64), nullable=True, index=True)

    def __repr__(self):
        return f"<DomainEvent {self.event_type} {self.status}>"
