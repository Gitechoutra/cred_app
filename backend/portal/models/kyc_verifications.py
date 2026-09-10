from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class KYCStatus:
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"

    CHOICES = [NOT_STARTED, PENDING, UNDER_REVIEW, APPROVED, REJECTED, EXPIRED]


class DocumentType:
    PAN = "PAN"
    AADHAAR = "AADHAAR"
    PASSPORT = "PASSPORT"
    DRIVING_LICENSE = "DRIVING_LICENSE"
    VOTER_ID = "VOTER_ID"

    CHOICES = [PAN, AADHAAR, PASSPORT, DRIVING_LICENSE, VOTER_ID]


class KYCVerifications(db.Model, TimestampMixin, CRUDMixin):
    """
    PRD FR-012 and section 18. Two tiers: MINIMUM (mobile plus PAN) unlocks the
    app; FULL (Aadhaar eKYC) is required before credit-to-bank transfers above
    10,000 INR.
    """

    __tablename__ = 'kyc_verifications'

    kyc_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, unique=True)

    kyc_status = db.Column(db.String(20), default=KYCStatus.NOT_STARTED, nullable=False)
    requested_tier = db.Column(db.String(20), nullable=True)

    pan_document_path = db.Column(db.String(500), nullable=True)
    aadhaar_document_path = db.Column(db.String(500), nullable=True)
    selfie_path = db.Column(db.String(500), nullable=True)

    # Name as returned by the verification provider. This is the string the
    # penny-drop name match in FR-005 compares the bank CBS name against.
    verified_legal_name = db.Column(db.String(200), nullable=True)
    provider_reference = db.Column(db.String(150), nullable=True)

    submitted_at = db.Column(db.DateTime, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.String(36), nullable=True)
    rejection_reason = db.Column(db.String(500), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship(
        'Users', back_populates='kyc_verification', foreign_keys=[user_id]
    )

    def __repr__(self):
        return f"<KYC {self.user_id} {self.kyc_status}>"
