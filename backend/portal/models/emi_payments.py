from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class PaymentMode:
    """
    PRD section 11.1 permitted instruments.

    CREDIT_CARD is deliberately absent. RBI prohibits servicing loan debt from
    a revolving credit line, so the option does not exist in the vocabulary -
    it cannot be selected even by a hand-crafted request.
    """

    UPI_INTENT = "UPI_INTENT"
    UPI_COLLECT = "UPI_COLLECT"
    NETBANKING = "NETBANKING"
    DEBIT_CARD = "DEBIT_CARD"

    CHOICES = [UPI_INTENT, UPI_COLLECT, NETBANKING, DEBIT_CARD]


class EMIPaymentState:
    """PRD section 11.1 lifecycle."""

    INITIATED = "INITIATED"
    PROCESSING = "PROCESSING"
    SUCCESSFUL = "SUCCESSFUL"
    SETTLED = "SETTLED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"
    REFUNDED = "REFUNDED"

    CHOICES = [
        INITIATED, PROCESSING, SUCCESSFUL, SETTLED, PENDING,
        CANCELLED, FAILED, REVERSED, REFUNDED,
    ]

    TERMINAL = [SETTLED, CANCELLED, FAILED, REFUNDED]

    # PROCESSING and PENDING both reach CANCELLED: a user who dismisses UPI
    # checkout abandons an attempt that has already left INITIATED. The engine
    # only takes that route once the gateway confirms nothing was collected, so
    # the transition is reachable but never a way to discard a real payment.
    ALLOWED = {
        INITIATED: [PROCESSING, CANCELLED, FAILED],
        PROCESSING: [SUCCESSFUL, PENDING, CANCELLED, FAILED],
        PENDING: [SUCCESSFUL, CANCELLED, FAILED],
        SUCCESSFUL: [SETTLED, REVERSED],
        REVERSED: [REFUNDED],
        SETTLED: [],
        CANCELLED: [],
        FAILED: [],
        REFUNDED: [],
    }


class EMIPayments(db.Model, TimestampMixin, CRUDMixin):
    """One installment payment attempt (PRD FR-008, FR-009)."""

    __tablename__ = 'emi_payments'
    __table_args__ = (
        db.Index('ix_emipay_emi_created', 'emi_id', 'created_on'),
    )

    payment_id = uuid_pk()
    emi_id = uuid_fk('emi_obligations.emi_id', nullable=False, index=True)
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    transaction_id = db.Column(db.String(36), nullable=True, index=True)
    mandate_id = db.Column(db.String(36), nullable=True, index=True)

    amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_mode = db.Column(db.String(30), nullable=False)
    is_auto_pay = db.Column(db.Boolean, default=False)

    idempotency_key = db.Column(db.String(64), unique=True, nullable=False, index=True)

    status = db.Column(
        db.String(20), default=EMIPaymentState.INITIATED, nullable=False, index=True
    )

    gateway_provider = db.Column(db.String(30), nullable=True)
    gateway_order_id = db.Column(db.String(150), nullable=True, index=True)

    # Unique, not merely indexed. A gateway payment id identifies exactly one
    # collection of money, so two payment rows claiming the same one would mean
    # one UPI debit had settled two installments. The database refuses it
    # rather than leaving the guarantee to whichever handler wins the race.
    gateway_payment_id = db.Column(
        db.String(150), nullable=True, unique=True, index=True
    )

    # The HMAC Checkout returned in the browser, kept for dispute forensics.
    # It is evidence that the handler payload was genuine - never the reason a
    # payment is treated as settled, which is always a fresh API read.
    gateway_signature = db.Column(db.String(255), nullable=True)

    checkout_url = db.Column(db.String(1000), nullable=True)

    # UPI specifics. `upi_app` is the app the user chose before handoff, which
    # is a preference rather than a fact - the UPI stack lets them switch apps
    # mid-flow, and `upi_vpa` records the address that actually paid.
    upi_app = db.Column(db.String(30), nullable=True)
    upi_vpa = db.Column(db.String(120), nullable=True)
    upi_rrn = db.Column(db.String(50), nullable=True, index=True)

    bbps_rrn = db.Column(db.String(50), nullable=True, index=True)
    biller_ack_utr = db.Column(db.String(50), nullable=True)
    receipt_path = db.Column(db.String(500), nullable=True)

    installment_number = db.Column(db.Integer, nullable=True)
    due_date = db.Column(db.Date, nullable=True)

    # Polling worker state - PRD FR-008 polls a PENDING payment every 15
    # minutes for up to 24 hours before giving up.
    poll_attempts = db.Column(db.Integer, default=0)
    next_poll_at = db.Column(db.DateTime, nullable=True, index=True)

    paid_at = db.Column(db.DateTime, nullable=True)
    settled_at = db.Column(db.DateTime, nullable=True)
    failure_code = db.Column(db.String(50), nullable=True)
    failure_reason = db.Column(db.String(500), nullable=True)

    obligation = db.relationship('EMIObligations', back_populates='payments')

    def __repr__(self):
        return f"<EMIPayment {self.amount} {self.status}>"

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in EMIPaymentState.ALLOWED.get(self.status, [])
