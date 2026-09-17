from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class PennyDropStatus:
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    NAME_MISMATCH = "NAME_MISMATCH"          # 70-80% similarity, manual review
    MANUAL_REVIEW_KYC = "MANUAL_REVIEW_KYC"  # below 70%, PMLA hold
    FAILED = "FAILED"

    CHOICES = [
        NOT_STARTED, IN_PROGRESS, VERIFIED,
        NAME_MISMATCH, MANUAL_REVIEW_KYC, FAILED,
    ]


class AccountType:
    SAVINGS = "SAVINGS"
    CURRENT = "CURRENT"

    CHOICES = [SAVINGS, CURRENT]


class BankAccounts(db.Model, TimestampMixin, CRUDMixin):
    """
    A destination bank account for payouts (PRD FR-005).

    PMLA constraint: the account must belong to the authenticated user.
    Third-party transfers are prohibited, which is what the penny-drop name
    match exists to prove - CashU sends 1 INR, reads back the name registered
    in the bank's core banking system, and compares it to the KYC PAN name.

    The account number is AES-256-GCM encrypted; only the last four digits are
    stored in the clear, for display and support lookup.
    """

    __tablename__ = 'bank_accounts'
    __table_args__ = (
        db.Index('ix_bank_accounts_user_status', 'user_id', 'penny_drop_status'),
    )

    bank_account_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    account_number_enc = db.Column(db.String(512), nullable=False)
    account_last4 = db.Column(db.String(4), nullable=False)
    # Blind index: SHA-256 of the account number, so a duplicate can be caught
    # without decrypting every row.
    account_number_hash = db.Column(db.String(64), nullable=False, index=True)

    ifsc_code = db.Column(db.String(11), nullable=False)
    bank_name = db.Column(db.String(150), nullable=True)
    branch_name = db.Column(db.String(200), nullable=True)
    account_type = db.Column(db.String(20), default=AccountType.SAVINGS)
    balance = db.Column(db.Numeric(12, 2), default=20000.00, nullable=False)

    account_holder_name = db.Column(db.String(200), nullable=True)   # user-entered
    verified_cbs_name = db.Column(db.String(200), nullable=True)     # from the bank
    name_match_score = db.Column(db.Numeric(5, 2), nullable=True)    # 0.00-100.00

    penny_drop_status = db.Column(
        db.String(30), default=PennyDropStatus.NOT_STARTED, nullable=False
    )
    penny_drop_reference = db.Column(db.String(150), nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)

    is_primary = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    deleted_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('Users', back_populates='bank_accounts')
    transfers = db.relationship('Transfers', back_populates='bank_account', lazy='dynamic')

    def __repr__(self):
        return f"<BankAccount {self.bank_name} ****{self.account_last4}>"

    @property
    def is_payout_eligible(self) -> bool:
        return (
            self.penny_drop_status == PennyDropStatus.VERIFIED
            and self.is_active
            and self.deleted_at is None
        )

    def masked_account(self) -> str:
        return f"**** {self.account_last4}"
