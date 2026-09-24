from portal import db
from portal.models.base import TimestampMixin, AppendOnlyMixin, uuid_pk, uuid_fk


class TransactionType:
    EMI_MANUAL_PAY = "EMI_MANUAL_PAY"
    EMI_AUTO_PAY = "EMI_AUTO_PAY"
    FEE_DEBIT = "FEE_DEBIT"
    REVERSAL_REFUND = "REVERSAL_REFUND"
    PENNY_DROP = "PENNY_DROP"
    #: Scanned UPI payment to a merchant. A separate type because it is a
    #: separate product: the money leaves the user's bank, not their card, and
    #: the destination is a third party rather than their own account.
    QR_UPI_PAYMENT = "QR_UPI_PAYMENT"

    # -- Issued credit line --------------------------------------------------
    #: A spend drawn on a CashU credit line.
    CREDIT_PURCHASE = "CREDIT_PURCHASE"
    #: A payment made against a credit line statement.
    CREDIT_BILL_PAYMENT = "CREDIT_BILL_PAYMENT"
    #: A merchant refund reversing a purchase.
    CREDIT_REFUND = "CREDIT_REFUND"
    #: A late payment fee charged on an overdue statement.
    CREDIT_LATE_FEE = "CREDIT_LATE_FEE"

    #: Retired with the credit-to-bank transfer product. The ledger is
    #: append-only, so rows of this type still exist and must still validate.
    CARD_TO_BANK_TRANSFER = "CARD_TO_BANK_TRANSFER"

    CHOICES = [
        EMI_MANUAL_PAY, EMI_AUTO_PAY, FEE_DEBIT, REVERSAL_REFUND, PENNY_DROP,
        QR_UPI_PAYMENT,
        CREDIT_PURCHASE, CREDIT_BILL_PAYMENT, CREDIT_REFUND, CREDIT_LATE_FEE,
        CARD_TO_BANK_TRANSFER,
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
    #: An issued CashU credit line - the source of a purchase.
    CREDIT_LINE = "CREDIT_LINE"

    CHOICES = [
        CREDIT_CARD_TOKEN, BANK_ACCOUNT_MANDATE,
        UPI_VPA, NETBANKING, DEBIT_CARD, CREDIT_LINE,
    ]


class DestType:
    BANK_ACCOUNT_IMPS = "BANK_ACCOUNT_IMPS"
    BBPS_BILLER_COLLECTION = "BBPS_BILLER_COLLECTION"
    CARD_REFUND = "CARD_REFUND"
    #: A merchant's UPI address, from a scanned QR.
    MERCHANT_VPA = "MERCHANT_VPA"
    #: A merchant accepting a card purchase.
    MERCHANT = "MERCHANT"
    #: An issued CashU credit line - the destination of a bill payment.
    CREDIT_LINE = "CREDIT_LINE"

    CHOICES = [
        BANK_ACCOUNT_IMPS, BBPS_BILLER_COLLECTION, CARD_REFUND, MERCHANT_VPA,
        MERCHANT, CREDIT_LINE,
    ]


class GatewayProvider:
    CASHFREE = "CASHFREE"
    RAZORPAY = "RAZORPAY"
    SANDBOX = "SANDBOX"
    #: No external gateway was involved. A purchase on an issued credit line and
    #: a late fee are both movements between this platform's own accounts, and
    #: naming a gateway that took no part would make reconciliation against that
    #: gateway's settlement file look permanently short.
    INTERNAL = "INTERNAL"

    CHOICES = [CASHFREE, RAZORPAY, SANDBOX, INTERNAL]


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
