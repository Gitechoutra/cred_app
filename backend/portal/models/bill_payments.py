from sqlalchemy.dialects.mysql import DATETIME

from portal import db
from portal.models.base import AppendOnlyMixin, uuid_pk, uuid_fk, utcnow


class BillCategory:
    """
    What kind of bill the credit is being used for.

    A fixed vocabulary for the same reason CreditPurpose is one: this is the
    field that decides whether a draw is an eligible expense, and a free-text
    answer can be neither reported on nor enforced against.
    """

    ELECTRICITY = 'ELECTRICITY'
    WATER = 'WATER'
    GAS = 'GAS'
    BROADBAND = 'BROADBAND'
    MOBILE_POSTPAID = 'MOBILE_POSTPAID'
    DTH = 'DTH'
    INSURANCE = 'INSURANCE'
    EDUCATION = 'EDUCATION'
    RENT = 'RENT'
    MEDICAL = 'MEDICAL'
    OTHER = 'OTHER'

    CHOICES = [
        ELECTRICITY, WATER, GAS, BROADBAND, MOBILE_POSTPAID, DTH, INSURANCE,
        EDUCATION, RENT, MEDICAL, OTHER,
    ]

    LABELS = {
        ELECTRICITY: 'Electricity',
        WATER: 'Water',
        GAS: 'Gas',
        BROADBAND: 'Internet / Broadband',
        MOBILE_POSTPAID: 'Mobile Postpaid',
        DTH: 'DTH / TV',
        INSURANCE: 'Insurance',
        EDUCATION: 'Education Fees',
        RENT: 'Rent',
        MEDICAL: 'Medical / Hospital',
        OTHER: 'Other Eligible Bills',
    }

    #: Billers offered per category. A reference list, not a BBPS directory:
    #: the real one comes from the Biller Operating Unit once PRD section 27
    #: names it. OTHER is absent on purpose - there the payee is typed.
    PROVIDERS = {
        ELECTRICITY: [
            'Tata Power', 'Adani Electricity', 'BESCOM', 'MSEDCL', 'TSSPDCL',
            'BSES Rajdhani', 'CESC', 'TNEB (TANGEDCO)',
        ],
        WATER: [
            'Delhi Jal Board', 'BWSSB Bengaluru', 'HMWSSB Hyderabad',
            'MCGM Water', 'Chennai Metrowater',
        ],
        GAS: [
            'Indraprastha Gas', 'Mahanagar Gas', 'Adani Total Gas',
            'Gujarat Gas', 'HP Gas', 'Indane', 'Bharat Gas',
        ],
        BROADBAND: [
            'Airtel Xstream Fiber', 'JioFiber', 'ACT Fibernet', 'BSNL Broadband',
            'Hathway', 'Excitel',
        ],
        MOBILE_POSTPAID: [
            'Airtel Postpaid', 'Jio Postpaid', 'Vi Postpaid', 'BSNL Postpaid',
        ],
        DTH: ['Tata Play', 'Airtel Digital TV', 'Dish TV', 'Sun Direct', 'd2h'],
        INSURANCE: [
            'LIC of India', 'HDFC Life', 'ICICI Prudential Life', 'SBI Life',
            'Star Health', 'Niva Bupa', 'ICICI Lombard',
        ],
        EDUCATION: [
            'School fees', 'College / University fees', 'Coaching institute',
            'Exam or application fee',
        ],
        RENT: ['House rent', 'Office / shop rent', 'Hostel / PG rent'],
        MEDICAL: [
            'Hospital bill', 'Diagnostic lab', 'Pharmacy', 'Clinic consultation',
        ],
    }


class BillPurpose:
    """
    The declared reason for drawing credit, chosen separately from the category.

    Asked for twice on purpose - once as the kind of bill, once as the reason -
    so a mismatch between the two is visible in review rather than assumed away.
    OTHER carries a required note.
    """

    ELECTRICITY = 'ELECTRICITY'
    WATER = 'WATER'
    BROADBAND = 'BROADBAND'
    MOBILE = 'MOBILE'
    EDUCATION = 'EDUCATION'
    INSURANCE = 'INSURANCE'
    MEDICAL = 'MEDICAL'
    RENT = 'RENT'
    OTHER = 'OTHER'

    CHOICES = [
        ELECTRICITY, WATER, BROADBAND, MOBILE, EDUCATION, INSURANCE, MEDICAL,
        RENT, OTHER,
    ]

    LABELS = {
        ELECTRICITY: 'Electricity Bill',
        WATER: 'Water Bill',
        BROADBAND: 'Internet / Broadband Bill',
        MOBILE: 'Mobile Bill',
        EDUCATION: 'Education Fee',
        INSURANCE: 'Insurance Payment',
        MEDICAL: 'Medical Expense',
        RENT: 'Rent Payment',
        OTHER: 'Other Eligible Bill',
    }


class BillPaymentStatus:
    """
    Where a Pay Bills request is.

    AWAITING_OTP is the only state before any money moves: the request is
    recorded and priced, and nothing has touched the credit line. Everything
    after it has drawn credit, so every path out of those states either
    confirms the payout or gives the credit back.

        AWAITING_OTP -> PROCESSING -> SUCCEEDED
                                   -> PENDING -> SUCCEEDED | FAILED
                                   -> FAILED           (credit restored)
        SUCCEEDED    -> REVERSED                        (bank returned it)
        AWAITING_OTP -> CANCELLED | EXPIRED             (nothing moved)
    """

    AWAITING_OTP = 'AWAITING_OTP'
    #: Credit drawn and the payout handed to the rail. Not yet confirmed.
    PROCESSING = 'PROCESSING'
    #: The rail accepted the payout but has not confirmed it within the
    #: synchronous window. Settled later by the poller.
    PENDING = 'PENDING'
    SUCCEEDED = 'SUCCEEDED'
    #: The payout was refused. The credit drawn has been restored in full.
    FAILED = 'FAILED'
    #: The payout was confirmed and later returned by the beneficiary bank.
    #: The credit drawn has been restored in full.
    REVERSED = 'REVERSED'
    CANCELLED = 'CANCELLED'
    EXPIRED = 'EXPIRED'

    CHOICES = [
        AWAITING_OTP, PROCESSING, PENDING, SUCCEEDED, FAILED, REVERSED,
        CANCELLED, EXPIRED,
    ]
    #: States in which credit is drawn and the outcome is not yet known.
    IN_FLIGHT = [PROCESSING, PENDING]
    TERMINAL = [SUCCEEDED, FAILED, REVERSED, CANCELLED, EXPIRED]


class BillPayments(db.Model, AppendOnlyMixin):
    """
    One Pay Bills request: credit drawn for a declared bill, paid out to the
    holder's own verified bank account.

    ⚑ Regulatory note. This moves credit-line money to a bank account, the
    movement Version1.md section 2 removed on 2026-09-24. It was reinstated at
    the product owner's request on 2026-09-30 behind the controls below, and
    runs on the sandbox payout rail only until a licensed issuing/PA partner
    signs off the merchant model (PRD open decision #1).

    What the row proves, for audit:
      - what was declared (category, provider, bill reference, purpose, note)
      - what was disclosed and accepted (fee, GST, total, consent timestamp and
        the disclosure version the holder saw)
      - that the holder authenticated it (OTP verified timestamp)
      - where the money went (bank account id, masked, and the rail's UTR)
      - what happened to the credit (the draw and, if any, the restoring row)

    Append-only in the ledger sense: amounts are never edited after the quote
    is accepted. Status and the rail's references are the only mutations, and
    only bill_pay_engine makes them.
    """

    __tablename__ = 'bill_payments'
    __table_args__ = (
        db.Index('ix_bill_payments_user_created', 'user_id', 'created_on'),
        db.Index('ix_bill_payments_status', 'status'),
    )

    bill_payment_id = uuid_pk()
    #: Shown to the holder as the transaction ID - CASHU plus ten characters.
    #: Not the primary key, so a receipt never exposes an internal identifier.
    reference = db.Column(db.String(20), unique=True, nullable=False, index=True)

    user_id = uuid_fk('users.user_id', nullable=False, index=True)
    credit_account_id = uuid_fk(
        'credit_accounts.credit_account_id', nullable=False, index=True,
    )
    bank_account_id = uuid_fk(
        'bank_accounts.bank_account_id', nullable=False, index=True,
    )

    status = db.Column(
        db.String(20), default=BillPaymentStatus.AWAITING_OTP, nullable=False,
    )

    # -- What was declared ------------------------------------------------
    category = db.Column(db.String(20), nullable=False)
    provider = db.Column(db.String(120), nullable=False)
    bill_reference_number = db.Column(db.String(50), nullable=False)
    purpose = db.Column(db.String(20), nullable=False)
    #: Required when purpose is OTHER, refused otherwise.
    purpose_note = db.Column(db.String(200), nullable=True)

    # -- What was priced and disclosed ------------------------------------
    bill_amount = db.Column(db.Numeric(12, 2), nullable=False)
    fee_percent = db.Column(db.Numeric(5, 2), nullable=False)
    fee_amount = db.Column(db.Numeric(12, 2), nullable=False)
    gst_amount = db.Column(db.Numeric(12, 2), nullable=False)
    #: bill + fee + GST: what the credit line is charged.
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    #: The destination as shown on the review screen, e.g. "HDFC Bank •••• 4582".
    #: Captured, not recomputed, so a later rename of the account does not
    #: change what the receipt says the holder agreed to.
    bank_display = db.Column(db.String(160), nullable=False)

    # -- Consent and authentication ---------------------------------------
    consent_at = db.Column(DATETIME(fsp=6), nullable=False)
    #: Which wording of the disclosure the holder accepted.
    disclosure_version = db.Column(db.String(20), nullable=False)
    otp_verified_at = db.Column(DATETIME(fsp=6), nullable=True)

    # -- What happened to the credit --------------------------------------
    #: The master_transactions row for the draw. History reads this.
    transaction_id = db.Column(db.String(36), nullable=True, index=True)
    #: The credit_transactions row that drew the line down.
    credit_transaction_id = db.Column(db.String(36), nullable=True, index=True)
    #: The credit_transactions row that restored it, on failure or reversal.
    restore_credit_transaction_id = db.Column(db.String(36), nullable=True)
    #: Available credit immediately after the draw - what the holder was told.
    available_after = db.Column(db.Numeric(12, 2), nullable=True)

    # -- The payout -------------------------------------------------------
    payout_provider = db.Column(db.String(20), nullable=True)
    payout_reference = db.Column(db.String(100), nullable=True, index=True)
    #: The bank's UTR: what the holder quotes to their bank to trace the credit.
    bank_utr = db.Column(db.String(50), nullable=True)
    payout_dispatched_at = db.Column(DATETIME(fsp=6), nullable=True)
    completed_at = db.Column(DATETIME(fsp=6), nullable=True)

    failure_code = db.Column(db.String(50), nullable=True)
    failure_reason = db.Column(db.String(500), nullable=True)

    idempotency_key = db.Column(db.String(64), unique=True, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    device_uuid = db.Column(db.String(100), nullable=True)

    created_on = db.Column(DATETIME(fsp=6), default=utcnow, nullable=False)
    updated_on = db.Column(
        DATETIME(fsp=6), default=utcnow, onupdate=utcnow, nullable=False,
    )

    bank_account = db.relationship('BankAccounts')

    @property
    def category_label(self) -> str:
        return BillCategory.LABELS.get(self.category, self.category)

    @property
    def purpose_label(self) -> str:
        return BillPurpose.LABELS.get(self.purpose, self.purpose)

    def __repr__(self):
        return f'<BillPayment {self.reference} {self.status} {self.total_amount}>'
