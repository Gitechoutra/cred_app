from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class MandateType:
    """
    PRD 12.1 routing rule: UPI AutoPay handles EMIs up to 15,000 INR without a
    per-debit OTP; e-NACH covers higher-value loans up to 10,00,000 INR.
    """

    UPI_AUTOPAY = "UPI_AUTOPAY"
    ENACH = "ENACH"

    CHOICES = [UPI_AUTOPAY, ENACH]

    #: Ceiling above which UPI AutoPay is not permitted.
    UPI_AUTOPAY_MAX = 15000


class MandateStatus:
    PENDING_AFA = "PENDING_AFA"     # awaiting the registration auth challenge
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"             # cancelled by the user at bank level
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"

    CHOICES = [PENDING_AFA, ACTIVE, PAUSED, REVOKED, FAILED, EXPIRED]


class MandateFrequency:
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"

    CHOICES = [MONTHLY, QUARTERLY]


class AutoPayMandates(db.Model, TimestampMixin, CRUDMixin):
    """
    An NPCI e-Mandate / UPI AutoPay registration (PRD FR-009, section 12).

    Regulatory requirements baked into this model:
      - AFA challenge at registration (status starts PENDING_AFA)
      - max_amount at least 110% of the EMI, so an interest adjustment does not
        bounce, while still bounding an arbitrary debit
      - pre-debit notice dispatched T-24h or earlier, tracked here so the
        scheduler cannot double-send or silently skip it
      - user pause/cancel available up to 24h before the debit
    """

    __tablename__ = 'auto_pay_mandates'

    mandate_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)
    emi_id = uuid_fk('emi_obligations.emi_id', nullable=False, unique=True)
    bank_account_id = uuid_fk('bank_accounts.bank_account_id', nullable=True)

    mandate_type = db.Column(db.String(20), nullable=False)
    # Unique Mandate Number issued by NPCI on bank authorization.
    mandate_umn = db.Column(db.String(100), nullable=True, unique=True, index=True)
    provider_reference = db.Column(db.String(150), nullable=True)

    upi_vpa = db.Column(db.String(150), nullable=True)
    debit_instrument = db.Column(db.String(50), nullable=True)

    max_amount = db.Column(db.Numeric(12, 2), nullable=False)
    frequency = db.Column(db.String(20), default=MandateFrequency.MONTHLY)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)

    status = db.Column(
        db.String(20), default=MandateStatus.PENDING_AFA, nullable=False, index=True
    )

    next_debit_date = db.Column(db.Date, nullable=True, index=True)
    last_debit_date = db.Column(db.Date, nullable=True)
    # Guards against duplicate pre-debit notices when the scheduler reruns.
    predebit_notice_sent_for = db.Column(db.Date, nullable=True)

    afa_completed_at = db.Column(db.DateTime, nullable=True)
    activated_at = db.Column(db.DateTime, nullable=True)
    paused_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    revoked_reason = db.Column(db.String(255), nullable=True)

    consecutive_failures = db.Column(db.Integer, default=0)

    user = db.relationship('Users', back_populates='mandates')
    obligation = db.relationship('EMIObligations', back_populates='mandate')
    debit_attempts = db.relationship(
        'MandateDebitAttempts', back_populates='mandate', lazy='dynamic'
    )

    def __repr__(self):
        return f"<Mandate {self.mandate_umn} {self.status}>"
