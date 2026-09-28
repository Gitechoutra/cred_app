from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk


class DiscrepancyType:
    LEDGER_MISSING = "LEDGER_MISSING"
    GATEWAY_MISSING = "GATEWAY_MISSING"
    PAYOUT_MISSING = "PAYOUT_MISSING"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    UNBALANCED_LEDGER = "UNBALANCED_LEDGER"

    CHOICES = [
        LEDGER_MISSING, GATEWAY_MISSING, PAYOUT_MISSING,
        AMOUNT_MISMATCH, STATUS_MISMATCH, UNBALANCED_LEDGER,
    ]


class DiscrepancyResolution:
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    WRITTEN_OFF = "WRITTEN_OFF"

    CHOICES = [OPEN, INVESTIGATING, RESOLVED, WRITTEN_OFF]


class ReconciliationDiscrepancies(db.Model, TimestampMixin, CRUDMixin):
    """
    A single unmatched item surfaced to the L2 recon console (PRD 16.1).

    UNBALANCED_LEDGER is the one that matters most: it means debits did not
    equal credits for a transaction, which should be impossible and indicates
    the ledger engine was bypassed. It is raised as a critical alert.
    """

    __tablename__ = 'reconciliation_discrepancies'

    discrepancy_id = uuid_pk()

    transaction_id = db.Column(db.String(36), nullable=True, index=True)
    discrepancy_type = db.Column(db.String(30), nullable=False, index=True)

    expected_amount = db.Column(db.Numeric(12, 2), nullable=True)
    actual_amount = db.Column(db.Numeric(12, 2), nullable=True)
    expected_status = db.Column(db.String(30), nullable=True)
    actual_status = db.Column(db.String(30), nullable=True)

    details = db.Column(db.Text, nullable=True)

    resolution = db.Column(db.String(20), default=DiscrepancyResolution.OPEN, index=True)
    resolved_by = db.Column(db.String(36), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolution_notes = db.Column(db.String(1000), nullable=True)

    def __repr__(self):
        return f"<Discrepancy {self.discrepancy_type} {self.resolution}>"
