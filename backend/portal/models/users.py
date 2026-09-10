from portal import db
from portal.models.base import (
    TimestampMixin, CRUDMixin, uuid_pk, UUIDColumn,
)


class UserStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    PENDING = "PENDING"
    FROZEN = "FROZEN"          # admin freeze on suspicious velocity (PRD 16.1)
    BANNED = "BANNED"

    CHOICES = [ACTIVE, SUSPENDED, PENDING, FROZEN, BANNED]


class KYCTier:
    """
    PRD section 18: Minimum KYC (mobile + PAN) is enough to onboard; Full KYC
    (Aadhaar eKYC / Video KYC) is required before credit-to-bank transfers
    above 10,000 INR.
    """

    NONE = "NONE"
    MINIMUM = "MINIMUM"
    FULL = "FULL"

    CHOICES = [NONE, MINIMUM, FULL]


class Users(db.Model, TimestampMixin, CRUDMixin):
    __tablename__ = 'users'

    user_id = uuid_pk()
    role_id = db.Column(db.Integer, db.ForeignKey('roles.role_id'), nullable=False)

    # Mobile-first identity - PRD FR-001. No password anywhere in this model.
    phone = db.Column(db.String(15), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=True, index=True)
    full_name = db.Column(db.String(200), nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)

    mpin_hash = db.Column(db.String(255), nullable=True)
    kyc_tier = db.Column(db.String(20), default=KYCTier.NONE, nullable=False)

    is_phone_verified = db.Column(db.Boolean, default=False)
    is_email_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(20), default=UserStatus.PENDING, nullable=False)

    biometric_enabled = db.Column(db.Boolean, default=False)

    # Auth lockout - PRD FR-001: 3 failed attempts locks auth for 30 minutes.
    failed_auth_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    # Transactions freeze after a registered-phone change (PRD FR-012).
    transactions_frozen_until = db.Column(db.DateTime, nullable=True)

    terms_accepted = db.Column(db.Boolean, default=False)
    terms_accepted_at = db.Column(db.DateTime, nullable=True)

    last_login = db.Column(db.DateTime, nullable=True)

    # Relationships
    role = db.relationship('Roles', back_populates='users')
    profile = db.relationship('UserProfiles', back_populates='user', uselist=False)
    security_settings = db.relationship('UserSecuritySettings', back_populates='user', uselist=False)
    kyc_verification = db.relationship(
        'KYCVerifications', back_populates='user', uselist=False,
        foreign_keys='KYCVerifications.user_id',
    )
    sessions = db.relationship('UserSessions', back_populates='user', lazy='dynamic')
    devices = db.relationship('DeviceBindings', back_populates='user', lazy='dynamic')
    otp_verifications = db.relationship('OTPVerifications', back_populates='user', lazy='dynamic')
    login_history = db.relationship('LoginHistory', back_populates='user', lazy='dynamic')
    cards = db.relationship('Cards', back_populates='user', lazy='dynamic')
    bank_accounts = db.relationship('BankAccounts', back_populates='user', lazy='dynamic')
    transfers = db.relationship('Transfers', back_populates='user', lazy='dynamic')
    emi_obligations = db.relationship('EMIObligations', back_populates='user', lazy='dynamic')
    mandates = db.relationship('AutoPayMandates', back_populates='user', lazy='dynamic')
    transactions = db.relationship('MasterTransactions', back_populates='user', lazy='dynamic')
    notifications = db.relationship('Notifications', back_populates='user', lazy='dynamic')
    notification_preferences = db.relationship(
        'NotificationPreferences', back_populates='user', uselist=False
    )

    def __repr__(self):
        return f"<User {self.phone}>"

    @property
    def is_admin(self) -> bool:
        from portal.models.roles import RoleTypes
        return self.role is not None and self.role.role_name in RoleTypes.ADMIN_ROLES

    def masked_phone(self) -> str:
        if not self.phone or len(self.phone) < 4:
            return "******"
        return f"{'*' * (len(self.phone) - 4)}{self.phone[-4:]}"
