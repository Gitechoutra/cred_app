from portal import db
from portal.models.base import TimestampMixin, CRUDMixin, uuid_pk, uuid_fk


class ScoreCheckStatus:
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'

    CHOICES = [SUCCESS, FAILED]


class CreditScoreChecks(db.Model, TimestampMixin, CRUDMixin):
    """
    One credit score check the user asked for from the Credit Score screen.

    Separate from the score on a credit application: that one is pulled as part
    of a lending decision, this one because the user wants to see their score.
    Both need the user's consent, and each row records when it was given -
    a bureau enquiry without it is not permitted.

    `is_demo` is true for every row the sandbox produced, and for every row a
    provider's test environment produced. The screen shows those as test data,
    so a simulated report is never mistaken for a real one.
    """

    __tablename__ = 'credit_score_checks'
    __table_args__ = (
        db.Index('ix_credit_score_checks_user_created', 'user_id', 'created_on'),
    )

    check_id = uuid_pk()
    user_id = uuid_fk('users.user_id', nullable=False, index=True)

    status = db.Column(db.String(10), nullable=False)
    consent_at = db.Column(db.DateTime, nullable=False)

    #: 300-900. Null when the bureau has no file (see no_history) or on failure.
    score = db.Column(db.Integer, nullable=True)
    no_history = db.Column(db.Boolean, default=False, nullable=False)

    #: SANDBOX or the provider that pulled it (DECENTRO).
    provider = db.Column(db.String(20), nullable=True)
    #: Which bureau answered: EXPERIAN, CRIF, EQUIFAX, or SANDBOX.
    bureau = db.Column(db.String(20), nullable=True)
    bureau_reference = db.Column(db.String(64), nullable=True)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)

    #: Accounts, utilisation, payment history and enquiries, as the bureau
    #: returned them.
    report = db.Column(db.JSON, nullable=True)
    fetched_at = db.Column(db.DateTime, nullable=True)
    error = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f'<CreditScoreCheck {self.user_id} {self.status} {self.score}>'
