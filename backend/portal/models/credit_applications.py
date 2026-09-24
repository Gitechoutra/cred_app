from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class ApplicationStatus:
    """
    The application state machine.

    Linear by design. An application does not go back to SUBMITTED once a human
    has looked at it, and an APPROVED application is not re-decided - a change
    of mind after approval is a limit change on the issued account, which is a
    separate, audited action.
    """

    DRAFT = 'DRAFT'
    #: Submitted by the applicant, waiting on KYC before anyone reviews it.
    KYC_PENDING = 'KYC_PENDING'
    #: KYC is verified; queued for a decision.
    UNDER_REVIEW = 'UNDER_REVIEW'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'
    #: Withdrawn by the applicant before a decision.
    WITHDRAWN = 'WITHDRAWN'

    CHOICES = [DRAFT, KYC_PENDING, UNDER_REVIEW, APPROVED, REJECTED, WITHDRAWN]
    TERMINAL = [APPROVED, REJECTED, WITHDRAWN]

    #: Which transitions are legal. Enforced in the engine, not just documented:
    #: a status set by an out-of-order request is how an unreviewed application
    #: ends up with a credit line.
    ALLOWED = {
        DRAFT: [KYC_PENDING, UNDER_REVIEW, WITHDRAWN],
        KYC_PENDING: [UNDER_REVIEW, REJECTED, WITHDRAWN],
        UNDER_REVIEW: [APPROVED, REJECTED, WITHDRAWN],
        APPROVED: [],
        REJECTED: [],
        WITHDRAWN: [],
    }


class EmploymentType:
    SALARIED = 'SALARIED'
    SELF_EMPLOYED = 'SELF_EMPLOYED'
    STUDENT = 'STUDENT'
    RETIRED = 'RETIRED'
    OTHER = 'OTHER'

    CHOICES = [SALARIED, SELF_EMPLOYED, STUDENT, RETIRED, OTHER]


class CreditApplications(db.Model, TimestampMixin, CRUDMixin):
    """
    One request for a credit line.

    Kept separate from the account it may produce, because most of what matters
    here is the evidence behind a decision: what the applicant declared, what
    the backend computed from it, who decided, and why. That record has to
    survive unchanged even if the account is later closed.

    A user may apply more than once - after a rejection, or for a higher limit -
    so this is a history, not a single row per user. The partial uniqueness that
    actually matters (one *open* application at a time) is enforced in the
    engine, because MySQL has no partial unique index.
    """

    __tablename__ = 'credit_applications'
    __table_args__ = (
        db.Index('ix_credit_app_user_status', 'user_id', 'status'),
    )

    application_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    status = db.Column(
        db.String(20), default=ApplicationStatus.DRAFT, nullable=False, index=True
    )

    # -- What the applicant declared --------------------------------------
    # Self-declared and treated as such. The limit decision bounds itself by
    # these numbers but never trusts them as verified income.
    employment_type = db.Column(db.String(20), nullable=False)
    monthly_income = db.Column(db.Numeric(12, 2), nullable=False)
    existing_emi_outflow = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    requested_limit = db.Column(db.Numeric(12, 2), nullable=True)

    # -- What the backend decided -----------------------------------------
    # Computed server-side, always. A client-supplied limit is a request, never
    # the outcome.
    approved_limit = db.Column(db.Numeric(12, 2), nullable=True)
    #: The offer the engine computed, kept even when an admin overrides it, so
    #: an override is visible as an override.
    offered_limit = db.Column(db.Numeric(12, 2), nullable=True)
    eligibility_score = db.Column(db.Numeric(5, 2), nullable=True)
    #: Machine-readable reason, from a fixed vocabulary. The message shown to
    #: the applicant is derived from this rather than stored free-text, so the
    #: same reason always reads the same way.
    decision_reason = db.Column(db.String(50), nullable=True)
    decision_note = db.Column(db.String(500), nullable=True)

    kyc_verified_at = db.Column(db.DateTime, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    #: Null for an automatic decision. Set when a human decided or overrode.
    decided_by = db.Column(db.String(36), nullable=True)

    user = db.relationship('Users', backref=db.backref(
        'credit_applications', lazy='dynamic',
    ))

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in ApplicationStatus.ALLOWED.get(self.status, [])

    @property
    def is_open(self) -> bool:
        return self.status not in ApplicationStatus.TERMINAL

    def __repr__(self):
        return f'<CreditApplication {self.application_id} {self.status}>'
