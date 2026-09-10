from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class PennyDropVerifications(db.Model, TimestampMixin, CRUDMixin):
    """
    Audit trail of every 1 INR verification attempt (PRD FR-005).

    Kept separate from bank_accounts because an account may be re-verified -
    on re-KYC, after a name change, or when a mismatch is manually cleared -
    and each attempt is evidence a compliance officer may need to review.
    """

    __tablename__ = 'penny_drop_verifications'

    verification_id = uuid_pk()
    bank_account_id = uuid_fk('bank_accounts.bank_account_id', nullable=False, index=True)
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    provider = db.Column(db.String(50), nullable=True)      # CASHFREE | SANDBOX
    provider_reference = db.Column(db.String(150), nullable=True)
    amount = db.Column(db.Numeric(12, 2), default=1.00)
    imps_utr = db.Column(db.String(50), nullable=True)

    cbs_name_returned = db.Column(db.String(200), nullable=True)
    kyc_name_compared = db.Column(db.String(200), nullable=True)
    # Jaro-Winkler / Levenshtein composite, per PRD FR-005.
    similarity_score = db.Column(db.Numeric(5, 2), nullable=True)

    result = db.Column(db.String(30), nullable=False)
    failure_reason = db.Column(db.String(500), nullable=True)
    raw_response = db.Column(db.Text, nullable=True)        # sanitized

    def __repr__(self):
        return f"<PennyDrop {self.bank_account_id} {self.result}>"
