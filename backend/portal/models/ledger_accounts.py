from portal import db
from portal.models.base import TimestampMixin, CRUDMixin


class AccountClass:
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"

    CHOICES = [ASSET, LIABILITY, INCOME, EXPENSE]


class LedgerAccounts(db.Model, TimestampMixin, CRUDMixin):
    """
    Chart of accounts - the vocabulary of account_code in double_entry_ledger.

    Seeded and never user-editable. A ledger posting that names an account code
    not in this table is rejected before it is written, which is what stops a
    typo from creating a silent orphan entry that breaks reconciliation.

    Normal balance convention:
      ASSET / EXPENSE      increase on DEBIT
      LIABILITY / INCOME   increase on CREDIT
    """

    __tablename__ = 'ledger_accounts'

    account_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    account_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    account_name = db.Column(db.String(150), nullable=False)
    account_class = db.Column(db.String(20), nullable=False)
    normal_balance = db.Column(db.String(10), nullable=False)   # DEBIT | CREDIT
    description = db.Column(db.String(500), nullable=True)

    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<LedgerAccount {self.account_code}>"
