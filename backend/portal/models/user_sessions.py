from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class SessionStatus:
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"

    CHOICES = [ACTIVE, EXPIRED, REVOKED]


class UserSessions(db.Model, TimestampMixin, CRUDMixin):
    """
    One row per issued refresh token. PRD FR-001 rotates the refresh token on
    every use, so a replayed old token lands on a REVOKED row and is refused -
    that is the signal for token theft.
    """

    __tablename__ = 'user_sessions'

    session_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    refresh_token_hash = db.Column(db.String(255), nullable=False, index=True)
    device_uuid = db.Column(db.String(100), nullable=True, index=True)
    device_name = db.Column(db.String(150), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)

    status = db.Column(db.String(20), default=SessionStatus.ACTIVE, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    revoked_reason = db.Column(db.String(255), nullable=True)

    user = db.relationship('Users', back_populates='sessions')

    def __repr__(self):
        return f"<Session {self.user_id} {self.status}>"
