from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk


class PlatformStatistics(db.Model, TimestampMixin, CRUDMixin):
    """
    Daily rollup powering the admin dashboard and the PRD 3.2 KPI table.

    Precomputed rather than aggregated on read: the console should not run a
    full table scan over master_transactions every time someone opens it.
    """

    __tablename__ = 'platform_statistics'
    __table_args__ = (
        db.UniqueConstraint('stat_date', name='uq_stat_date'),
    )

    stat_id = uuid_pk()
    stat_date = db.Column(db.Date, nullable=False, index=True)

    # Acquisition
    total_users = db.Column(db.Integer, default=0)
    new_users = db.Column(db.Integer, default=0)
    kyc_verified_users = db.Column(db.Integer, default=0)
    daily_active_users = db.Column(db.Integer, default=0)

    # Engagement
    total_cards_linked = db.Column(db.Integer, default=0)
    total_emi_obligations = db.Column(db.Integer, default=0)
    active_mandates = db.Column(db.Integer, default=0)

    # Volume
    transfer_count = db.Column(db.Integer, default=0)
    transfer_volume = db.Column(db.Numeric(16, 2), default=0)
    emi_payment_count = db.Column(db.Integer, default=0)
    emi_payment_volume = db.Column(db.Numeric(16, 2), default=0)

    # Revenue
    fee_revenue = db.Column(db.Numeric(14, 2), default=0)
    gst_collected = db.Column(db.Numeric(14, 2), default=0)

    # Reliability (PRD 3.2 targets: >98.2% e-mandate, >97.5% card transfers)
    transfer_success_rate = db.Column(db.Numeric(5, 2), default=0)
    emi_success_rate = db.Column(db.Numeric(5, 2), default=0)
    failed_transfer_count = db.Column(db.Integer, default=0)
    reversal_count = db.Column(db.Integer, default=0)
    open_discrepancy_count = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f"<PlatformStats {self.stat_date}>"
