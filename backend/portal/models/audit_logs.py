from portal import db
from portal.models.base import TimestampMixin, AppendOnlyMixin, uuid_pk


class AuditLogs(db.Model, TimestampMixin, AppendOnlyMixin):
    """
    Immutable record of every authentication event, financial state transition
    and administrative action (PRD 17.1).

    Append-only by construction. In production these rows are also streamed to
    WORM storage with checksum hashing; the application-level guarantee here is
    that nothing in CashU deletes or rewrites them.
    """

    __tablename__ = 'audit_logs'
    __table_args__ = (
        db.Index('ix_audit_actor_time', 'actor_user_id', 'created_on'),
        db.Index('ix_audit_entity', 'entity_type', 'entity_id'),
    )

    audit_id = uuid_pk()

    actor_user_id = db.Column(db.String(36), nullable=True, index=True)
    actor_role = db.Column(db.String(50), nullable=True)
    on_behalf_of_user_id = db.Column(db.String(36), nullable=True, index=True)

    action = db.Column(db.String(100), nullable=False, index=True)
    entity_type = db.Column(db.String(80), nullable=True)
    entity_id = db.Column(db.String(36), nullable=True)

    # JSON snapshots. PII is masked before it is written here.
    before_state = db.Column(db.Text, nullable=True)
    after_state = db.Column(db.Text, nullable=True)

    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    correlation_id = db.Column(db.String(64), nullable=True, index=True)

    notes = db.Column(db.String(1000), nullable=True)

    def __repr__(self):
        return f"<Audit {self.action} {self.entity_type}:{self.entity_id}>"


class AdminActivityLogs(db.Model, TimestampMixin, AppendOnlyMixin):
    """
    Administrative actions specifically, split out from the general audit trail
    so a compliance reviewer can read the console's history without wading
    through every user login.

    PRD 16.1 requires maker-checker on reversals above 25,000 INR - the checker
    columns record who approved what.
    """

    __tablename__ = 'admin_activity_logs'

    activity_id = uuid_pk()

    admin_user_id = db.Column(db.String(36), nullable=False, index=True)
    admin_role = db.Column(db.String(50), nullable=False)

    module = db.Column(db.String(80), nullable=False)      # USERS | TXN | RECON | ...
    action = db.Column(db.String(100), nullable=False)
    target_type = db.Column(db.String(80), nullable=True)
    target_id = db.Column(db.String(36), nullable=True, index=True)

    amount_involved = db.Column(db.Numeric(12, 2), nullable=True)

    requires_maker_checker = db.Column(db.Boolean, default=False)
    checker_user_id = db.Column(db.String(36), nullable=True)
    checker_approved_at = db.Column(db.DateTime, nullable=True)
    checker_rejected_reason = db.Column(db.String(500), nullable=True)

    ip_address = db.Column(db.String(45), nullable=True)
    justification = db.Column(db.String(1000), nullable=True)
    payload = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<AdminActivity {self.admin_user_id} {self.action}>"
