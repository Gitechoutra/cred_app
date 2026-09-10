from portal import db
from portal.models.base import TimestampMixin, AppendOnlyMixin, uuid_pk, uuid_fk, utcnow


class DoubleEntryLedger(db.Model, TimestampMixin, AppendOnlyMixin):
    """
    The immutable journal (PRD FR-010, section 23).

    Every monetary movement produces at least two rows that sum to zero: one
    debit, one credit. Nothing here is ever updated or deleted - a mistake is
    corrected by posting the opposite entry, so the history stays a complete
    record of what was believed at each point in time.

    Only ledger_engine.post() writes to this table.
    """

    __tablename__ = 'double_entry_ledger'
    __table_args__ = (
        db.Index('ix_ledger_txn', 'transaction_id'),
        db.Index('ix_ledger_account_time', 'account_code', 'entry_timestamp'),
    )

    entry_id = uuid_pk()
    transaction_id = uuid_fk(
        'master_transactions.transaction_id', nullable=False, index=True
    )

    account_code = db.Column(db.String(50), nullable=False, index=True)
    # Exactly one of these is non-zero on any given row.
    debit_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    credit_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    currency = db.Column(db.String(3), default='INR', nullable=False)

    narration = db.Column(db.String(500), nullable=True)
    entry_timestamp = db.Column(db.DateTime, default=utcnow, nullable=False)

    transaction = db.relationship('MasterTransactions', back_populates='ledger_entries')

    def __repr__(self):
        side = f"Dr {self.debit_amount}" if self.debit_amount else f"Cr {self.credit_amount}"
        return f"<Ledger {self.account_code} {side}>"
