from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class TransferStatus:
    """
    PRD section 9.3 state machine.

        INITIATED -> RISK_CHECKED -+-> RISK_FAILED
                                   +-> AUTH_PENDING -> INBOUND_CHARGED
                                          -+-> SUCCEEDED
                                           +-> PAYOUT_PROCESSING -+-> SUCCEEDED
                                                                  +-> REVERSAL_INIT
                                                                        -> REVERSED_TO_CARD
    """

    INITIATED = "INITIATED"
    RISK_CHECKED = "RISK_CHECKED"
    RISK_FAILED = "RISK_FAILED"
    AUTH_PENDING = "AUTH_PENDING"
    INBOUND_CHARGED = "INBOUND_CHARGED"
    PAYOUT_PROCESSING = "PAYOUT_PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    PENDING_RECONCILIATION = "PENDING_RECONCILIATION"
    REVERSAL_INIT = "REVERSAL_INIT"
    REVERSED_TO_CARD = "REVERSED_TO_CARD"
    FAILED = "FAILED"

    CHOICES = [
        INITIATED, RISK_CHECKED, RISK_FAILED, AUTH_PENDING, INBOUND_CHARGED,
        PAYOUT_PROCESSING, SUCCEEDED, PENDING_RECONCILIATION,
        REVERSAL_INIT, REVERSED_TO_CARD, FAILED,
    ]

    TERMINAL = [RISK_FAILED, SUCCEEDED, REVERSED_TO_CARD, FAILED]

    #: Legal next states. transfer_engine refuses any transition not listed
    #: here, so a webhook arriving out of order cannot walk a transfer
    #: backwards into a chargeable state.
    ALLOWED = {
        INITIATED: [RISK_CHECKED, RISK_FAILED, FAILED],
        RISK_CHECKED: [AUTH_PENDING, RISK_FAILED, FAILED],
        RISK_FAILED: [],
        AUTH_PENDING: [INBOUND_CHARGED, FAILED],
        INBOUND_CHARGED: [SUCCEEDED, PAYOUT_PROCESSING, PENDING_RECONCILIATION],
        PAYOUT_PROCESSING: [SUCCEEDED, REVERSAL_INIT, PENDING_RECONCILIATION],
        PENDING_RECONCILIATION: [SUCCEEDED, REVERSAL_INIT, FAILED],
        REVERSAL_INIT: [REVERSED_TO_CARD, PENDING_RECONCILIATION],
        REVERSED_TO_CARD: [],
        SUCCEEDED: [],
        FAILED: [],
    }


class Transfers(db.Model, TimestampMixin, CRUDMixin):
    """
    Credit-facility to bank transfer (PRD FR-006, section 9).

    Regulatory note: this is the platform's highest-risk feature. RBI's Credit
    Card Master Direction prohibits disguised P2P cash cycling, so every
    transfer must route through an approved merchant category and land only in
    an account the sender has been penny-drop verified to own.
    """

    __tablename__ = 'transfers'
    __table_args__ = (
        db.Index('ix_transfers_user_created', 'user_id', 'created_on'),
    )

    transfer_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)
    card_id = uuid_fk('cards.card_id', nullable=False, index=True)
    bank_account_id = uuid_fk('bank_accounts.bank_account_id', nullable=False, index=True)

    transaction_id = db.Column(db.String(36), nullable=True, index=True)

    # -- Money (PRD 9.2) ---------------------------------------------------
    principal_amount = db.Column(db.Numeric(12, 2), nullable=False)
    convenience_fee = db.Column(db.Numeric(12, 2), nullable=False)
    gst_on_fee = db.Column(db.Numeric(12, 2), nullable=False)
    total_charged_to_card = db.Column(db.Numeric(12, 2), nullable=False)
    net_payout_amount = db.Column(db.Numeric(12, 2), nullable=False)
    fee_percentage_applied = db.Column(db.Numeric(5, 2), nullable=False)

    source_opening_balance = db.Column(db.Numeric(12, 2), nullable=True)
    source_closing_balance = db.Column(db.Numeric(12, 2), nullable=True)
    destination_opening_balance = db.Column(db.Numeric(12, 2), nullable=True)
    destination_closing_balance = db.Column(db.Numeric(12, 2), nullable=True)

    idempotency_key = db.Column(db.String(64), unique=True, nullable=False, index=True)

    status = db.Column(
        db.String(30), default=TransferStatus.INITIATED, nullable=False, index=True
    )

    # -- Gateway (inbound card charge) ------------------------------------
    # What actually paid, as the gateway reports it: 'card', 'upi',
    # 'netbanking'. The card stays selected on every transfer - it is the
    # instrument the limit and the risk check are assessed against - but during
    # testing the charge itself may be settled by UPI, and the credit line must
    # not be consumed for money that came out of a bank account.
    source_instrument = db.Column(db.String(20), nullable=True)
    source_vpa = db.Column(db.String(120), nullable=True)

    gateway_provider = db.Column(db.String(30), nullable=True)
    gateway_order_id = db.Column(db.String(150), nullable=True, index=True)
    gateway_payment_id = db.Column(db.String(150), nullable=True)
    gateway_signature = db.Column(db.String(512), nullable=True)
    three_ds_url = db.Column(db.String(1000), nullable=True)
    charged_at = db.Column(db.DateTime, nullable=True)

    # -- Payout (outbound IMPS) -------------------------------------------
    payout_provider = db.Column(db.String(30), nullable=True)
    payout_reference = db.Column(db.String(150), nullable=True, index=True)
    bank_rrn_utr = db.Column(db.String(50), nullable=True, index=True)
    payout_dispatched_at = db.Column(db.DateTime, nullable=True)
    payout_completed_at = db.Column(db.DateTime, nullable=True)
    payout_retry_count = db.Column(db.Integer, default=0)
    next_retry_at = db.Column(db.DateTime, nullable=True)

    # -- Reversal (PRD 9.4 circuit breaker) -------------------------------
    reversal_reference = db.Column(db.String(150), nullable=True)
    reversed_at = db.Column(db.DateTime, nullable=True)

    # -- Risk (PRD 16.1) ---------------------------------------------------
    risk_score = db.Column(db.Numeric(5, 2), nullable=True)
    risk_decision = db.Column(db.String(30), nullable=True)
    risk_reason = db.Column(db.String(500), nullable=True)

    failure_code = db.Column(db.String(50), nullable=True)
    failure_reason = db.Column(db.String(500), nullable=True)

    device_uuid = db.Column(db.String(100), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)

    user = db.relationship('Users', back_populates='transfers')
    card = db.relationship('Cards', back_populates='transfers')
    bank_account = db.relationship('BankAccounts', back_populates='transfers')

    def __repr__(self):
        return f"<Transfer {self.transfer_id} {self.principal_amount} {self.status}>"

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in TransferStatus.ALLOWED.get(self.status, [])
