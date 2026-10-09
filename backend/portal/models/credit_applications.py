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


class BureauStatus:
    """
    Where the credit bureau check stands. Derived from the stored result (see
    CreditApplications.bureau_status), never stored on its own, so it cannot
    disagree with the score it describes.
    """

    #: Not asked yet - the bureau is queried by PAN once KYC is verified.
    PENDING = 'PENDING'
    #: The bureau returned a score, 300-900.
    SCORED = 'SCORED'
    #: The bureau has no file on the person (NH / NA / No Hit): new to credit.
    #: Not a score, and never converted into one.
    NO_HISTORY = 'NO_HISTORY'
    #: The bureau was asked and gave no usable answer: down, not connected, or
    #: a response that was neither a score nor a no-history code.
    UNAVAILABLE = 'UNAVAILABLE'

    LABELS = {
        PENDING: 'Credit check pending',
        SCORED: 'Credit score received',
        NO_HISTORY: 'New to Credit / No Credit History',
        UNAVAILABLE: 'Credit score unavailable',
    }


class EmploymentType:
    SALARIED = 'SALARIED'
    SELF_EMPLOYED = 'SELF_EMPLOYED'
    STUDENT = 'STUDENT'
    RETIRED = 'RETIRED'
    OTHER = 'OTHER'

    CHOICES = [SALARIED, SELF_EMPLOYED, STUDENT, RETIRED, OTHER]
    #: Those who must name an employer or business.
    WITH_EMPLOYER = [SALARIED, SELF_EMPLOYED]


class IncomeProofType:
    SALARY_SLIP = 'SALARY_SLIP'
    BANK_STATEMENT = 'BANK_STATEMENT'
    ITR = 'ITR'

    CHOICES = [SALARY_SLIP, BANK_STATEMENT, ITR]
    LABELS = {
        SALARY_SLIP: 'Latest salary slip',
        BANK_STATEMENT: 'Bank statement (3 months)',
        ITR: 'Income tax return',
    }


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

    # -- Employment -------------------------------------------------------
    #: Employer, or the business name for the self-employed. Required for both;
    #: optional for students, retirees and "other", who have no employer.
    employer_name = db.Column(db.String(150), nullable=True)
    designation = db.Column(db.String(100), nullable=True)
    #: How long in the current job or business. Stability is evidence a
    #: reviewer weighs; it does not move the eligible limit by itself.
    months_in_current_job = db.Column(db.Integer, nullable=True)

    # -- Income evidence --------------------------------------------------
    #: SALARY_SLIP, BANK_STATEMENT or ITR. The declared income is what the
    #: limit is computed from; this is what a reviewer checks it against.
    income_proof_type = db.Column(db.String(20), nullable=True)
    #: Relative to UPLOAD_FOLDER. Never served statically - only through the
    #: audited admin document route.
    income_proof_path = db.Column(db.String(500), nullable=True)

    # -- Bank -------------------------------------------------------------
    #: The applicant's own account, penny-drop verified against their KYC
    #: name at the time of applying. It is where their salary lands and where
    #: repayments come from; the credit line itself is never paid out to it.
    bank_account_id = uuid_fk('bank_accounts.bank_account_id', nullable=True)

    # -- From the credit bureau -------------------------------------------
    #: The CIBIL-style score, 300-900. Null until fetched, and also null when
    #: the bureau has no file on the applicant (see credit_no_history).
    credit_score = db.Column(db.Integer, nullable=True)
    #: The bureau has no credit history for this person - new to credit, which
    #: is assessed differently from a low score rather than as one.
    credit_no_history = db.Column(db.Boolean, default=False, nullable=False)
    credit_score_fetched_at = db.Column(db.DateTime, nullable=True)
    bureau_reference = db.Column(db.String(64), nullable=True)
    #: Who answered: SANDBOX, or the provider (DECENTRO) that pulled it.
    bureau_provider = db.Column(db.String(20), nullable=True)
    #: Which bureau the score is from: EXPERIAN, CRIF, EQUIFAX, or SANDBOX.
    #: Scores from different bureaus are different numbers for the same person.
    bureau_name = db.Column(db.String(20), nullable=True)
    #: Not a real person's real file - the sandbox, or a provider's test
    #: environment. Labelled as test data wherever it is shown.
    bureau_is_test = db.Column(db.Boolean, default=False, nullable=False,
                               server_default=db.false())
    #: The bureau's own no-history code (NH, NA), kept as returned.
    bureau_code = db.Column(db.String(20), nullable=True)
    #: Why the last enquiry produced nothing usable. Cleared by a good answer.
    bureau_error = db.Column(db.String(255), nullable=True)
    #: When the applicant agreed to the bureau enquiry. A report is never pulled
    #: without it.
    bureau_consent_at = db.Column(db.DateTime, nullable=True)

    # -- What the backend decided -----------------------------------------
    # Computed server-side, always. A client-supplied limit is a request, never
    # the outcome.
    approved_limit = db.Column(db.Numeric(12, 2), nullable=True)
    #: The eligible limit the rules give from income and the bureau result.
    #: Not a decision: only an administrator's approval grants a limit.
    offered_limit = db.Column(db.Numeric(12, 2), nullable=True)
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
    bank_account = db.relationship('BankAccounts', foreign_keys=[bank_account_id])

    def can_transition_to(self, new_status: str) -> bool:
        return new_status in ApplicationStatus.ALLOWED.get(self.status, [])

    @property
    def bureau_status(self) -> str:
        if self.credit_score is not None:
            return BureauStatus.SCORED
        if self.credit_no_history:
            return BureauStatus.NO_HISTORY
        if self.bureau_error:
            return BureauStatus.UNAVAILABLE
        return BureauStatus.PENDING

    @property
    def is_open(self) -> bool:
        return self.status not in ApplicationStatus.TERMINAL

    def __repr__(self):
        return f'<CreditApplication {self.application_id} {self.status}>'
