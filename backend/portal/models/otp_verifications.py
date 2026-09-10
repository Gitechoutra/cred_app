from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class OTPPurpose:
    LOGIN = "LOGIN"
    REGISTRATION = "REGISTRATION"
    TRANSACTION = "TRANSACTION"
    MANDATE_AFA = "MANDATE_AFA"
    PHONE_CHANGE = "PHONE_CHANGE"
    MPIN_RESET = "MPIN_RESET"

    CHOICES = [LOGIN, REGISTRATION, TRANSACTION, MANDATE_AFA, PHONE_CHANGE, MPIN_RESET]


class OTPStatus:
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"

    CHOICES = [PENDING, VERIFIED, EXPIRED, FAILED]


class OTPVerifications(db.Model, TimestampMixin, CRUDMixin):
    """
    PRD FR-001: 6-digit OTP, 3-minute lifetime, verified against a
    cryptographic hash - the plaintext code is never stored.

    The PRD puts this in Redis with a 180s TTL. We hold it in MySQL with an
    explicit expires_at and let the otp_janitor job sweep expired rows; the
    security property (hashed, time-bounded, single-use) is identical.
    """

    __tablename__ = 'otp_verifications'

    otp_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=True, index=True)

    phone = db.Column(db.String(15), nullable=False, index=True)
    otp_hash = db.Column(db.String(255), nullable=False)
    purpose = db.Column(db.String(30), default=OTPPurpose.LOGIN, nullable=False)
    status = db.Column(db.String(20), default=OTPStatus.PENDING, nullable=False)

    attempts = db.Column(db.Integer, default=0)
    max_attempts = db.Column(db.Integer, default=3)

    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    verified_at = db.Column(db.DateTime, nullable=True)

    request_ip = db.Column(db.String(45), nullable=True)
    device_uuid = db.Column(db.String(100), nullable=True)

    user = db.relationship('Users', back_populates='otp_verifications')

    def __repr__(self):
        return f"<OTP {self.phone} {self.purpose} {self.status}>"
