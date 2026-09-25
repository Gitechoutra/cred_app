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
    SUCCEEDED = 'SUCCEEDED'
    FAILED = 'FAILED'
    #: Reversed by a later compensating row.
    REVERSED = 'REVERSED'

    CHOICES = [PENDING, SUCCEEDED, FAILED, REVERSED]
    TERMINAL = [SUCCEEDED, FAILED, REVERSED]


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
