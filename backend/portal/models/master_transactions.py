from portal import db
from portal.models.base import TimestampMixin, AppendOnlyMixin, uuid_pk, uuid_fk


class TransactionType:
    CARD_TO_BANK_TRANSFER = "CARD_TO_BANK_TRANSFER"
    EMI_MANUAL_PAY = "EMI_MANUAL_PAY"
    EMI_AUTO_PAY = "EMI_AUTO_PAY"
    FEE_DEBIT = "FEE_DEBIT"
    REVERSAL_REFUND = "REVERSAL_REFUND"
    PENNY_DROP = "PENNY_DROP"

    CHOICES = [
        CARD_TO_BANK_TRANSFER, EMI_MANUAL_PAY, EMI_AUTO_PAY,
        FEE_DEBIT, REVERSAL_REFUND, PENNY_DROP,
    ]


class TransactionStatus:
    INITIATED = "INITIATED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"

    CHOICES = [INITIATED, PROCESSING, SUCCEEDED, FAILED, PENDING, REVERSED]
    TERMINAL = [SUCCEEDED, FAILED, REVERSED]


class SourceType:
    CREDIT_CARD_TOKEN = "CREDIT_CARD_TOKEN"
    BANK_ACCOUNT_MANDATE = "BANK_ACCOUNT_MANDATE"
    UPI_VPA = "UPI_VPA"
    NETBANKING = "NETBANKING"
    DEBIT_CARD = "DEBIT_CARD"

    CHOICES = [
        CREDIT_CARD_TOKEN, BANK_ACCOUNT_MANDATE,
        UPI_VPA, NETBANKING, DEBIT_CARD,
    ]


class DestType:
    BANK_ACCOUNT_IMPS = "BANK_ACCOUNT_IMPS"
    BBPS_BILLER_COLLECTION = "BBPS_BILLER_COLLECTION"
    CARD_REFUND = "CARD_REFUND"

    CHOICES = [BANK_ACCOUNT_IMPS, BBPS_BILLER_COLLECTION, CARD_REFUND]


class GatewayProvider:
    CASHFREE = "CASHFREE"
    SANDBOX = "SANDBOX"

    CHOICES = [CASHFREE, SANDBOX]


class ReconStatus:
    UNRECONCILED = "UNRECONCILED"
    MATCHED = "MATCHED"
    DISCREPANCY_FLAGGED = "DISCREPANCY_FLAGGED"

    CHOICES = [UNRECONCILED, MATCHED, DISCREPANCY_FLAGGED]


class MasterTransactions(db.Model, TimestampMixin, AppendOnlyMixin):
    """
    Every monetary movement on the platform (PRD section 13.1, verbatim).

    Append-only: this row is never deleted, and a correction is a compensating
    entry, not an edit (PRD FR-010). Status transitions are the one permitted
    mutation, and only through ledger_engine.

    idempotency_key is UNIQUE. That constraint is the duplicate-charge defence
    (ERR-007, AC-004): a second submission with the same key raises
    IntegrityError at INSERT, which the route catches and answers with the
    original transaction rather than charging the card twice. The PRD puts this
    in Redis with a 24h TTL; a database constraint is strictly stronger because
    it cannot be lost to an eviction or a restart.
    """

    __tablename__ = 'master_transactions'
    __table_args__ = (
        db.Index('ix_txn_user_created', 'user_id', 'created_on'),
        db.Index('ix_txn_status_recon', 'status', 'recon_status'),
    )

    transaction_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    transaction_type = db.Column(db.String(40), nullable=False, index=True)

    gross_amount = db.Column(db.Numeric(12, 2), nullable=False)
    net_amount = db.Column(db.Numeric(12, 2), nullable=False)
    fee_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    tax_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    currency = db.Column(db.String(3), default='INR', nullable=False)

    source_type = db.Column(db.String(40), nullable=False)
    source_masked_ref = db.Column(db.String(150), nullable=False)
    dest_type = db.Column(db.String(40), nullable=False)
    dest_masked_ref = db.Column(db.String(150), nullable=False)

    gateway_provider = db.Column(db.String(30), nullable=False)
    gateway_ref_no = db.Column(db.String(150), nullable=True, index=True)
    bank_rrn_utr = db.Column(db.String(50), nullable=True, index=True)

    idempotency_key = db.Column(db.String(64), unique=True, nullable=False, index=True)

    status = db.Column(
        db.String(20), default=TransactionStatus.INITIATED, nullable=False, index=True
    )
    failure_code = db.Column(db.String(50), nullable=True)
    failure_reason = db.Column(db.String(500), nullable=True)

    recon_status = db.Column(
        db.String(30), default=ReconStatus.UNRECONCILED, nullable=False
    )
    reconciled_at = db.Column(db.DateTime, nullable=True)

    # Set on the compensating transaction, pointing back at what it reverses.
    reverses_transaction_id = db.Column(db.String(36), nullable=True, index=True)

    user = db.relationship('Users', back_populates='transactions')
    ledger_entries = db.relationship(
        'DoubleEntryLedger', back_populates='transaction', lazy='dynamic'
    )

    def __repr__(self):
        return f"<Txn {self.transaction_id} {self.transaction_type} {self.status}>"
