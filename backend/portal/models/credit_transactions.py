from sqlalchemy.dialects.mysql import DATETIME

from portal import db
from portal.models.base import (
    AppendOnlyMixin, uuid_pk, uuid_fk, utcnow,
)


class CreditTransactionType:
    #: A spend that draws down the line.
    PURCHASE = 'PURCHASE'
    #: A bill payment that restores it.
    PAYMENT = 'PAYMENT'
    #: A reversal of a purchase - a refund from the merchant.
    REFUND = 'REFUND'
    #: A charge added by the platform: a late fee, for instance.
    FEE = 'FEE'

    CHOICES = [PURCHASE, PAYMENT, REFUND, FEE]

    #: Which types increase what the user owes. Everything else reduces it.
    DEBITS = [PURCHASE, FEE]
    CREDITS = [PAYMENT, REFUND]


class CreditTransactionStatus:
    #: Authorised and holding limit, not yet settled.
    PENDING = 'PENDING'
    #: A bill payment waiting on the gateway. It has not touched the balance:
    #: credit is restored only when it moves to SUCCEEDED, and only the gateway's
    #: own record of the payment can move it there.
    PROCESSING = 'PROCESSING'
    SUCCEEDED = 'SUCCEEDED'
    #: Declined - a purchase refused by a limit or the card's state, or a bill
    #: payment the gateway reported as failed. Recorded rather than discarded,
    #: because "why was my card declined?" needs a row to answer it from.
    FAILED = 'FAILED'
    #: A bill payment the payer backed out of before any money moved.
    CANCELLED = 'CANCELLED'
    #: Reversed by a later compensating row. Shown to the holder as "Refunded".
    REVERSED = 'REVERSED'

    CHOICES = [PENDING, PROCESSING, SUCCEEDED, FAILED, CANCELLED, REVERSED]
    TERMINAL = [SUCCEEDED, FAILED, CANCELLED, REVERSED]


class BillPaymentMethod:
    """
    Instruments a credit-line bill may be paid from.

    The same vocabulary the EMI flow uses, because it goes through the same
    gateway integration. CREDIT_CARD is absent rather than refused: paying one
    credit line from another is revolving debt with extra steps, and there is no
    value a request could send to select it.
    """

    UPI_INTENT = 'UPI_INTENT'
    UPI_COLLECT = 'UPI_COLLECT'
    NETBANKING = 'NETBANKING'
    DEBIT_CARD = 'DEBIT_CARD'

    CHOICES = [UPI_INTENT, UPI_COLLECT, NETBANKING, DEBIT_CARD]
    UPI = [UPI_INTENT, UPI_COLLECT]

    LABELS = {
        UPI_INTENT: 'UPI',
        UPI_COLLECT: 'UPI ID',
        NETBANKING: 'Net Banking',
        DEBIT_CARD: 'Debit Card',
    }


class MerchantCategory:
    """
    Coarse categories, for the statement and for spend analysis.

    Deliberately short. A real MCC list belongs in a reference table fed by the
    network; this is what the product can honestly categorise today.
    """

    GROCERIES = 'GROCERIES'
    DINING = 'DINING'
    TRAVEL = 'TRAVEL'
    FUEL = 'FUEL'
    SHOPPING = 'SHOPPING'
    UTILITIES = 'UTILITIES'
    HEALTHCARE = 'HEALTHCARE'
    EDUCATION = 'EDUCATION'
    ENTERTAINMENT = 'ENTERTAINMENT'
    OTHER = 'OTHER'

    CHOICES = [
        GROCERIES, DINING, TRAVEL, FUEL, SHOPPING, UTILITIES, HEALTHCARE,
        EDUCATION, ENTERTAINMENT, OTHER,
    ]


class CreditTransactions(db.Model, AppendOnlyMixin):
    """
    One movement on a credit line.

    Append-only, like the ledger it mirrors. A purchase that is refunded gets a
    REFUND row and its own status moves to REVERSED; the original amount is
    never edited, because the statement it appeared on has already been issued.

    `balance_after` records what the user owed once this row landed. It is
    redundant against a running sum, which is exactly why it is here: a
    statement dispute is answered by what the account said at the time, and
    recomputing it from history hides any drift instead of exposing it.

    idempotency_key is UNIQUE. That constraint, not application logic, is what
    stops a double-tapped purchase from drawing the limit down twice.
    """

    __tablename__ = 'credit_transactions'
    __table_args__ = (
        db.Index('ix_credit_txn_account_created', 'credit_account_id', 'created_on'),
        db.Index('ix_credit_txn_statement', 'statement_id'),
    )

    credit_transaction_id = uuid_pk()
    credit_account_id = uuid_fk(
        'credit_accounts.credit_account_id', nullable=False, index=True,
    )
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    #: The ledger row this corresponds to. Every settled movement here has one;
    #: this column is what makes the two reconcilable.
    transaction_id = db.Column(db.String(36), nullable=True, index=True)

    transaction_type = db.Column(db.String(20), nullable=False, index=True)
    status = db.Column(
        db.String(20), default=CreditTransactionStatus.PENDING,
        nullable=False, index=True,
    )

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    #: What was owed on the account immediately after this row settled.
    balance_after = db.Column(db.Numeric(12, 2), nullable=True)
    #: What was left to spend immediately after this row settled - or, for a
    #: decline, what was available when it was refused. Stored for the same
    #: reason as balance_after: it is what the holder was told at the time, and
    #: deriving it later from a limit that may since have changed would restate
    #: history.
    available_after = db.Column(db.Numeric(12, 2), nullable=True)

    merchant_name = db.Column(db.String(120), nullable=True)
    merchant_category = db.Column(db.String(20), nullable=True)
    description = db.Column(db.String(200), nullable=True)

    idempotency_key = db.Column(
        db.String(64), unique=True, nullable=False, index=True,
    )

    #: Which statement cycle this fell into. Null until the cycle is cut, which
    #: is what distinguishes unbilled spend from billed.
    statement_id = db.Column(
        db.String(36), db.ForeignKey('credit_statements.statement_id'),
        nullable=True,
    )

    #: Set on a REFUND, pointing at what it reverses.
    reverses_credit_transaction_id = db.Column(
        db.String(36), nullable=True, index=True,
    )

    failure_code = db.Column(db.String(50), nullable=True)
    failure_reason = db.Column(db.String(500), nullable=True)

    # -- Bill payments only ------------------------------------------------
    # A payment arrives from outside through a gateway, so it carries the
    # identifiers needed to prove it did. Null on every other type.
    payment_method = db.Column(db.String(20), nullable=True)
    gateway_provider = db.Column(db.String(20), nullable=True)
    #: The order the gateway knows this payment by. Indexed because the webhook
    #: arrives with nothing else to find the row by.
    gateway_order_id = db.Column(db.String(100), nullable=True, index=True)
    gateway_payment_id = db.Column(db.String(100), nullable=True)
    #: The bank's reference for the collection - the UPI RRN - which is what a
    #: payer quotes to their bank when a payment is disputed.
    gateway_reference = db.Column(db.String(64), nullable=True)
    #: The statement the payer chose to pay, applied when the payment settles.
    #: Distinct from statement_id, which records the cycle a row was billed on.
    target_statement_id = db.Column(db.String(36), nullable=True)

    #: True only for a transaction produced by a test card in development. The
    #: column exists so a test movement can never be mistaken for a real one in
    #: a report, and so a production database can be checked for their absence.
    is_test = db.Column(db.Boolean, default=False, nullable=False)

    settled_at = db.Column(DATETIME(fsp=6), nullable=True)

    # Microsecond precision, not the TimestampMixin's plain DateTime. MySQL's
    # DATETIME stores whole seconds, so two purchases made in the same second
    # compared equal and `ORDER BY created_on DESC` returned them in an
    # arbitrary order - a cardholder saw their own spends listed wrongly. The
    # microseconds were already being generated; only the column was discarding
    # them.
    created_on = db.Column(DATETIME(fsp=6), default=utcnow, nullable=False)
    updated_on = db.Column(
        DATETIME(fsp=6), default=utcnow, onupdate=utcnow, nullable=False,
    )

    account = db.relationship('CreditAccounts', backref=db.backref(
        'transactions', lazy='dynamic',
    ))

    @property
    def is_debit(self) -> bool:
        return self.transaction_type in CreditTransactionType.DEBITS

    @property
    def signed_amount(self):
        """Positive when it increases what is owed, negative when it reduces it."""
        return self.amount if self.is_debit else -self.amount

    def __repr__(self):
        return (
            f'<CreditTransaction {self.credit_transaction_id} '
            f'{self.transaction_type} {self.amount} {self.status}>'
        )
