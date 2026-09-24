from decimal import Decimal

from portal import db
from portal.models.base import (
    AppendOnlyMixin, TimestampMixin, uuid_pk, uuid_fk,
)


class StatementStatus:
    #: Cut and issued, nothing paid yet, still inside the grace period.
    UNPAID = 'UNPAID'
    #: At least the minimum due paid, but not the full closing balance.
    PARTIALLY_PAID = 'PARTIALLY_PAID'
    #: Closing balance settled in full.
    PAID = 'PAID'
    #: Past the due date with the minimum due unmet.
    OVERDUE = 'OVERDUE'

    CHOICES = [UNPAID, PARTIALLY_PAID, PAID, OVERDUE]
    #: A statement in one of these still owes money.
    OUTSTANDING = [UNPAID, PARTIALLY_PAID, OVERDUE]


class CreditStatements(db.Model, TimestampMixin, AppendOnlyMixin):
    """
    One billing cycle on a credit line.

    Append-only in its money columns. Once a statement is cut, the opening
    balance, the purchases, the closing balance and the minimum due are what the
    user was told they owe - a later correction is a transaction in the next
    cycle, not an edit to this row. `amount_paid` and `status` do move, because
    they record what has since happened against it rather than restating the
    bill.

    Why the totals are stored rather than summed on read: the minimum due is a
    percentage of the closing balance at the moment of cutting, and a spend that
    lands a second later must not change what was already billed. Summing the
    transactions on each read would do exactly that.
    """

    __tablename__ = 'credit_statements'
    __table_args__ = (
        db.Index('ix_statement_account_period', 'credit_account_id', 'period_end'),
        # One statement per account per cycle. The scheduler is idempotent
        # because of this constraint, not because of a check-then-write.
        db.UniqueConstraint(
            'credit_account_id', 'period_end', name='uq_statement_period',
        ),
    )

    statement_id = uuid_pk()
    credit_account_id = uuid_fk(
        'credit_accounts.credit_account_id', nullable=False, index=True,
    )
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    #: Human-facing reference, printed on the statement.
    statement_number = db.Column(db.String(24), unique=True, nullable=False)

    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    statement_date = db.Column(db.Date, nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)

    # -- The bill, as issued ----------------------------------------------
    opening_balance = db.Column(db.Numeric(12, 2), nullable=False)
    total_purchases = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_payments = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_refunds = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    total_fees = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    closing_balance = db.Column(db.Numeric(12, 2), nullable=False)
    minimum_due = db.Column(db.Numeric(12, 2), nullable=False)
    #: The percentage used, recorded so an old statement still explains its own
    #: minimum after the setting changes.
    minimum_due_percent = db.Column(db.Numeric(5, 2), nullable=False)

    # -- What has happened since -------------------------------------------
    amount_paid = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    status = db.Column(
        db.String(20), default=StatementStatus.UNPAID, nullable=False, index=True,
    )
    fully_paid_at = db.Column(db.DateTime, nullable=True)
    #: Set once, when the late fee is charged, so it cannot be charged twice for
    #: the same cycle.
    late_fee_charged_at = db.Column(db.DateTime, nullable=True)

    account = db.relationship('CreditAccounts', backref=db.backref(
        'statements', lazy='dynamic',
    ))
    transactions = db.relationship(
        'CreditTransactions', backref='statement', lazy='dynamic',
    )

    @property
    def amount_outstanding(self):
        return self.closing_balance - self.amount_paid

    @property
    def minimum_outstanding(self):
        """What still has to be paid to avoid going overdue, never below zero."""
        remaining = self.minimum_due - self.amount_paid
        return remaining if remaining > 0 else Decimal('0.00')

    def __repr__(self):
        return (
            f'<CreditStatement {self.statement_number} '
            f'{self.closing_balance} {self.status}>'
        )
