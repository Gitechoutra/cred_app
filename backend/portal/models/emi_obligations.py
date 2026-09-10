from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class LoanType:
    CONSUMER_DURABLE = "CONSUMER_DURABLE"
    PERSONAL_LOAN = "PERSONAL_LOAN"
    TWO_WHEELER = "TWO_WHEELER"
    HOME_APPLIANCE = "HOME_APPLIANCE"
    EDUCATION = "EDUCATION"

    CHOICES = [
        CONSUMER_DURABLE, PERSONAL_LOAN, TWO_WHEELER,
        HOME_APPLIANCE, EDUCATION,
    ]


class AutoPayStatus:
    NOT_CONFIGURED = "NOT_CONFIGURED"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    PAUSED = "PAUSED"

    CHOICES = [NOT_CONFIGURED, ACTIVE, FAILED, PAUSED]


class EMIPaymentStatus:
    DUE = "DUE"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    PROCESSING = "PROCESSING"

    CHOICES = [DUE, PAID, OVERDUE, PROCESSING]


class EMIObligations(db.Model, TimestampMixin, CRUDMixin):
    """
    A tracked loan (PRD FR-007, data spec 10.2).

    The loan account number is encrypted at rest and shown masked in the UI
    (LAN-******7819 per the PRD), because a LAN plus a phone number is enough
    to impersonate a borrower on most NBFC support lines.
    """

    __tablename__ = 'emi_obligations'
    __table_args__ = (
        db.Index('ix_emi_user_status', 'user_id', 'payment_status'),
    )

    emi_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)
    provider_id = db.Column(
        db.Integer, db.ForeignKey('emi_providers.provider_id'), nullable=False
    )

    provider_name = db.Column(db.String(150), nullable=False)
    loan_account_no_enc = db.Column(db.String(512), nullable=False)
    loan_account_last4 = db.Column(db.String(4), nullable=False)
    registered_phone = db.Column(db.String(15), nullable=True)

    loan_type = db.Column(db.String(30), default=LoanType.CONSUMER_DURABLE)
    nickname = db.Column(db.String(100), nullable=True)

    total_loan_amount = db.Column(db.Numeric(12, 2), nullable=True)
    emi_amount = db.Column(db.Numeric(12, 2), nullable=False)
    due_day_of_month = db.Column(db.Integer, nullable=False)   # 1-31
    total_tenure = db.Column(db.Integer, nullable=True)
    tenure_remaining = db.Column(db.Integer, nullable=True)
    outstanding_bal = db.Column(db.Numeric(12, 2), nullable=True)
    interest_rate = db.Column(db.Numeric(5, 2), nullable=True)

    next_due_date = db.Column(db.Date, nullable=True, index=True)
    last_paid_date = db.Column(db.Date, nullable=True)

    auto_pay_status = db.Column(db.String(20), default=AutoPayStatus.NOT_CONFIGURED)
    payment_status = db.Column(db.String(20), default=EMIPaymentStatus.DUE, index=True)

    # Set when the provider API was unavailable and the user typed the details
    # in by hand - PRD FR-007 requires an admin to verify these against the
    # uploaded sanction letter before auto-pay can be armed.
    is_manually_created = db.Column(db.Boolean, default=False)
    loan_document_path = db.Column(db.String(500), nullable=True)
    admin_verified = db.Column(db.Boolean, default=False)
    admin_verified_at = db.Column(db.DateTime, nullable=True)

    is_active = db.Column(db.Boolean, default=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('Users', back_populates='emi_obligations')
    provider = db.relationship('EMIProviders', back_populates='obligations')
    payments = db.relationship('EMIPayments', back_populates='obligation', lazy='dynamic')
    mandate = db.relationship(
        'AutoPayMandates', back_populates='obligation', uselist=False
    )

    def __repr__(self):
        return f"<EMI {self.provider_name} {self.emi_amount}>"

    def masked_loan_account(self) -> str:
        return f"LAN-******{self.loan_account_last4}"
