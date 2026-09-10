from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class NotificationChannel:
    IN_APP = "IN_APP"
    PUSH = "PUSH"
    SMS = "SMS"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"

    CHOICES = [IN_APP, PUSH, SMS, EMAIL, WHATSAPP]


class NotificationPriority:
    """
    PRD section 14. CRITICAL and HIGH carry regulatory weight - pre-debit
    notices, security alerts and payment confirmations cannot be switched off
    by the user.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    CHOICES = [LOW, MEDIUM, HIGH, CRITICAL]
    NON_SUPPRESSIBLE = [HIGH, CRITICAL]


class NotificationEvent:
    """Trigger vocabulary from the PRD 14.1 matrix."""

    NEW_CARD_LINKED = "NEW_CARD_LINKED"
    TRANSFER_INITIATED = "TRANSFER_INITIATED"
    TRANSFER_SUCCEEDED = "TRANSFER_SUCCEEDED"
    TRANSFER_FAILED = "TRANSFER_FAILED"
    EMI_DUE_T7 = "EMI_DUE_T7"
    EMI_DUE_T1 = "EMI_DUE_T1"
    EMI_PAID = "EMI_PAID"
    AUTOPAY_PREDEBIT = "AUTOPAY_PREDEBIT"
    AUTOPAY_SUCCEEDED = "AUTOPAY_SUCCEEDED"
    AUTOPAY_FAILED = "AUTOPAY_FAILED"
    SUSPICIOUS_LOGIN = "SUSPICIOUS_LOGIN"
    KYC_APPROVED = "KYC_APPROVED"
    KYC_REJECTED = "KYC_REJECTED"
    BANK_VERIFIED = "BANK_VERIFIED"

    CHOICES = [
        NEW_CARD_LINKED, TRANSFER_INITIATED, TRANSFER_SUCCEEDED, TRANSFER_FAILED,
        EMI_DUE_T7, EMI_DUE_T1, EMI_PAID, AUTOPAY_PREDEBIT, AUTOPAY_SUCCEEDED,
        AUTOPAY_FAILED, SUSPICIOUS_LOGIN, KYC_APPROVED, KYC_REJECTED, BANK_VERIFIED,
    ]


class DeliveryStatus:
    QUEUED = "QUEUED"
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"

    CHOICES = [QUEUED, SENT, DELIVERED, FAILED]


class Notifications(db.Model, TimestampMixin, CRUDMixin):
    __tablename__ = 'notifications'
    __table_args__ = (
        db.Index('ix_notif_user_read', 'user_id', 'is_read'),
    )

    notification_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    event = db.Column(db.String(50), nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False)
    priority = db.Column(db.String(20), default=NotificationPriority.MEDIUM)

    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    deep_link = db.Column(db.String(500), nullable=True)

    delivery_status = db.Column(db.String(20), default=DeliveryStatus.QUEUED)
    provider_reference = db.Column(db.String(150), nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    failure_reason = db.Column(db.String(500), nullable=True)

    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime, nullable=True)

    # Free-form context (transfer id, UTR, amount) for rendering and support.
    payload = db.Column(db.Text, nullable=True)

    user = db.relationship('Users', back_populates='notifications')

    def __repr__(self):
        return f"<Notification {self.event} {self.channel}>"


class NotificationPreferences(db.Model, TimestampMixin, CRUDMixin):
    """
    Per-user channel opt-ins.

    These gate LOW and MEDIUM priority messages only. A CRITICAL pre-debit
    notice or a security alert is dispatched regardless, because RBI requires
    it and the user cannot waive that (PRD 14.1).
    """

    __tablename__ = 'notification_preferences'

    preference_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, unique=True)

    in_app_enabled = db.Column(db.Boolean, default=True)
    push_enabled = db.Column(db.Boolean, default=True)
    sms_enabled = db.Column(db.Boolean, default=True)
    email_enabled = db.Column(db.Boolean, default=True)
    whatsapp_enabled = db.Column(db.Boolean, default=False)

    emi_reminders_enabled = db.Column(db.Boolean, default=True)
    marketing_enabled = db.Column(db.Boolean, default=False)

    quiet_hours_start = db.Column(db.String(5), nullable=True)   # "22:00"
    quiet_hours_end = db.Column(db.String(5), nullable=True)     # "07:00"

    user = db.relationship('Users', back_populates='notification_preferences')

    def __repr__(self):
        return f"<NotifPrefs {self.user_id}>"


class NotificationTemplates(db.Model, TimestampMixin, CRUDMixin):
    """
    Templated copy per event and channel, seeded from the PRD 14.1 matrix.

    SMS templates carry a DLT template id because Indian carriers reject
    transactional SMS that is not registered under an approved template.
    """

    __tablename__ = 'notification_templates'
    __table_args__ = (
        db.UniqueConstraint('event', 'channel', name='uq_template_event_channel'),
    )

    template_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    event = db.Column(db.String(50), nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False)
    priority = db.Column(db.String(20), default=NotificationPriority.MEDIUM)

    title_template = db.Column(db.String(200), nullable=True)
    body_template = db.Column(db.Text, nullable=False)
    dlt_template_id = db.Column(db.String(50), nullable=True)

    regulatory_note = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<Template {self.event}/{self.channel}>"
