from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class SupportSenderRole:
    USER = "USER"
    AGENT = "AGENT"
    SYSTEM = "SYSTEM"

    CHOICES = [USER, AGENT, SYSTEM]


class TicketStatus:
    OPEN = "OPEN"
    #: An agent has picked it up and is working on it.
    IN_PROGRESS = "IN_PROGRESS"
    #: Both still "In progress" to the people involved; they say whose turn it is.
    AWAITING_USER = "AWAITING_USER"
    AWAITING_AGENT = "AWAITING_AGENT"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"

    CHOICES = [OPEN, IN_PROGRESS, AWAITING_USER, AWAITING_AGENT, RESOLVED, CLOSED]
    #: What an agent may set by hand. The AWAITING_* states follow replies.
    AGENT_SETTABLE = [OPEN, IN_PROGRESS, RESOLVED, CLOSED]
    #: The four states the screens show, and which stored states each covers.
    DISPLAY = {
        OPEN: 'Open',
        IN_PROGRESS: 'In progress',
        AWAITING_USER: 'In progress',
        AWAITING_AGENT: 'In progress',
        RESOLVED: 'Resolved',
        CLOSED: 'Closed',
    }


class TicketCategory:
    PAYMENT_ISSUE = "PAYMENT_ISSUE"
    EMI_ISSUE = "EMI_ISSUE"
    CARD_ISSUE = "CARD_ISSUE"
    KYC_ISSUE = "KYC_ISSUE"
    REFUND_STATUS = "REFUND_STATUS"
    OTHER = "OTHER"

    #: Retired with the credit-to-bank transfer feature. Kept in CHOICES so
    #: tickets raised before the pivot still read back as valid rows.
    TRANSFER_ISSUE = "TRANSFER_ISSUE"

    CHOICES = [
        PAYMENT_ISSUE, EMI_ISSUE, CARD_ISSUE,
        KYC_ISSUE, REFUND_STATUS, OTHER, TRANSFER_ISSUE,
    ]


class SupportTickets(db.Model, TimestampMixin, CRUDMixin):
    """
    A dispute or query thread (PRD US-015: an agent looks up a transaction by
    UTR or phone with PII masked).
    """

    __tablename__ = 'support_tickets'

    ticket_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    ticket_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    category = db.Column(db.String(30), default=TicketCategory.OTHER)
    subject = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default=TicketStatus.OPEN, index=True)
    priority = db.Column(db.String(20), default='MEDIUM')

    # Links the thread to whatever it is about, so an agent has one click to
    # the transaction rather than asking the user to repeat the UTR.
    related_entity_type = db.Column(db.String(50), nullable=True)
    related_entity_id = db.Column(db.String(36), nullable=True)

    assigned_agent_id = db.Column(db.String(36), nullable=True, index=True)

    # Escalation to an administrator. An agent cannot decide on money, limits
    # or KYC; escalating puts the ticket in the admin console's queue.
    escalated = db.Column(db.Boolean, default=False, nullable=False, index=True)
    escalated_at = db.Column(db.DateTime, nullable=True)
    escalated_by = db.Column(db.String(36), nullable=True)
    escalation_reason = db.Column(db.String(500), nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolution_notes = db.Column(db.String(1000), nullable=True)

    messages = db.relationship(
        'SupportMessages', back_populates='ticket', lazy='dynamic'
    )

    def __repr__(self):
        return f"<Ticket {self.ticket_number} {self.status}>"


class SupportMessages(db.Model, TimestampMixin, CRUDMixin):
    __tablename__ = 'support_messages'

    message_id = uuid_pk()
    ticket_id = uuid_fk('support_tickets.ticket_id', nullable=False, index=True)

    sender_role = db.Column(db.String(20), nullable=False)
    sender_id = db.Column(db.String(36), nullable=True)
    sender_name = db.Column(db.String(150), nullable=True)

    body = db.Column(db.Text, nullable=False)
    attachment_path = db.Column(db.String(500), nullable=True)

    is_read = db.Column(db.Boolean, default=False)
    #: A note between staff. Never returned to the customer.
    is_internal = db.Column(db.Boolean, default=False, nullable=False)

    ticket = db.relationship('SupportTickets', back_populates='messages')

    def __repr__(self):
        return f"<SupportMessage {self.ticket_id} {self.sender_role}>"
