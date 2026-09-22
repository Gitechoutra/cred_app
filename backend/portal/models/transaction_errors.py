from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class ErrorType:
    """
    What kind of thing went wrong, as opposed to which code came back.

    The type is what drives the advice: everything in INSTRUMENT is worth
    retrying with a different card, everything in TRANSIENT is worth retrying
    with the same one, and nothing in LIMIT is worth retrying at all until
    something changes. Grouping by type is also what makes the admin view
    useful - twenty rows of "card declined" from twenty issuers is one story,
    not twenty.
    """

    INSTRUMENT = 'INSTRUMENT'        # the card or account itself
    INSUFFICIENT = 'INSUFFICIENT'    # not enough limit or balance
    AUTHENTICATION = 'AUTHENTICATION'  # 3DS, OTP, PIN
    LIMIT = 'LIMIT'                  # our own or the issuer's ceilings
    GATEWAY = 'GATEWAY'              # the provider failed or timed out
    NETWORK = 'NETWORK'              # could not reach the provider
    VERIFICATION = 'VERIFICATION'    # we could not confirm what happened
    DUPLICATE = 'DUPLICATE'          # already done
    CANCELLED = 'CANCELLED'          # the user backed out
    COMPLIANCE = 'COMPLIANCE'        # KYC, risk, prohibited instrument
    INTERNAL = 'INTERNAL'            # our fault
    UNKNOWN = 'UNKNOWN'              # unmapped provider response

    CHOICES = [
        INSTRUMENT, INSUFFICIENT, AUTHENTICATION, LIMIT, GATEWAY, NETWORK,
        VERIFICATION, DUPLICATE, CANCELLED, COMPLIANCE, INTERNAL, UNKNOWN,
    ]


class TransactionErrors(db.Model, TimestampMixin, CRUDMixin):
    """
    One recorded failure, with enough detail to explain it to the person it
    happened to and enough to debug it afterwards - and nothing more.

    Deliberately *not* append-only. Unlike the ledger this holds no financial
    truth; it is a diagnostic record, and support needs to be able to mark one
    resolved. The money record for a failed payment lives in `transfers` or
    `emi_payments`, which are unchanged by anything here.

    On what is stored: `gateway_response` is the provider's own payload after
    sanitisation, kept because a support agent cannot diagnose an acquirer
    error from a friendly summary. It never holds a PAN, CVV, PIN, OTP or
    token - see helpers/error_catalog.sanitize_gateway_payload, which strips
    those keys and redacts anything shaped like a card number regardless of
    which key it arrived under.
    """

    __tablename__ = 'transaction_errors'
    __table_args__ = (
        db.Index('ix_txnerr_user_created', 'user_id', 'created_on'),
        db.Index('ix_txnerr_type_created', 'error_type', 'created_on'),
    )

    error_id = uuid_pk()

    # The money row this describes. Not a foreign key: a failure can happen
    # before any transaction row exists - a declined authorisation never
    # reaches the ledger - and the record is more useful than the constraint.
    transaction_id = db.Column(db.String(36), nullable=True, index=True)
    reference_type = db.Column(db.String(30), nullable=True)   # Transfers, EMIPayments
    reference_id = db.Column(db.String(36), nullable=True, index=True)

    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    error_code = db.Column(db.String(50), nullable=False, index=True)
    error_type = db.Column(db.String(30), nullable=False, index=True)

    # Two different audiences, deliberately two columns. `error_message` is
    # what the user is shown; `error_reason` is the technical cause a support
    # agent needs. Collapsing them produces either a cryptic user message or a
    # useless agent one.
    error_message = db.Column(db.String(300), nullable=False)
    error_reason = db.Column(db.String(500), nullable=True)

    payment_method = db.Column(db.String(30), nullable=True)
    gateway = db.Column(db.String(30), nullable=True)
    amount = db.Column(db.Numeric(12, 2), nullable=True)
    transaction_status = db.Column(db.String(30), nullable=True)

    #: Sanitised provider payload. JSON-encoded text rather than a JSON column
    #: so the schema works identically on MySQL 5.7 and MariaDB.
    gateway_response = db.Column(db.Text, nullable=True)

    is_retryable = db.Column(db.Boolean, default=True)

    # Support workflow.
    is_resolved = db.Column(db.Boolean, default=False, index=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.String(36), nullable=True)
    resolution_notes = db.Column(db.String(1000), nullable=True)

    #: Set when the user escalates from the chatbot, so an agent opening the
    #: ticket lands on the failure rather than hunting for it.
    support_ticket_id = db.Column(db.String(36), nullable=True, index=True)

    def __repr__(self):
        return f"<TransactionError {self.error_code} {self.error_type}>"
