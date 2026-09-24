from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class CreditAccountStatus:
    """
    The lifecycle of an issued credit line.

    PENDING_PURPOSE is its own state rather than a flag, because the purpose of
    credit is a hard gate: an approved account with no declared purpose cannot
    be activated and cannot spend.
    """

    #: Approved and issued, but the applicant has not declared what the credit
    #: is for. Cannot spend.
    PENDING_PURPOSE = 'PENDING_PURPOSE'
    #: Purpose declared, waiting for the applicant to activate. Cannot spend.
    PENDING_ACTIVATION = 'PENDING_ACTIVATION'
    ACTIVE = 'ACTIVE'
    #: Temporarily stopped - by the user, or by an administrator on a risk
    #: signal. Reversible, and the balance stays owed.
    BLOCKED = 'BLOCKED'
    #: Settled and shut. Terminal.
    CLOSED = 'CLOSED'

    CHOICES = [PENDING_PURPOSE, PENDING_ACTIVATION, ACTIVE, BLOCKED, CLOSED]
    #: The only state in which money may be spent.
    SPENDABLE = [ACTIVE]

    ALLOWED = {
        PENDING_PURPOSE: [PENDING_ACTIVATION, CLOSED],
        PENDING_ACTIVATION: [ACTIVE, CLOSED],
        ACTIVE: [BLOCKED, CLOSED],
        BLOCKED: [ACTIVE, CLOSED],
        CLOSED: [],
    }


class CreditPurpose:
    """
    What the credit is for. Declared by the applicant before activation.

    A fixed vocabulary rather than free text, because this is the field that
    decides what the product is allowed to be used for, and a free-text answer
    cannot be reported on or enforced against.
    """

    EDUCATION = 'EDUCATION'
    MEDICAL = 'MEDICAL'
    SHOPPING = 'SHOPPING'
    TRAVEL = 'TRAVEL'
    BUSINESS = 'BUSINESS'
    BILLS = 'BILLS'
    EMERGENCY = 'EMERGENCY'
    #: The only option that carries a note, and the note is then required.
    OTHER = 'OTHER'

    CHOICES = [
        EDUCATION, MEDICAL, SHOPPING, TRAVEL, BUSINESS, BILLS, EMERGENCY, OTHER,
    ]

    LABELS = {
        EDUCATION: 'Education',
        MEDICAL: 'Medical',
        SHOPPING: 'Shopping',
        TRAVEL: 'Travel',
        BUSINESS: 'Business',
        BILLS: 'Bill payments',
        EMERGENCY: 'Emergency',
        OTHER: 'Other',
    }


class CreditAccounts(db.Model, TimestampMixin, CRUDMixin):
    """
    An issued credit line and the card that draws on it.

    On what is stored about the card: last four digits, BIN, network, expiry and
    the name on it. Never the full number, never a CVV, never a PIN. The display
    number the user sees is composed at the edge from the BIN and last four; the
    middle digits are not persisted anywhere, so there is nothing here to leak.

    On the balances: `available_credit` is derived state, and the only writer is
    credit_engine under a row lock. It is stored rather than computed on read
    because a spend has to check and decrement it in one atomic step - computing
    it from the transaction history on each request would let two concurrent
    purchases both pass the same check.

    The invariant, asserted by the engine on every write:

        available_credit + current_outstanding == credit_limit
    """

    __tablename__ = 'credit_accounts'
    __table_args__ = (
        db.Index('ix_credit_account_user_status', 'user_id', 'status'),
    )

    credit_account_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)
    application_id = uuid_fk(
        'credit_applications.application_id', nullable=False, index=True,
    )

    status = db.Column(
        db.String(20), default=CreditAccountStatus.PENDING_PURPOSE,
        nullable=False, index=True,
    )

    # -- The card (no PAN, no CVV, ever) ----------------------------------
    card_bin = db.Column(db.String(6), nullable=False)
    card_last4 = db.Column(db.String(4), nullable=False)
    card_network = db.Column(db.String(20), nullable=False)
    name_on_card = db.Column(db.String(80), nullable=False)
    expiry_month = db.Column(db.String(2), nullable=False)
    expiry_year = db.Column(db.String(4), nullable=False)

    # -- Money -------------------------------------------------------------
    credit_limit = db.Column(db.Numeric(12, 2), nullable=False)
    available_credit = db.Column(db.Numeric(12, 2), nullable=False)
    current_outstanding = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    currency = db.Column(db.String(3), default='INR', nullable=False)

    # -- Purpose of credit -------------------------------------------------
    purpose = db.Column(db.String(20), nullable=True)
    #: Required when purpose is OTHER, refused otherwise.
    purpose_note = db.Column(db.String(200), nullable=True)
    purpose_declared_at = db.Column(db.DateTime, nullable=True)

    # -- Billing cycle -----------------------------------------------------
    #: Day of month the statement is cut. Copied from settings at issuance so a
    #: later settings change does not silently move every existing account's
    #: cycle, which would move due dates people have already been told.
    statement_day = db.Column(db.Integer, nullable=False)
    grace_days = db.Column(db.Integer, nullable=False)

    activated_at = db.Column(db.DateTime, nullable=True)
    blocked_at = db.Column(db.DateTime, nullable=True)
    block_reason = db.Column(db.String(200), nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('Users', backref=db.backref(
        'credit_accounts', lazy='dynamic',
    ))
    application = db.relationship('CreditApplications', backref=db.backref(
        'credit_account', uselist=False,
    ))

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in CreditAccountStatus.ALLOWED.get(self.status, [])

    @property
    def can_spend(self) -> bool:
        return self.status in CreditAccountStatus.SPENDABLE

    @property
    def masked_number(self) -> str:
        """What is safe to show: the BIN, filler, and the last four."""
        return f'{self.card_bin}******{self.card_last4}'

    @property
    def utilization_percent(self):
        if not self.credit_limit:
            return None
        return round(
            float(self.current_outstanding) / float(self.credit_limit) * 100, 2
        )

    def __repr__(self):
        return (
            f'<CreditAccount {self.credit_account_id} {self.status} '
            f'{self.available_credit}/{self.credit_limit}>'
        )
