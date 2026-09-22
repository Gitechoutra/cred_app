from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class QRPaymentState:
    """
    Lifecycle of a scanned payment.

    Mirrors the EMI payment states rather than inventing a vocabulary: the same
    poller, the same terminal set, and the same meaning for PENDING - money may
    have moved and we cannot yet confirm it.
    """

    INITIATED = 'INITIATED'
    PROCESSING = 'PROCESSING'
    SUCCESSFUL = 'SUCCESSFUL'
    PENDING = 'PENDING'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'

    CHOICES = [INITIATED, PROCESSING, SUCCESSFUL, PENDING, FAILED, CANCELLED]
    TERMINAL = [SUCCESSFUL, FAILED, CANCELLED]


class QRPayments(db.Model, TimestampMixin, CRUDMixin):
    """
    A payment made by scanning a UPI QR code.

    A different product from a transfer, and the distinction is worth stating:
    a transfer moves money from the user's *credit card* to the user's *own*
    verified bank account, and third-party destinations are refused outright.
    A scanned payment sends money from the user's bank, over UPI, to somebody
    else - a merchant. Neither the card rail nor the penny-drop name check
    applies, because neither is relevant.

    What is stored about the payee is deliberately thin: an address and a
    display name that came off a sticker. Both are validated and sanitised at
    the boundary (helpers/upi_qr.py) and neither is trusted for anything beyond
    display and routing.
    """

    __tablename__ = 'qr_payments'
    __table_args__ = (
        db.Index('ix_qrpay_user_created', 'user_id', 'created_on'),
    )

    qr_payment_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    transaction_id = db.Column(db.String(36), nullable=True, index=True)

    #: The payee, as scanned. Stored in full because it is the destination the
    #: payment was actually sent to and a dispute turns on it; the API masks it
    #: on the way out.
    payee_vpa = db.Column(db.String(128), nullable=False)
    payee_name = db.Column(db.String(80), nullable=True)

    amount = db.Column(db.Numeric(12, 2), nullable=False)

    #: True when the QR carried the amount, so it could not be edited. Worth
    #: keeping: "the sticker said 120" and "the payer typed 120" are different
    #: facts if the payee later disputes the sum.
    amount_from_qr = db.Column(db.Boolean, default=False)

    note = db.Column(db.String(120), nullable=True)
    #: The merchant's own reference from the QR, echoed for their reconciliation.
    payee_reference = db.Column(db.String(40), nullable=True)

    idempotency_key = db.Column(db.String(64), unique=True, nullable=False, index=True)

    status = db.Column(
        db.String(20), default=QRPaymentState.INITIATED, nullable=False, index=True
    )

    gateway_provider = db.Column(db.String(30), nullable=True)
    gateway_order_id = db.Column(db.String(150), nullable=True, index=True)
    gateway_payment_id = db.Column(
        db.String(150), nullable=True, unique=True, index=True
    )
    gateway_signature = db.Column(db.String(255), nullable=True)

    upi_rrn = db.Column(db.String(50), nullable=True, index=True)
    payer_vpa = db.Column(db.String(128), nullable=True)

    paid_at = db.Column(db.DateTime, nullable=True)
    failure_code = db.Column(db.String(50), nullable=True)
    failure_reason = db.Column(db.String(500), nullable=True)

    def __repr__(self):
        return f"<QRPayment {self.amount} -> {self.payee_vpa} {self.status}>"
