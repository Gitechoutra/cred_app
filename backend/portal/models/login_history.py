from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class LoginStatus:
    SUCCESS = "SUCCESS"
    FAILED_OTP = "FAILED_OTP"
    FAILED_MPIN = "FAILED_MPIN"
    LOCKED = "LOCKED"
    DEVICE_MISMATCH = "DEVICE_MISMATCH"

    CHOICES = [SUCCESS, FAILED_OTP, FAILED_MPIN, LOCKED, DEVICE_MISMATCH]


class LoginHistory(db.Model, TimestampMixin, CRUDMixin):
    __tablename__ = 'login_history'

    login_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=True, index=True)

    phone = db.Column(db.String(15), nullable=True, index=True)
    status = db.Column(db.String(30), nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    device_uuid = db.Column(db.String(100), nullable=True)
    location = db.Column(db.String(150), nullable=True)
    failure_reason = db.Column(db.String(255), nullable=True)

    user = db.relationship('Users', back_populates='login_history')

    def __repr__(self):
        return f"<Login {self.phone} {self.status}>"
