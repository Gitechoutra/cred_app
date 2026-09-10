from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class DebitAttemptResult:
    SCHEDULED = "SCHEDULED"
    SUCCESS = "SUCCESS"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    MANDATE_REVOKED = "MANDATE_REVOKED"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    SKIPPED = "SKIPPED"

    CHOICES = [
        SCHEDULED, SUCCESS, INSUFFICIENT_FUNDS,
        MANDATE_REVOKED, TECHNICAL_FAILURE, SKIPPED,
    ]


class MandateDebitAttempts(db.Model, TimestampMixin, CRUDMixin):
    """
    One row per debit attempt in the PRD 12.3 retry ladder.

        Attempt 1  due date, 04:00 IST
        Attempt 2  due date + 1 day, 11:30 IST   (post-salary window)
        Attempt 3  due date + 2 days, 18:00 IST  (final)

    After the third failure the mandate is disabled for the cycle, the
    obligation is flagged OVERDUE, and the user is prompted to pay manually.

    Persisting each attempt rather than a counter on the mandate means the
    scheduler is restart-safe: it can always tell which attempts have already
    fired for a given cycle.
    """

    __tablename__ = 'mandate_debit_attempts'
    __table_args__ = (
        db.UniqueConstraint(
            'mandate_id', 'cycle_date', 'attempt_number', name='uq_mandate_cycle_attempt'
        ),
        db.Index('ix_attempt_scheduled', 'scheduled_at', 'result'),
    )

    attempt_id = uuid_pk()
    mandate_id = uuid_fk('auto_pay_mandates.mandate_id', nullable=False, index=True)
    emi_id = uuid_fk('emi_obligations.emi_id', nullable=False, index=True)

    cycle_date = db.Column(db.Date, nullable=False)     # the due date being served
    attempt_number = db.Column(db.Integer, nullable=False)   # 1, 2 or 3
    scheduled_at = db.Column(db.DateTime, nullable=False)
    executed_at = db.Column(db.DateTime, nullable=True)

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    result = db.Column(
        db.String(30), default=DebitAttemptResult.SCHEDULED, nullable=False
    )

    payment_id = db.Column(db.String(36), nullable=True)
    provider_reference = db.Column(db.String(150), nullable=True)
    bounce_code = db.Column(db.String(50), nullable=True)
    failure_reason = db.Column(db.String(500), nullable=True)

    mandate = db.relationship('AutoPayMandates', back_populates='debit_attempts')

    def __repr__(self):
        return f"<DebitAttempt {self.mandate_id} #{self.attempt_number} {self.result}>"
