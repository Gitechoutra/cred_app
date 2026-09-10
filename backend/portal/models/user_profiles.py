from portal import db
from portal.models.base import (
    TimestampMixin, CRUDMixin, uuid_pk, uuid_fk,
)


class UserProfiles(db.Model, TimestampMixin, CRUDMixin):
    """
    Legal identity. PAN and Aadhaar are AES-256-GCM encrypted at rest
    (PRD 17.1 / 8.2) - never store them in the clear, and never log them.
    """

    __tablename__ = 'user_profiles'

    profile_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, unique=True)

    pan_number_enc = db.Column(db.String(512), nullable=True)
    pan_last4 = db.Column(db.String(4), nullable=True)      # safe for UI + search
    aadhaar_last4 = db.Column(db.String(4), nullable=True)

    address_line1 = db.Column(db.String(255), nullable=True)
    address_line2 = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    pincode = db.Column(db.String(10), nullable=True)

    occupation = db.Column(db.String(100), nullable=True)
    annual_income_band = db.Column(db.String(50), nullable=True)

    avatar_path = db.Column(db.String(500), nullable=True)
    currency_preference = db.Column(db.String(3), default='INR')

    user = db.relationship('Users', back_populates='profile')

    def __repr__(self):
        return f"<UserProfile {self.user_id}>"
