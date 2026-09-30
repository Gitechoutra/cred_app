"""
The limit CashU records against a linked credit card.

Worked out here from the holder's credit score and monthly salary, and never
taken from the client. A limit the user types is a number nobody has checked,
and utilisation, warnings and every figure built on them inherit it.

The salary and the score are the ones on the user's credit application: the
declared monthly income, and the score the bureau returned for it. Without both
there is no limit to record, and the card is not linked - there is no fallback
to asking the user.
"""

from decimal import Decimal

from portal.helpers.ledger_engine import money
from portal.models.credit_applications import CreditApplications
from portal.models.users import KYCTier

#: Months of salary recorded as the limit, by credit score band.
#: (lowest score in band, salary multiple)
SCORE_BANDS = (
    (750, Decimal('4')),
    (700, Decimal('3')),
    (650, Decimal('2')),
)

#: Below this, a card is not linked at all.
MINIMUM_CREDIT_SCORE = 650


class Reason:
    KYC_INCOMPLETE = 'KYC_INCOMPLETE'
    INCOME_MISSING = 'INCOME_MISSING'
    SCORE_UNAVAILABLE = 'SCORE_UNAVAILABLE'
    SCORE_TOO_LOW = 'SCORE_TOO_LOW'

    MESSAGES = {
        KYC_INCOMPLETE: 'Complete KYC and income details to link your card.',
        INCOME_MISSING: 'Complete KYC and income details to link your card.',
        SCORE_UNAVAILABLE: (
            'We could not get your credit score yet, so a limit for this card '
            'cannot be set. Complete your income details and bureau consent '
            'to link your card.'
        ),
        SCORE_TOO_LOW: (
            f'Cards can be linked with a credit score of '
            f'{MINIMUM_CREDIT_SCORE} or more.'
        ),
    }


def _latest_scored_application(user):
    """The newest application that carries both a salary and a score."""
    return CreditApplications.query.filter(
        CreditApplications.user_id == user.user_id,
        CreditApplications.credit_score.isnot(None),
        CreditApplications.monthly_income > 0,
    ).order_by(CreditApplications.credit_score_fetched_at.desc()).first()


def assess(user) -> dict:
    """
    The limit for a card this user links. Pure: reads, writes nothing.

    Returns {'eligible', 'limit', 'reason', 'message', 'credit_score',
    'monthly_income', 'multiple'}.
    """
    result = {
        'eligible': False, 'limit': None, 'reason': None, 'message': None,
        'credit_score': None, 'monthly_income': None, 'multiple': None,
    }

    def refuse(reason):
        result.update(reason=reason, message=Reason.MESSAGES[reason])
        return result

    if user.kyc_tier == KYCTier.NONE:
        return refuse(Reason.KYC_INCOMPLETE)

    application = _latest_scored_application(user)
    if application is None:
        # Distinguish "never told us their salary" from "no score yet".
        has_income = CreditApplications.query.filter(
            CreditApplications.user_id == user.user_id,
            CreditApplications.monthly_income > 0,
        ).first() is not None
        return refuse(Reason.SCORE_UNAVAILABLE if has_income else Reason.INCOME_MISSING)

    score = application.credit_score
    income = money(application.monthly_income)
    result.update(credit_score=score, monthly_income=income)

    if score < MINIMUM_CREDIT_SCORE:
        return refuse(Reason.SCORE_TOO_LOW)

    multiple = next(m for floor, m in SCORE_BANDS if score >= floor)
    # Down to a round figure, never up.
    limit = money((income * multiple // Decimal('500')) * Decimal('500'))

    result.update(eligible=True, limit=limit, multiple=multiple)
    return result
