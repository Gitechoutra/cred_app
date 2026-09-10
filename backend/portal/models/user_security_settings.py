from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class UserSecuritySettings(db.Model, TimestampMixin, CRUDMixin):
    """PRD FR-012 - biometrics, MPIN policy, session kill switch."""

    __tablename__ = 'user_security_settings'

    setting_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, unique=True)

    biometric_enabled = db.Column(db.Boolean, default=False)
    mpin_set = db.Column(db.Boolean, default=False)
    mpin_last_changed = db.Column(db.DateTime, nullable=True)

    two_factor_enabled = db.Column(db.Boolean, default=True)
    login_alerts_enabled = db.Column(db.Boolean, default=True)

    # Kill switch: bumping this invalidates every session issued before it.
    sessions_invalidated_at = db.Column(db.DateTime, nullable=True)

    # DPDPA 2023 rights (PRD FR-012).
    data_export_requested_at = db.Column(db.DateTime, nullable=True)
    erasure_requested_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('Users', back_populates='security_settings')

    def __repr__(self):
        return f"<SecuritySettings {self.user_id}>"
