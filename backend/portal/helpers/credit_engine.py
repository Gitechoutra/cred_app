"""
portal/helpers/credit_engine.py
===============================
The credit line: application, approval, issuance, spend and settlement.

This module is the only thing in the codebase permitted to change a credit
limit, an available balance or an outstanding amount. Every route delegates
here, and nothing else writes those columns. The reason is concurrency, not
tidiness: deciding whether a spend fits means reading a balance and then writing
it, and two requests that both read before either writes will both be approved.
So every balance-changing operation in here re-reads its account with
SELECT ... FOR UPDATE inside one transaction, and asserts the account's
invariant before committing:

    available_credit + current_outstanding == credit_limit

A client never supplies a limit or a balance. It supplies an amount and an
intent; what that does to the account is computed here from the account's own
state. A request that says "set my available credit to 90,000" has nowhere to
land, because no function here accepts it.

Duplicate protection is a UNIQUE index on credit_transactions.idempotency_key,
and it is load-bearing rather than belt-and-braces. A check-then-insert cannot
close the window between two concurrent taps; the constraint can, so a replay
raises IntegrityError and is answered with the original transaction.

Nothing here ever sees a CVV, a PIN or an OTP, and nothing here stores a full
card number. Issuance generates the four digits the user is shown and the BIN
that identifies the network; the middle digits are never composed, never
persisted and never logged.
"""

import random
import uuid
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from flask import current_app
from sqlalchemy.exc import IntegrityError

from portal import db
from portal.helpers import (
    adapters, audit, error_recorder, ledger_engine, settings, test_cards,
)
from portal.helpers.encryption import decrypt
from portal.helpers.helpers import ErrorCode
from portal.helpers.ledger_engine import money
from portal.helpers.settings import Key
from portal.models.bank_accounts import BankAccounts, PennyDropStatus
from portal.models.base import utcnow
from portal.models.credit_accounts import (
    CreditAccounts, CreditAccountStatus, CreditPurpose,
)
from portal.models.credit_applications import (
    ApplicationStatus, CreditApplications, EmploymentType,
)
from portal.models.credit_statements import CreditStatements, StatementStatus
from portal.models.credit_transactions import (
    BillPaymentMethod, CreditTransactions, CreditTransactionStatus,
    CreditTransactionType,
)
from portal.models.master_transactions import (
    DestType, GatewayProvider, SourceType, TransactionStatus, TransactionType,
)
from portal.models.kyc_verifications import KYCStatus
from portal.models.users import KYCTier

ZERO = Decimal('0.00')


class CreditError(Exception):
    """A refusal the user should see, with a code the client can branch on."""

    def __init__(self, code: str, message: str, recovery: str = None,
                 transaction=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recovery = recovery
        #: The row that records this refusal, when there is one - a declined
        #: purchase or a failed bill payment - so the client can show its
        #: reference rather than an anonymous error.
        self.transaction = transaction


class DuplicateSpend(Exception):
    """
    A replayed idempotency key. Carries the original transaction.

    Not an error: a double-tapped button is the expected cause, and the right
    answer is the first transaction rather than a second charge.
    """

    def __init__(self, transaction):
        super().__init__('Duplicate credit transaction.')
        self.transaction = transaction


# ── Decision rules ─────────────────────────────────────────────────────────

class DecisionReason:
    """
    Machine-readable decision reasons.

    The applicant-facing wording is derived from these rather than stored, so
    the same decision always reads the same way and an operator changing a
    message cannot accidentally change the meaning of past decisions.
    """

    APPROVED = 'APPROVED'
    KYC_INCOMPLETE = 'KYC_INCOMPLETE'
    INCOME_BELOW_FLOOR = 'INCOME_BELOW_FLOOR'
    OBLIGATIONS_TOO_HIGH = 'OBLIGATIONS_TOO_HIGH'
    FULL_KYC_REQUIRED = 'FULL_KYC_REQUIRED'
    MANUAL_DECLINE = 'MANUAL_DECLINE'
    CREDIT_SCORE_TOO_LOW = 'CREDIT_SCORE_TOO_LOW'
    CREDIT_SCORE_UNAVAILABLE = 'CREDIT_SCORE_UNAVAILABLE'

    MESSAGES = {
        APPROVED: 'Your credit line has been approved.',
        KYC_INCOMPLETE: 'Complete your KYC verification before we can decide.',
        INCOME_BELOW_FLOOR: (
            'Based on the income you declared, we cannot offer a credit line '
            'that meets our minimum.'
        ),
        OBLIGATIONS_TOO_HIGH: (
            'Your existing monthly commitments leave too little room for a new '
            'credit line right now.'
        ),
        FULL_KYC_REQUIRED: (
            'Complete full KYC to be considered for a limit this size.'
        ),
        MANUAL_DECLINE: 'We are unable to offer a credit line at this time.',
        CREDIT_SCORE_TOO_LOW: (
            'Your credit score is below what we need for a credit line right '
            'now. Paying existing loans and cards on time raises it.'
        ),
        CREDIT_SCORE_UNAVAILABLE: (
            'We could not get your credit score yet, so your limit has not '
            'been worked out.'
        ),
    }


#: How many months of disposable income - declared salary less existing EMIs -
#: may be extended as a limit, by credit score band. Disposable rather than gross,
#: so an applicant already servicing debt is not offered a limit their cash flow
#: cannot carry; scaled by score, because the score is the evidence of how that
#: applicant has handled credit before.
#:
#: Constants rather than settings, because changing them changes who gets credit
#: and how much - a decision that should arrive as a reviewed commit rather than
#: as an edit in an admin console at 2am.
SCORE_BANDS = (
    # (lowest score in band, income multiple, label)
    (800, Decimal('4'), 'Excellent'),
    (750, Decimal('3'), 'Very good'),
    (700, Decimal('2'), 'Good'),
    (650, Decimal('1'), 'Fair'),
)

#: Below this, no credit line is offered at all.
MINIMUM_CREDIT_SCORE = 650

#: Applicants the bureau has no history on are assessed on salary alone, at the
#: lowest multiple, and capped - new to credit is not a bad score, but it is no
#: evidence either.
NO_HISTORY_MULTIPLE = Decimal('1')

#: Applicants in these categories have no assessable regular income here, and
#: neither does anyone new to credit, so their offer is capped regardless of
#: what they declare.
THIN_FILE_CAP = Decimal('20000.00')
THIN_FILE_EMPLOYMENT = (EmploymentType.STUDENT, EmploymentType.OTHER)


def score_band(score) -> str:
    """The label for a credit score, for people rather than for the rules."""
    if score is None:
        return None
    for floor, _, label in SCORE_BANDS:
        if score >= floor:
            return label
    return 'Poor'


#: Fixed obligations to income ratio: the share of monthly income already going
#: to EMIs. Above this, a lender does not add more debt however good the score
#: is - the applicant's cash flow is already committed.
MAX_FOIR = Decimal('60')


def assess(application: CreditApplications, user) -> dict:
    """
    Work out the eligible limit. Pure: reads, decides, writes nothing.

    The limit comes from two things and nothing else: declared salary net of
    existing EMIs, and the credit score from the bureau. The applicant does not
    name a limit and an administrator does not set one - both used to be
    possible, and both were a way for the number to drift from the evidence.

    Separate from `decide()` so the arithmetic can be tested without a database
    write, and so the same numbers can be shown before anyone commits to them.

    Also returns `breakdown` (every figure the limit was built from) and
    `checks` (each rule, passed or not), so a reviewer can follow the number
    rather than take it on trust.
    """
    income = money(application.monthly_income)
    outflow = money(application.existing_emi_outflow)
    disposable = income - outflow
    foir = money(outflow / income * 100) if income > ZERO else ZERO
    score = application.credit_score
    no_history = bool(application.credit_no_history)
    floor = money(settings.get_decimal(Key.CREDIT_LIMIT_MIN))

    breakdown = {
        'monthly_income': income,
        'existing_emis': outflow,
        'disposable_income': disposable,
        'foir_percent': foir,
        'max_foir_percent': MAX_FOIR,
        'credit_score': score,
        'score_band': score_band(score),
        'no_credit_history': no_history,
        'minimum_score': MINIMUM_CREDIT_SCORE,
        'kyc_tier': user.kyc_tier,
        'minimum_limit': floor,
        'income_multiple': None,
        'base_limit': None,
        'thin_file_cap': None,
        'kyc_cap': None,
        'eligible_limit': None,
    }
    checks = []

    def check(key, label, passed, detail):
        checks.append({'key': key, 'label': label, 'passed': bool(passed), 'detail': detail})
        return passed

    def refuse(reason, score=ZERO):
        return {
            'approved': False, 'reason': reason, 'limit': ZERO, 'score': score,
            'full_kyc_limit': None, 'breakdown': breakdown, 'checks': checks,
        }

    if not check('kyc', 'KYC verified', user.kyc_tier != KYCTier.NONE,
                 f'{user.kyc_tier} tier' if user.kyc_tier != KYCTier.NONE
                 else 'Not verified yet'):
        return refuse(DecisionReason.KYC_INCOMPLETE)

    if not check('foir', f'Existing EMIs within {MAX_FOIR:.0f}% of income',
                 disposable > ZERO and foir <= MAX_FOIR,
                 f'{foir:.1f}% of income already goes to EMIs'):
        return refuse(DecisionReason.OBLIGATIONS_TOO_HIGH)

    affordability = _score(disposable, income)
    thin_file = application.employment_type in THIN_FILE_EMPLOYMENT

    if no_history:
        check('score', 'Credit history', True,
              'New to credit - assessed on income alone, and capped')
        multiple = NO_HISTORY_MULTIPLE
        thin_file = True
    elif score is None:
        check('score', 'Credit score available', False, 'Not fetched from the bureau yet')
        return refuse(DecisionReason.CREDIT_SCORE_UNAVAILABLE, score=affordability)
    elif not check('score', f'Credit score at least {MINIMUM_CREDIT_SCORE}',
                   score >= MINIMUM_CREDIT_SCORE, f'{score} ({score_band(score)})'):
        return refuse(DecisionReason.CREDIT_SCORE_TOO_LOW, score=affordability)
    else:
        multiple = next(m for floor_, m, _ in SCORE_BANDS if score >= floor_)

    offer = money(disposable * multiple)
    breakdown['income_multiple'] = multiple
    breakdown['base_limit'] = offer
    if thin_file:
        breakdown['thin_file_cap'] = THIN_FILE_CAP
        offer = min(offer, THIN_FILE_CAP)

    tier_cap = money(settings.get_decimal(
        Key.CREDIT_LIMIT_MAX_FULL_KYC if user.kyc_tier == KYCTier.FULL
        else Key.CREDIT_LIMIT_MAX_STANDARD_KYC
    ))
    full_kyc_above = money(settings.get_decimal(Key.FULL_KYC_REQUIRED_ABOVE))

    # A limit above the full-KYC threshold needs full KYC. A minimum-KYC
    # applicant who qualifies for more is offered the threshold, and told what
    # full KYC would unlock. This used to decline them outright and rely on an
    # administrator typing in a smaller limit by hand; with limits no longer set
    # by hand, declining would turn away almost every minimum-KYC applicant.
    full_kyc_limit = None
    if user.kyc_tier != KYCTier.FULL and offer > full_kyc_above:
        full_kyc_limit = _round_down_to(
            min(offer, money(settings.get_decimal(Key.CREDIT_LIMIT_MAX_FULL_KYC))),
            Decimal('500'),
        )
        offer = full_kyc_above
        tier_cap = min(tier_cap, full_kyc_above)

    breakdown['kyc_cap'] = tier_cap
    offer = min(offer, tier_cap)

    if not check('floor', f'Limit at least Rs. {floor:,.0f}', offer >= floor,
                 f'Works out to Rs. {offer:,.0f}'):
        return refuse(DecisionReason.INCOME_BELOW_FLOOR, score=affordability)

    # Rounded down to a round number, the way a limit is actually granted. Down,
    # never up: rounding up would hand out credit the rule above did not.
    limit = _round_down_to(offer, Decimal('500'))
    breakdown['eligible_limit'] = limit
    return {
        'approved': True,
        'reason': DecisionReason.APPROVED,
        'limit': limit,
        'score': affordability,
        # What the same application would be eligible for with full KYC, when
        # that is more. None when full KYC would change nothing.
        'full_kyc_limit': full_kyc_limit,
        'breakdown': breakdown,
        'checks': checks,
    }


def _score(disposable: Decimal, income: Decimal) -> Decimal:
    """
    Share of declared income that is not already committed, as a percentage.

    A thin proxy for affordability, and labelled as such: it is recorded so a
    reviewer can see what the automatic decision was looking at, not presented
    as a credit score.
    """
    if income <= ZERO:
        return ZERO
    return money(disposable / income * 100)


def _round_down_to(value: Decimal, step: Decimal) -> Decimal:
    return money((value // step) * step)


# ── Application ────────────────────────────────────────────────────────────

def check_can_apply(*, user, bureau_consent: bool, employment_type: str,
                    employer_name: str = None, bank_account_id: str = None,
                    has_income_proof: bool = False) -> BankAccounts:
    """
    Every refusal an application can meet before it is opened, in the order an
    applicant would want to hear them. Raises CreditError; returns the verified
    bank account the application will carry.

    Separate from `apply()` so a route can run it before saving an uploaded
    document - a refused application must not leave a file behind.
    """
    if not bureau_consent:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            'We need your permission to check your credit score.',
            recovery='Tick the consent box to continue.',
        )

    if _open_application_for(user.user_id):
        raise CreditError(
            ErrorCode.CONFLICT,
            'You already have an application in progress.',
            recovery='Check its status before applying again.',
        )

    if _live_account_for(user.user_id):
        raise CreditError(
            ErrorCode.CONFLICT,
            'You already have an active credit line.',
            recovery='Close it before applying for another.',
        )

    # KYC is part of the application. It may still be in review - the
    # application then waits in KYC_PENDING - but it must have been submitted:
    # the credit score is pulled by the PAN it carries.
    kyc = user.kyc_verification
    if user.kyc_tier == KYCTier.NONE and not (
        kyc and kyc.kyc_status in (KYCStatus.PENDING, KYCStatus.UNDER_REVIEW)
    ):
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            'Submit your KYC - PAN and Aadhaar - as part of your application.',
            recovery='Complete the identity step first.',
        )

    if employment_type in EmploymentType.WITH_EMPLOYER and not employer_name:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            'Enter your employer, or your business name if self-employed.',
        )

    account = None
    if bank_account_id:
        account = BankAccounts.query.filter_by(
            bank_account_id=bank_account_id, user_id=user.user_id,
            deleted_at=None, is_active=True,
        ).first()
    if not account:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            'Choose the bank account your salary is paid into.',
            recovery='Link and verify a bank account first.',
        )
    if account.penny_drop_status != PennyDropStatus.VERIFIED:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            'That bank account is not verified yet. Choose a verified account.',
        )

    if not has_income_proof:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            'Upload a salary slip, bank statement or ITR as proof of income.',
        )

    return account


def apply(*, user, employment_type: str, monthly_income, existing_emi_outflow=0,
          bureau_consent: bool = False, employer_name: str = None,
          designation: str = None, months_in_current_job: int = None,
          income_proof_type: str = None, income_proof_path: str = None,
          bank_account_id: str = None) -> CreditApplications:
    """
    Open a credit application.

    The applicant gives their identity (KYC), employment, income with a proof
    document, the verified bank account their salary lands in, and consent to a
    credit bureau enquiry. They do not name a limit: the eligible limit is
    worked out from salary and credit score, and that is what goes to review.

    Refuses a second open application, and refuses one from a user who already
    holds a live credit line - two live lines is a product decision nobody has
    made, and allowing it here by omission is how it would happen.
    """
    account = check_can_apply(
        user=user, bureau_consent=bureau_consent, employment_type=employment_type,
        employer_name=employer_name, bank_account_id=bank_account_id,
        has_income_proof=bool(income_proof_path),
    )

    application = CreditApplications(
        user_id=user.user_id,
        employment_type=employment_type,
        employer_name=employer_name,
        designation=designation,
        months_in_current_job=months_in_current_job,
        monthly_income=money(monthly_income),
        existing_emi_outflow=money(existing_emi_outflow),
        income_proof_type=income_proof_type,
        income_proof_path=income_proof_path,
        bank_account_id=account.bank_account_id,
        bureau_consent_at=utcnow(),
        submitted_at=utcnow(),
    )

    # KYC decides which queue this lands in. A verified applicant goes straight
    # to review; an unverified one waits, and is told why. Both are visible to
    # administrators - an application waiting on KYC is still an application.
    if user.kyc_tier == KYCTier.NONE:
        application.status = ApplicationStatus.KYC_PENDING
    else:
        application.status = ApplicationStatus.UNDER_REVIEW
        application.kyc_verified_at = utcnow()
        # The score needs the PAN, which only a verified applicant has given.
        _fetch_credit_score(application, user)

    _reassess(application, user)

    db.session.add(application)
    db.session.commit()

    audit.record(
        action='CREDIT_APPLICATION_SUBMITTED',
        entity_type='CreditApplications',
        entity_id=application.application_id,
        actor_user_id=user.user_id,
        after={
            'status': application.status,
            'credit_score': application.credit_score,
            'eligible_limit': float(application.offered_limit or 0),
        },
    )
    return application


def kyc_completed(user) -> CreditApplications:
    """
    Advance a waiting application once KYC is approved.

    Called from the KYC review path rather than polled, so an applicant who was
    blocked on verification moves the moment they are verified rather than on
    their next visit. This is also when the credit score is first fetched: it
    needs the PAN that KYC has just verified.

    Returns the application it advanced, or None.
    """
    application = CreditApplications.query.filter_by(
        user_id=user.user_id, status=ApplicationStatus.KYC_PENDING,
    ).first()
    if not application:
        return None

    application.status = ApplicationStatus.UNDER_REVIEW
    application.kyc_verified_at = utcnow()
    _fetch_credit_score(application, user)
    _reassess(application, user)

    db.session.commit()
    return application


def _reassess(application: CreditApplications, user) -> dict:
    """Store the eligible limit the rules give right now, and return the assessment."""
    assessment = assess(application, user)
    application.offered_limit = assessment['limit'] if assessment['approved'] else None
    application.eligibility_score = assessment['score']
    return assessment


def _fetch_credit_score(application: CreditApplications, user) -> bool:
    """
    Ask the bureau for the applicant's score, and record it.

    Never raises: a bureau that is down leaves the score empty, the application
    stays in review showing that, and approval waits until a score exists. An
    application must not be lost because a third party was unreachable.
    """
    if not application.bureau_consent_at:
        return False

    profile = getattr(user, 'profile', None)
    pan = None
    if profile is not None and profile.pan_number_enc:
        try:
            pan = decrypt(profile.pan_number_enc)
        except Exception:     # noqa: BLE001 - an unreadable PAN is a missing one
            pan = None
    if not pan:
        return False

    result = adapters.fetch_credit_score(
        reference=f'CASHUAPP{(application.application_id or "").replace("-", "")[:16]}',
        pan=pan,
        full_name=user.full_name,
        phone=user.phone,
    )
    if not result.get('ok'):
        current_app.logger.warning(
            f'[credit] credit score unavailable: {result.get("error")}'
        )
        return False

    application.credit_score = result.get('score')
    application.credit_no_history = bool(result.get('no_history'))
    application.credit_score_fetched_at = utcnow()
    application.bureau_reference = (result.get('reference') or '')[:64] or None
    return True


def withdraw(application: CreditApplications) -> CreditApplications:
    """Let an applicant take back an undecided application."""
    if not application.can_transition_to(ApplicationStatus.WITHDRAWN):
        raise CreditError(
            ErrorCode.CONFLICT,
            'This application can no longer be withdrawn.',
        )
    application.status = ApplicationStatus.WITHDRAWN
    application.decided_at = utcnow()
    db.session.commit()
    return application


def decide(application: CreditApplications, *, user, approve: bool,
           note: str = None, actor_id: str = None):
    """
    An administrator approves or rejects an application.

    Approval grants exactly the eligible limit the rules give - worked out from
    salary and credit score, re-checked at this moment. There is no limit to
    type in: an administrator decides *whether*, not *how much*, and cannot
    approve an application the rules say is ineligible. Any application can be
    rejected.

    Returns (application, account). account is None on a rejection.
    """
    if not application.can_transition_to(ApplicationStatus.APPROVED) and \
            not application.can_transition_to(ApplicationStatus.REJECTED):
        raise CreditError(
            ErrorCode.CONFLICT,
            'This application has already been decided.',
        )

    # A score that could not be fetched earlier is tried again now, so a bureau
    # outage at submission does not strand the application.
    if approve and application.credit_score is None and not application.credit_no_history:
        _fetch_credit_score(application, user)

    assessment = _reassess(application, user)

    if approve:
        if application.status != ApplicationStatus.UNDER_REVIEW:
            raise CreditError(
                ErrorCode.CONFLICT,
                'This application is waiting for the applicant to complete KYC.',
            )
        if not assessment['approved']:
            raise CreditError(
                ErrorCode.VALIDATION_ERROR,
                'This application is not eligible for a credit line. '
                + DecisionReason.MESSAGES.get(assessment['reason'], assessment['reason']),
                recovery='Reject it with a reason instead.',
            )
        granted = assessment['limit']
        reason = DecisionReason.APPROVED
    else:
        granted = ZERO
        reason = DecisionReason.MANUAL_DECLINE

    application.decision_reason = reason
    application.decision_note = note
    application.decided_at = utcnow()
    application.decided_by = actor_id

    if not approve:
        application.status = ApplicationStatus.REJECTED
        db.session.commit()
        audit.record(
            action='CREDIT_APPLICATION_REJECTED',
            entity_type='CreditApplications',
            entity_id=application.application_id,
            actor_user_id=application.user_id,
            after={'reason': reason},
        )
        _tell_applicant(user, 'CREDIT_REJECTED', {
            'reason': note or DecisionReason.MESSAGES[reason],
            'deep_link': f'/credit/status/{application.application_id}',
        })
        return application, None

    application.status = ApplicationStatus.APPROVED
    application.approved_limit = granted

    account = _issue(application, user, granted)
    db.session.commit()

    audit.record(
        action='CREDIT_APPLICATION_APPROVED',
        entity_type='CreditApplications',
        entity_id=application.application_id,
        actor_user_id=application.user_id,
        after={
            'approved_limit': float(granted),
            'credit_score': application.credit_score,
            'credit_account_id': account.credit_account_id,
            'decided_by': actor_id,
        },
    )
    _tell_applicant(user, 'CREDIT_APPROVED', {
        'limit': f'{granted:,.0f}',
        'deep_link': f'/credit/status/{application.application_id}',
    })
    return application, account


def _tell_applicant(user, event: str, context: dict) -> None:
    """
    Notify the applicant of a decision. Best effort: the decision is already
    committed, and a notification channel being down must not look like the
    decision failed.
    """
    try:
        from portal.helpers import notify
        notify.dispatch(user, event, context)
    except Exception as exc:     # noqa: BLE001
        db.session.rollback()
        current_app.logger.warning(f'[credit] could not notify {event}: {exc}')


def _issue(application: CreditApplications, user, limit: Decimal) -> CreditAccounts:
    """
    Create the credit account. Not committed here; `decide` owns the commit.

    The card identity generated is only ever a BIN and four digits. No full
    number is composed at any point, so there is none to store, log or leak.
    """
    account = CreditAccounts(
        user_id=user.user_id,
        application_id=application.application_id,
        status=CreditAccountStatus.PENDING_PURPOSE,
        card_bin=_issuing_bin(),
        card_last4=f'{random.randint(0, 9999):04d}',
        card_network='RUPAY',
        name_on_card=(user.full_name or 'CARDHOLDER').upper()[:80],
        expiry_month=f'{utcnow().month:02d}',
        expiry_year=str(utcnow().year + 5),
        credit_limit=limit,
        available_credit=limit,
        current_outstanding=ZERO,
        statement_day=settings.get_int(Key.STATEMENT_CYCLE_DAY),
        grace_days=settings.get_int(Key.STATEMENT_GRACE_DAYS),
    )
    db.session.add(account)
    db.session.flush()
    return account


def _issuing_bin() -> str:
    """
    The issuing BIN.

    A RuPay test range, and only a range: this platform is not a licensed issuer,
    so the BIN identifies the network for display purposes and nothing more.
    """
    return '607469'


# ── Purpose of credit ──────────────────────────────────────────────────────

def declare_purpose(account: CreditAccounts, *, purpose: str,
                    note: str = None) -> CreditAccounts:
    """
    Record what the credit is for, and clear the gate to activation.

    Mandatory: the account is issued in PENDING_PURPOSE and cannot leave it
    until this is called. A note is required for OTHER and refused for
    everything else, so the stored reason always matches the chosen category.
    """
    if account.status != CreditAccountStatus.PENDING_PURPOSE:
        raise CreditError(
            ErrorCode.CONFLICT,
            'The purpose of this credit line has already been recorded.',
        )

    if purpose not in CreditPurpose.CHOICES:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            'Choose what you will use this credit for.',
        )

    cleaned = (note or '').strip()

    if purpose == CreditPurpose.OTHER:
        if len(cleaned) < 3:
            raise CreditError(
                ErrorCode.VALIDATION_ERROR,
                'Tell us what you will use this credit for.',
            )
    elif cleaned:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            'A note only applies when the purpose is "Other".',
        )

    account.purpose = purpose
    account.purpose_note = cleaned[:200] or None
    account.purpose_declared_at = utcnow()
    account.status = CreditAccountStatus.PENDING_ACTIVATION
    db.session.commit()

    audit.record(
        action='CREDIT_PURPOSE_DECLARED',
        entity_type='CreditAccounts',
        entity_id=account.credit_account_id,
        actor_user_id=account.user_id,
        after={'purpose': purpose},
    )
    return account


# ── Activation ─────────────────────────────────────────────────────────────

def activate(account: CreditAccounts) -> CreditAccounts:
    """
    Turn the line on.

    Refuses without a declared purpose. The status machine already prevents it,
    and this says so explicitly because "cannot transition" is not an answer a
    user can act on.
    """
    if account.status == CreditAccountStatus.PENDING_PURPOSE:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            'Tell us what you will use this credit for before activating.',
            recovery='Choose a purpose of credit.',
        )

    if account.status == CreditAccountStatus.ACTIVE:
        return account

    if not account.can_transition_to(CreditAccountStatus.ACTIVE):
        raise CreditError(
            ErrorCode.CONFLICT,
            'This credit line cannot be activated.',
        )

    account.status = CreditAccountStatus.ACTIVE
    account.activated_at = utcnow()
    account.blocked_at = None
    account.block_reason = None
    db.session.commit()

    audit.record(
        action='CREDIT_ACCOUNT_ACTIVATED',
        entity_type='CreditAccounts',
        entity_id=account.credit_account_id,
        actor_user_id=account.user_id,
        after={'status': account.status},
    )
    return account


def block(account: CreditAccounts, *, reason: str,
          actor_id: str = None) -> CreditAccounts:
    """
    Stop the line spending. The balance stays owed, and remains payable.
    """
    if not account.can_transition_to(CreditAccountStatus.BLOCKED):
        raise CreditError(ErrorCode.CONFLICT, 'This credit line cannot be blocked.')

    account.status = CreditAccountStatus.BLOCKED
    account.blocked_at = utcnow()
    account.block_reason = (reason or '')[:200] or None
    db.session.commit()

    audit.record(
        action='CREDIT_ACCOUNT_BLOCKED',
        entity_type='CreditAccounts',
        entity_id=account.credit_account_id,
        actor_user_id=account.user_id,
        after={'reason': account.block_reason, 'by': actor_id or 'USER'},
    )
    return account


# ── Spending ───────────────────────────────────────────────────────────────

def purchase(*, account: CreditAccounts, amount, merchant_name: str,
             merchant_category: str = None, description: str = None,
             idempotency_key: str, is_test: bool = False) -> CreditTransactions:
    """
    Draw on the credit line.

    The whole operation is one database transaction, and the account row is
    re-read under a lock before the limit is examined. That ordering is the
    point: two taps on a 10,000 limit with 6,000 available must not both
    succeed, and only the lock prevents it.

    A replay of `idempotency_key` raises DuplicateSpend carrying the original,
    so the caller answers with the first purchase rather than making a second.
    """
    amount = money(amount)
    if amount <= ZERO:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR, 'Amount must be greater than zero.',
        )

    if is_test and not _test_spend_allowed():
        raise CreditError(
            ErrorCode.FORBIDDEN,
            'Test transactions are not available in this environment.',
        )

    existing = CreditTransactions.query.filter_by(
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        raise DuplicateSpend(existing)

    try:
        with ledger_engine.atomic():
            locked = _lock(account.credit_account_id)

            if not locked.can_spend:
                raise CreditError(
                    ErrorCode.FORBIDDEN,
                    _not_spendable_message(locked.status),
                    recovery=_not_spendable_recovery(locked.status),
                )

            if amount > money(locked.available_credit):
                raise CreditError(
                    'INSUFFICIENT_CREDIT',
                    f'This purchase needs Rs. {amount:,.2f} but only '
                    f'Rs. {money(locked.available_credit):,.2f} of your credit '
                    f'limit is available.',
                    recovery='Pay your outstanding balance to free up credit.',
                )

            _check_velocity(locked, amount)

            outstanding = money(locked.current_outstanding) + amount
            available = money(locked.credit_limit) - outstanding
            _assert_invariant(locked, available, outstanding)

            txn = ledger_engine.post(
                user_id=locked.user_id,
                transaction_type=TransactionType.CREDIT_PURCHASE,
                gross_amount=amount,
                net_amount=amount,
                source_type=SourceType.CREDIT_LINE,
                source_masked_ref=locked.masked_number,
                dest_type=DestType.MERCHANT,
                dest_masked_ref=merchant_name[:150],
                gateway_provider=GatewayProvider.INTERNAL,
                idempotency_key=idempotency_key,
                status=TransactionStatus.SUCCEEDED,
                entries=ledger_engine.entries_for_credit_purchase(
                    amount, locked.masked_number, merchant_name,
                ),
                commit=False,
            )

            locked.current_outstanding = outstanding
            locked.available_credit = available

            record = CreditTransactions(
                credit_account_id=locked.credit_account_id,
                user_id=locked.user_id,
                transaction_id=txn.transaction_id,
                transaction_type=CreditTransactionType.PURCHASE,
                status=CreditTransactionStatus.SUCCEEDED,
                amount=amount,
                balance_after=outstanding,
                available_after=available,
                merchant_name=merchant_name[:120],
                merchant_category=merchant_category,
                description=(description or '')[:200] or None,
                idempotency_key=idempotency_key,
                is_test=is_test,
                settled_at=utcnow(),
            )
            db.session.add(record)
    except CreditError as exc:
        # A decline is a real event on the card, and the holder is entitled to
        # see it in their history with the reason. The atomic block has already
        # rolled back, so this is written in its own transaction; nothing about
        # the balance changed. An invariant failure is ours, not a decline, and
        # is not dressed up as one.
        if exc.code != 'LIMIT_INVARIANT_VIOLATED':
            exc.transaction = _record_decline(
                credit_account_id=account.credit_account_id,
                amount=amount,
                merchant_name=merchant_name,
                merchant_category=merchant_category,
                description=description,
                idempotency_key=idempotency_key,
                is_test=is_test,
                error=exc,
            )
        raise
    except IntegrityError:
        # Two concurrent taps: the loser of the UNIQUE index race. The winner's
        # row is the answer.
        db.session.rollback()
        original = CreditTransactions.query.filter_by(
            idempotency_key=idempotency_key,
        ).first()
        if original:
            raise DuplicateSpend(original)
        raise

    audit.record(
        action='CREDIT_PURCHASE',
        entity_type='CreditTransactions',
        entity_id=record.credit_transaction_id,
        actor_user_id=record.user_id,
        after={
            'amount': float(amount),
            'merchant': record.merchant_name,
            'outstanding': float(record.balance_after),
            'is_test': is_test,
        },
    )
    return record


def _check_velocity(account: CreditAccounts, amount: Decimal):
    """
    Daily and monthly spend caps.

    Summed from the transaction history rather than from a counter row. The
    account is already locked at this point, so the sum cannot move underneath
    the check, and one query is cheaper than the correctness risk of a counter
    that can drift from the rows it is meant to summarise.
    """
    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)

    def spent_since(since):
        total = db.session.query(
            db.func.coalesce(db.func.sum(CreditTransactions.amount), 0)
        ).filter(
            CreditTransactions.credit_account_id == account.credit_account_id,
            CreditTransactions.transaction_type == CreditTransactionType.PURCHASE,
            CreditTransactions.status == CreditTransactionStatus.SUCCEEDED,
            CreditTransactions.created_on >= since,
        ).scalar()
        return money(total)

    daily_cap = money(settings.get_decimal(Key.CREDIT_DAILY_SPEND_LIMIT))
    if spent_since(day_start) + amount > daily_cap:
        raise CreditError(
            'DAILY_LIMIT_EXCEEDED',
            f'This purchase would take you past your daily spend limit of '
            f'Rs. {daily_cap:,.2f}.',
            recovery='Try again tomorrow, or contact support to review the limit.',
        )

    monthly_cap = money(settings.get_decimal(Key.CREDIT_MONTHLY_SPEND_LIMIT))
    if spent_since(month_start) + amount > monthly_cap:
        raise CreditError(
            'MONTHLY_LIMIT_EXCEEDED',
            f'This purchase would take you past your monthly spend limit of '
            f'Rs. {monthly_cap:,.2f}.',
            recovery='The limit resets at the start of next month.',
        )


def _record_decline(*, credit_account_id: str, amount: Decimal,
                    merchant_name: str, merchant_category: str,
                    description: str, idempotency_key: str, is_test: bool,
                    error: CreditError):
    """
    Write a FAILED row for a refused purchase, and return it.

    It consumes the idempotency key on purpose. That key named one attempt, and
    the attempt was declined: replaying it must answer "declined" again rather
    than quietly trying a second time after the holder has paid down their
    balance. A deliberate retry is a new attempt with a new key.

    Never raises. Recording the decline is secondary to reporting it, and a
    failure here must not turn a clear refusal into a 500.
    """
    try:
        account = (
            CreditAccounts.query
            .filter_by(credit_account_id=credit_account_id)
            .populate_existing()
            .first()
        )
        if account is None:
            return None

        record = CreditTransactions(
            credit_account_id=account.credit_account_id,
            user_id=account.user_id,
            transaction_type=CreditTransactionType.PURCHASE,
            status=CreditTransactionStatus.FAILED,
            amount=amount,
            balance_after=money(account.current_outstanding),
            available_after=money(account.available_credit),
            merchant_name=(merchant_name or '')[:120] or None,
            merchant_category=merchant_category,
            description=(description or '')[:200] or None,
            idempotency_key=idempotency_key,
            is_test=is_test,
            failure_code=error.code[:50],
            failure_reason=error.message[:500],
        )
        db.session.add(record)
        db.session.commit()
        return record
    except Exception as exc:     # noqa: BLE001 - see the docstring
        db.session.rollback()
        current_app.logger.warning(
            f'[credit] could not record a declined purchase: {exc}'
        )
        return None


# ── Bill payment ───────────────────────────────────────────────────────────
#
# A bill payment is money arriving from outside, so unlike a purchase it cannot
# be decided here. It runs in two halves:
#
#   open_bill_payment    validates, records a PROCESSING row and opens a gateway
#                        order. Touches no balance.
#   settle_bill_payment  asks the gateway what happened. Only a payment the
#                        gateway itself reports as captured restores credit.
#
# This replaced a single call that restored credit the moment the client said it
# had paid. Nothing checked that it had, so any authenticated request could clear
# its own balance.
#
# Three callers race to settle every payment - the browser returning from
# checkout, the gateway's webhook and the poller - so settling re-reads the row
# under a lock and does nothing if another caller got there first.

#: How long a payment may sit in PROCESSING with nothing collected before it is
#: treated as abandoned. Generous, because a UPI collect request legitimately
#: waits on the payer, and failing one they are about to approve is worse than
#: leaving it open a little long.
BILL_PAYMENT_TIMEOUT = timedelta(minutes=30)

#: Outcomes a development build may ask the simulated gateway for, mapped to the
#: adapters' directives. Ignored unless the rail really is the simulator.
SANDBOX_OUTCOMES = {
    'APPROVE': None,
    'DECLINE': adapters.Simulate.AUTH_DECLINE,
    'ABANDON': adapters.Simulate.ABANDON,
    'TIMEOUT': adapters.Simulate.TIMEOUT,
}

#: Gateway order states that mean the order can no longer be paid.
_DEAD_ORDER_STATES = ('FAILED', 'EXPIRED', 'TERMINATED', 'CANCELLED')

_SOURCE_BY_METHOD = {
    BillPaymentMethod.UPI_INTENT: SourceType.UPI_VPA,
    BillPaymentMethod.UPI_COLLECT: SourceType.UPI_VPA,
    BillPaymentMethod.NETBANKING: SourceType.NETBANKING,
    BillPaymentMethod.DEBIT_CARD: SourceType.DEBIT_CARD,
}


def bill_payment_provider(method: str) -> str:
    """The rail a payment by `method` would be collected on right now."""
    if method in BillPaymentMethod.UPI:
        return adapters.upi_provider()
    return adapters.card_gateway_provider()


def simulator_allowed() -> bool:
    """
    Whether a simulated gateway may settle a bill payment here.

    The simulator reports orders as paid. Behind a bill payment that means credit
    restored for nothing, so it is refused in production however the adapters
    are configured: USE_SANDBOX_ADAPTERS defaults on, and a deployment that
    forgot to turn it off has to fail closed rather than give credit away.
    """
    return current_app.config.get('ENV_NAME', 'development') != 'production'


def open_bill_payment(*, account: CreditAccounts, user, amount, method: str,
                      idempotency_key: str, statement: CreditStatements = None,
                      sandbox_outcome: str = None) -> CreditTransactions:
    """
    Start paying the bill: record the attempt and open a gateway order.

    Refuses more than is outstanding. An overpayment would create a credit
    balance on the line, which this product has no concept of, and taking money
    into an unrepresented state is the worst of the options.

    Refuses a second payment while one is still processing. The idempotency key
    cannot catch that case - a payer who closes the UPI app and taps Pay again
    sends a genuinely new request - and two captured payments against one bill
    would collect it twice.

    The returned row carries a transient `checkout` dict: what the client needs
    to open the gateway's sheet. Never a status - opening an order is not
    collecting money.
    """
    amount = money(amount)
    minimum = money(settings.get_decimal(Key.PAYMENT_MIN_AMOUNT))
    if amount < minimum:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            f'The smallest payment we can collect is Rs. {minimum:,.2f}.',
        )

    if method not in BillPaymentMethod.CHOICES:
        raise CreditError(
            ErrorCode.INSTRUMENT_NOT_PERMITTED,
            'A card bill can be paid by UPI, net banking or a debit card.',
            recovery='Choose UPI, Net Banking or Debit Card.',
        )

    existing = CreditTransactions.query.filter_by(
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        raise DuplicateSpend(existing)

    provider = bill_payment_provider(method)
    if provider == 'SANDBOX' and not simulator_allowed():
        current_app.logger.error(
            '[credit] bill payment refused: the payment rail is the simulator '
            'in a production environment.'
        )
        raise CreditError(
            ErrorCode.PROVIDER_ERROR,
            'Bill payments are temporarily unavailable.',
            recovery='Please try again later.',
        )

    try:
        with ledger_engine.atomic():
            locked = _lock(account.credit_account_id)

            if locked.status == CreditAccountStatus.CLOSED:
                raise CreditError(
                    ErrorCode.CONFLICT, 'This credit line is closed.',
                )

            outstanding = money(locked.current_outstanding)
            if outstanding <= ZERO:
                raise CreditError(
                    ErrorCode.CONFLICT,
                    'There is nothing outstanding on this credit line.',
                )
            # Normally no more than is owed. The exception is a balance smaller
            # than the smallest collectable payment - 0.50 left after a partial
            # payment - which could otherwise never be cleared. Paying the
            # minimum is allowed then, and the few paise over become a credit
            # balance on the card rather than being refused or lost.
            payable = max(outstanding, minimum)
            if amount > payable:
                raise CreditError(
                    ErrorCode.VALIDATION_ERROR,
                    f'You owe Rs. {outstanding:,.2f}. Enter that or less.',
                    recovery=f'Pay the full outstanding of Rs. {outstanding:,.2f}.',
                )

            # A locking read, not a plain one. Under REPEATABLE READ a plain
            # SELECT answers from the snapshot this transaction took at its first
            # read - before the account lock was granted - and would miss a
            # payment another request opened while this one waited for it.
            in_flight = (
                CreditTransactions.query
                .filter_by(
                    credit_account_id=locked.credit_account_id,
                    transaction_type=CreditTransactionType.PAYMENT,
                    status=CreditTransactionStatus.PROCESSING,
                )
                .with_for_update()
                .first()
            )
            if in_flight:
                raise CreditError(
                    ErrorCode.CONFLICT,
                    'A payment on this card is already being processed.',
                    recovery='Wait for it to finish, or cancel it and try again.',
                    transaction=in_flight,
                )

            record = CreditTransactions(
                credit_account_id=locked.credit_account_id,
                user_id=locked.user_id,
                transaction_type=CreditTransactionType.PAYMENT,
                status=CreditTransactionStatus.PROCESSING,
                amount=amount,
                description='Credit card bill payment',
                idempotency_key=idempotency_key,
                payment_method=method,
                target_statement_id=(
                    statement.statement_id if statement is not None else None
                ),
            )
            db.session.add(record)
            db.session.flush()
    except IntegrityError:
        db.session.rollback()
        original = CreditTransactions.query.filter_by(
            idempotency_key=idempotency_key,
        ).first()
        if original:
            raise DuplicateSpend(original)
        raise

    # The gateway is called after the commit, not inside the lock: a network
    # round trip must not hold the account row while a purchase waits on it.
    reference = f'CASHUBILL{record.credit_transaction_id.replace("-", "")[:20].upper()}'
    if provider == 'SANDBOX':
        directive = SANDBOX_OUTCOMES.get((sandbox_outcome or '').upper())
        if directive:
            reference += directive

    collection = dict(
        order_id=reference,
        amount=amount,
        customer_id=str(user.user_id),
        customer_phone=user.phone,
        customer_email=user.email,
        customer_name=user.full_name,
        note='CashU credit card bill',
        tags={
            'credit_transaction_id': record.credit_transaction_id,
            'type': 'CREDIT_BILL_PAYMENT',
        },
    )
    order = (
        adapters.create_upi_order(**collection)
        if method in BillPaymentMethod.UPI
        else adapters.create_payment_order(**collection)
    )

    if not order.get('ok'):
        timed_out = bool(order.get('timeout'))
        _close_unpaid(
            record,
            CreditTransactionStatus.FAILED,
            'GATEWAY_TIMEOUT' if timed_out else (order.get('error_code') or 'GATEWAY_ERROR'),
            (
                'The payment gateway took too long to respond. Nothing was charged.'
                if timed_out else
                'We could not reach the payment gateway. Nothing was charged.'
            ),
            gateway_response=order,
        )
        raise CreditError(
            record.failure_code, record.failure_reason,
            recovery='Please try again in a moment.', transaction=record,
        )

    record.gateway_provider = order.get('provider')
    # Razorpay's own order id is what Checkout, the verify call and the webhook
    # all speak. Everywhere else the merchant reference is the lookup key - and
    # on the simulator it is the thing carrying the requested outcome.
    record.gateway_order_id = (
        order.get('gateway_order_id') if record.gateway_provider == 'RAZORPAY'
        else reference
    )
    db.session.commit()

    audit.record(
        action='CREDIT_BILL_PAYMENT_INITIATED',
        entity_type='CreditTransactions',
        entity_id=record.credit_transaction_id,
        actor_user_id=record.user_id,
        after={
            'amount': float(amount),
            'method': method,
            'provider': record.gateway_provider,
        },
    )

    # Transient: derivable from config and the order, so storing it would only
    # be duplicating state that can go stale.
    record.checkout = {
        'provider': record.gateway_provider,
        'key': order.get('public_key') or None,
        'order_id': (
            record.gateway_order_id if record.gateway_provider == 'RAZORPAY'
            else None
        ),
        'amount_paise': order.get('amount_paise'),
        'currency': 'INR',
        'payment_session_id': order.get('payment_session_id'),
    }
    return record


def settle_bill_payment(record: CreditTransactions, *,
                        gateway_payment_id: str = None,
                        signature: str = None) -> CreditTransactions:
    """
    Ask the gateway what happened to a payment, and act on its answer alone.

    `gateway_payment_id` and `signature` come from the browser when it has them.
    The signature is verified before the id is trusted, and even a verified id
    only selects which payment to read: whether money moved is decided by the
    gateway's API, never by the caller. Safe to call any number of times, from
    anywhere, concurrently.
    """
    locked = _lock_payment(record)
    if locked is None:
        return record
    record = locked

    status = _gateway_status(record, gateway_payment_id, signature)

    if not status.get('ok'):
        # Cannot tell. Leave it for the poller rather than guess in either
        # direction - a guess of "failed" strands money that moved.
        db.session.commit()
        return record

    if status.get('gateway_payment_id'):
        record.gateway_payment_id = str(status['gateway_payment_id'])[:100]

    if status.get('paid'):
        return _apply_bill_payment(record, status)

    if (status.get('status') or '').upper() in _DEAD_ORDER_STATES:
        return _close_unpaid(
            record,
            CreditTransactionStatus.FAILED,
            status.get('failure_code') or 'PAYMENT_FAILED',
            status.get('failure_reason') or 'The payment was declined by your bank.',
            gateway_response=status,
        )

    # Still with the payer. Not a failure, and emphatically not a success.
    db.session.commit()
    return record


def cancel_bill_payment(record: CreditTransactions) -> CreditTransactions:
    """
    Abandon a payment the payer backed out of.

    Never on their say-so alone. Closing the checkout sheet after authorising is
    common, and the debit still lands - so the gateway is asked first, and a
    payment that did go through is settled instead of cancelled.
    """
    return _abandon(
        record,
        CreditTransactionStatus.CANCELLED,
        'USER_CANCELLED',
        'You cancelled this payment. Nothing was charged.',
    )


def poll_processing_bill_payments(limit: int = 100):
    """
    Resolve payments nobody came back for.

    The net under every interruption: a closed tab, a dropped connection, a
    webhook that never arrived. Anything still unpaid after BILL_PAYMENT_TIMEOUT
    with no live attempt at the gateway is closed as timed out.
    """
    now = utcnow()
    rows = CreditTransactions.query.filter(
        CreditTransactions.transaction_type == CreditTransactionType.PAYMENT,
        CreditTransactions.status == CreditTransactionStatus.PROCESSING,
        # Give the browser the first chance: it has the signed payload.
        CreditTransactions.created_on < now - timedelta(minutes=1),
    ).order_by(CreditTransactions.created_on.asc()).limit(limit).all()

    tally = {'settled': 0, 'failed': 0, 'timed_out': 0}
    for row in rows:
        try:
            result = settle_bill_payment(row)
            if (
                result.status == CreditTransactionStatus.PROCESSING
                and result.created_on < now - BILL_PAYMENT_TIMEOUT
            ):
                result = _abandon(
                    result,
                    CreditTransactionStatus.FAILED,
                    'PAYMENT_TIMEOUT',
                    'The payment was not completed in time. Nothing was charged.',
                )
                if result.status == CreditTransactionStatus.FAILED:
                    tally['timed_out'] += 1
            elif result.status == CreditTransactionStatus.SUCCEEDED:
                tally['settled'] += 1
            elif result.status == CreditTransactionStatus.FAILED:
                tally['failed'] += 1
        except Exception as exc:     # noqa: BLE001 - one bad row must not stop the sweep
            db.session.rollback()
            current_app.logger.error(
                f'[credit] bill payment poll failed for '
                f'{row.credit_transaction_id}: {exc}'
            )

    # None on a quiet run, so the scheduler logs it at debug rather than
    # filling the log with zeros.
    return tally if any(tally.values()) else None


def _lock_payment(record: CreditTransactions):
    """
    Re-read a PROCESSING payment under a row lock, or return None.

    None means another caller already resolved it, and the lock has been
    released. populate_existing() for the reason set out in `_lock`.
    """
    locked = (
        CreditTransactions.query
        .filter_by(credit_transaction_id=record.credit_transaction_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if locked is None or locked.status != CreditTransactionStatus.PROCESSING:
        db.session.commit()   # release the lock; nothing to do
        return None
    return locked


def _gateway_status(record: CreditTransactions, gateway_payment_id: str = None,
                    signature: str = None) -> dict:
    """The gateway's authoritative answer for this payment's order."""
    if record.gateway_provider == 'SANDBOX' and not simulator_allowed():
        return {
            'ok': True, 'paid': False, 'status': 'FAILED',
            'failure_code': 'SIMULATOR_REFUSED',
            'failure_reason': 'This payment could not be verified.',
        }

    if record.payment_method in BillPaymentMethod.UPI:
        if gateway_payment_id and signature and not \
                adapters.verify_upi_checkout_signature(
                    order_id=record.gateway_order_id,
                    payment_id=gateway_payment_id,
                    signature=signature,
                ):
            # A correct-looking payload with the wrong signature is a replay or
            # a guess. Drop the id and let the order-level lookup decide.
            current_app.logger.error(
                f'[credit] bad checkout signature for bill payment '
                f'{record.credit_transaction_id}; ignoring the supplied id.'
            )
            gateway_payment_id = None
        return adapters.get_upi_payment_status(
            order_id=record.gateway_order_id, payment_id=gateway_payment_id,
        )

    return adapters.get_payment_status(record.gateway_order_id)


def _apply_bill_payment(record: CreditTransactions,
                        status: dict) -> CreditTransactions:
    """
    The gateway says the money arrived. Restore the credit it frees.

    Same locking discipline as a purchase. The caller holds the payment row's
    lock; this takes the account's, in that order everywhere, so the two cannot
    deadlock against each other.

    The money has already moved, so this cannot refuse. If the balance fell
    while the payment was in flight - a refund landed - the payment still
    counts in full and the balance goes below zero: a credit balance, owed to
    the holder and spent first, as on a real card. It used to be clamped at
    zero and the difference only logged, which quietly kept the holder's money.
    """
    amount = money(record.amount)

    with ledger_engine.atomic():
        account = _lock(record.credit_account_id)

        outstanding_before = money(account.current_outstanding)
        # The part that settles billed debt; anything beyond it is credit.
        applied = max(ZERO, min(amount, outstanding_before))
        outstanding = outstanding_before - amount
        available = money(account.credit_limit) - outstanding
        if available < ZERO:
            # Fees took the balance past the limit; nothing is spendable yet.
            available = ZERO
        else:
            _assert_invariant(account, available, outstanding)

        method_label = BillPaymentMethod.LABELS.get(
            record.payment_method, record.payment_method or 'Payment',
        )
        try:
            txn = ledger_engine.post(
                user_id=account.user_id,
                transaction_type=TransactionType.CREDIT_BILL_PAYMENT,
                gross_amount=amount,
                net_amount=amount,
                source_type=_SOURCE_BY_METHOD.get(
                    record.payment_method, SourceType.UPI_VPA,
                ),
                source_masked_ref=method_label,
                dest_type=DestType.CREDIT_LINE,
                dest_masked_ref=account.masked_number,
                gateway_provider=record.gateway_provider or GatewayProvider.SANDBOX,
                gateway_ref_no=record.gateway_order_id,
                bank_rrn_utr=status.get('rrn'),
                idempotency_key=record.idempotency_key,
                status=TransactionStatus.SUCCEEDED,
                entries=ledger_engine.entries_for_credit_bill_payment(
                    amount, method_label, account.masked_number,
                ),
                commit=False,
            )
            transaction_id = txn.transaction_id
        except ledger_engine.DuplicateTransaction as dup:
            # Posted by an earlier attempt that died before marking the row.
            transaction_id = dup.transaction.transaction_id

        account.current_outstanding = outstanding
        account.available_credit = available

        record.status = CreditTransactionStatus.SUCCEEDED
        record.transaction_id = transaction_id
        record.balance_after = outstanding
        record.available_after = available
        record.gateway_reference = (str(status.get('rrn') or '')[:64]) or None
        record.failure_code = None
        record.failure_reason = None
        record.settled_at = utcnow()

        # Applied to the statement the payer chose if it still owes, otherwise
        # the oldest that does. Oldest first is what stops a payment clearing
        # this month's bill while last month's goes overdue.
        target = None
        if record.target_statement_id:
            target = CreditStatements.query.filter(
                CreditStatements.statement_id == record.target_statement_id,
                CreditStatements.status.in_(StatementStatus.OUTSTANDING),
            ).first()
        target = target or _oldest_outstanding_statement(record.credit_account_id)
        if target is not None and applied > ZERO:
            _apply_to_statement(target, applied)

    audit.record(
        action='CREDIT_BILL_PAYMENT',
        entity_type='CreditTransactions',
        entity_id=record.credit_transaction_id,
        actor_user_id=record.user_id,
        after={
            'amount': float(amount),
            'outstanding_before': float(outstanding_before),
            'outstanding_after': float(outstanding),
            'gateway': record.gateway_provider,
        },
    )
    return record


def _abandon(record: CreditTransactions, final_status: str, code: str,
             reason: str) -> CreditTransactions:
    """
    Close an unpaid payment - but only once the gateway confirms it is unpaid.

    A payment that did go through is settled instead. One whose attempt is still
    live at the bank is left processing: closing it would orphan a debit that
    may yet land.
    """
    locked = _lock_payment(record)
    if locked is None:
        return CreditTransactions.query.filter_by(
            credit_transaction_id=record.credit_transaction_id,
        ).populate_existing().first() or record
    record = locked

    status = _gateway_status(record)

    if not status.get('ok'):
        db.session.commit()
        return record

    if status.get('paid'):
        if status.get('gateway_payment_id'):
            record.gateway_payment_id = str(status['gateway_payment_id'])[:100]
        return _apply_bill_payment(record, status)

    if status.get('gateway_payment_id') and \
            (status.get('status') or '').upper() == 'PENDING':
        db.session.commit()
        return record

    return _close_unpaid(record, final_status, code, reason)


def _close_unpaid(record: CreditTransactions, final_status: str, code: str,
                  reason: str, gateway_response: dict = None):
    """Mark a payment that collected nothing, and log a failure for support."""
    record.status = final_status
    record.failure_code = (code or 'PAYMENT_FAILED')[:50]
    record.failure_reason = (reason or '')[:500]
    db.session.commit()

    if final_status == CreditTransactionStatus.FAILED:
        error_recorder.record(
            user_id=record.user_id,
            code=record.failure_code,
            reason=record.failure_reason,
            reference_type='CreditTransactions',
            reference_id=record.credit_transaction_id,
            payment_method=record.payment_method,
            gateway=record.gateway_provider,
            amount=record.amount,
            transaction_status=record.status,
            gateway_response=gateway_response,
        )

    audit.record(
        action=f'CREDIT_BILL_PAYMENT_{final_status}',
        entity_type='CreditTransactions',
        entity_id=record.credit_transaction_id,
        actor_user_id=record.user_id,
        after={'code': record.failure_code},
    )
    return record


def _oldest_outstanding_statement(credit_account_id: str):
    return CreditStatements.query.filter(
        CreditStatements.credit_account_id == credit_account_id,
        CreditStatements.status.in_(StatementStatus.OUTSTANDING),
    ).order_by(CreditStatements.period_end.asc()).first()


def _apply_to_statement(statement: CreditStatements, amount: Decimal):
    """
    Credit a payment against a statement and re-derive its status.

    Status is computed from the numbers rather than set by the caller, so a
    statement cannot be marked paid by anything other than money arriving.
    """
    statement.amount_paid = money(statement.amount_paid) + amount

    if statement.amount_paid >= money(statement.closing_balance):
        statement.status = StatementStatus.PAID
        statement.fully_paid_at = utcnow()
    elif statement.amount_paid >= money(statement.minimum_due):
        statement.status = StatementStatus.PARTIALLY_PAID
    elif statement.due_date < date.today():
        statement.status = StatementStatus.OVERDUE
    else:
        statement.status = StatementStatus.UNPAID


# ── Statements ─────────────────────────────────────────────────────────────

def cut_statement(account: CreditAccounts, *, as_of: date = None
                  ) -> CreditStatements:
    """
    Close a billing cycle and issue the statement.

    Everything unbilled on the account at this moment is swept into it, and each
    swept transaction is stamped with the statement id - which is what makes
    "unbilled spend" a query rather than a guess.

    Idempotent through the UNIQUE (credit_account_id, period_end) constraint, so
    a scheduler that runs twice issues one statement rather than two.
    """
    as_of = as_of or date.today()
    period_end = as_of
    period_start = _cycle_start(account, as_of)

    existing = CreditStatements.query.filter_by(
        credit_account_id=account.credit_account_id, period_end=period_end,
    ).first()
    if existing:
        return existing

    # REVERSED as well as SUCCEEDED. A fully refunded purchase moves to REVERSED,
    # but it still happened, and its REFUND row is swept in and subtracted. With
    # SUCCEEDED alone the purchase was dropped and the refund still counted, so
    # the statement came out short by the purchase's amount.
    unbilled = CreditTransactions.query.filter(
        CreditTransactions.credit_account_id == account.credit_account_id,
        CreditTransactions.statement_id.is_(None),
        CreditTransactions.status.in_([
            CreditTransactionStatus.SUCCEEDED, CreditTransactionStatus.REVERSED,
        ]),
    ).all()

    purchases = sum(
        (money(t.amount) for t in unbilled
         if t.transaction_type == CreditTransactionType.PURCHASE), ZERO,
    )
    payments = sum(
        (money(t.amount) for t in unbilled
         if t.transaction_type == CreditTransactionType.PAYMENT), ZERO,
    )
    refunds = sum(
        (money(t.amount) for t in unbilled
         if t.transaction_type == CreditTransactionType.REFUND), ZERO,
    )
    fees = sum(
        (money(t.amount) for t in unbilled
         if t.transaction_type == CreditTransactionType.FEE), ZERO,
    )

    fresh = (
        CreditAccounts.query
        .filter_by(credit_account_id=account.credit_account_id)
        .populate_existing()
        .first()
    )

    previous = CreditStatements.query.filter(
        CreditStatements.credit_account_id == account.credit_account_id,
    ).order_by(CreditStatements.period_end.desc()).first()

    # The opening balance is the previous statement's closing balance, in full.
    # Payments made since that statement are among the unbilled rows swept in
    # below, so they are subtracted here exactly once.
    #
    # This used to open at closing *minus amount_paid*. A payment made after a
    # statement is recorded in its amount_paid and is also an unbilled row, so it
    # was subtracted twice: pay an 8,000 bill, spend 5,000, and the next
    # statement read 0.00 due and PAID while the account owed 5,000.
    opening = money(previous.closing_balance) if previous else ZERO

    # Negative means a credit balance - a refund or a payment that crossed with
    # one. It is carried as money owed to the holder, never discarded.
    closing = opening + purchases + fees - payments - refunds

    # Every settled row up to now has been swept in, so the closing balance
    # must be what the account itself says is owed. Checked, not assumed: a
    # disagreement means a balance was written outside this module.
    if closing != money(fresh.current_outstanding):
        current_app.logger.error(
            f'[credit] statement for {account.credit_account_id} closes at '
            f'{closing} but the account owes {fresh.current_outstanding}'
        )

    percent = money(settings.get_decimal(Key.MINIMUM_DUE_PERCENT))
    floor = money(settings.get_decimal(Key.PAYMENT_MIN_AMOUNT))
    if closing <= ZERO:
        minimum = ZERO
    else:
        minimum = money(closing * percent / 100)
        # Anything past due on the statement being carried forward is added to
        # this one's minimum, as on a real card: missing a minimum does not
        # make the next month's minimum smaller.
        if previous is not None and previous.status == StatementStatus.OVERDUE:
            minimum += money(previous.minimum_outstanding)
        # A minimum due below the collectable floor is pointless, so a small
        # balance is simply due in full.
        if closing <= floor or minimum < floor or minimum > closing:
            minimum = closing

    statement = CreditStatements(
        credit_account_id=account.credit_account_id,
        user_id=account.user_id,
        statement_number=f'STMT{uuid.uuid4().hex[:10].upper()}',
        period_start=period_start,
        period_end=period_end,
        statement_date=as_of,
        due_date=as_of + timedelta(days=account.grace_days),
        opening_balance=opening,
        total_purchases=purchases,
        total_payments=payments,
        total_refunds=refunds,
        total_fees=fees,
        closing_balance=closing,
        minimum_due=minimum,
        minimum_due_percent=percent,
        # As the account stood at the close of the cycle. Read fresh, because the
        # instance passed in may have been loaded before the last spend landed.
        credit_limit=money(fresh.credit_limit),
        available_credit=money(fresh.available_credit),
        status=StatementStatus.PAID if closing <= ZERO else StatementStatus.UNPAID,
    )
    if closing <= ZERO:
        statement.fully_paid_at = utcnow()

    try:
        with ledger_engine.atomic():
            db.session.add(statement)
            db.session.flush()
            for transaction in unbilled:
                transaction.statement_id = statement.statement_id
            # Older statements still owing are superseded: their balance is in
            # this one's opening figure, so it is paid - and late-fee'd - here,
            # once, rather than on two statements at the same time.
            CreditStatements.query.filter(
                CreditStatements.credit_account_id == account.credit_account_id,
                CreditStatements.statement_id != statement.statement_id,
                CreditStatements.status.in_(StatementStatus.OUTSTANDING),
            ).update(
                {'status': StatementStatus.CARRIED_FORWARD},
                synchronize_session=False,
            )
    except IntegrityError:
        # Another run cut this cycle first. Its statement is the right answer.
        db.session.rollback()
        return CreditStatements.query.filter_by(
            credit_account_id=account.credit_account_id, period_end=period_end,
        ).first()

    audit.record(
        action='CREDIT_STATEMENT_ISSUED',
        entity_type='CreditStatements',
        entity_id=statement.statement_id,
        actor_user_id=account.user_id,
        after={
            'statement_number': statement.statement_number,
            'closing_balance': float(closing),
            'minimum_due': float(minimum),
            'due_date': statement.due_date.isoformat(),
        },
    )
    return statement


def _cycle_start(account: CreditAccounts, as_of: date) -> date:
    """
    The first day of the cycle ending on `as_of`.

    The previous statement's end plus a day when there is one, so cycles cannot
    overlap or leave a gap. Otherwise the account's own statement day in the
    previous month, clamped to a day that month actually has - a statement day
    of 31 has to mean the 28th in February rather than raising.
    """
    previous = CreditStatements.query.filter(
        CreditStatements.credit_account_id == account.credit_account_id,
    ).order_by(CreditStatements.period_end.desc()).first()

    if previous:
        return previous.period_end + timedelta(days=1)

    month = as_of.month - 1 or 12
    year = as_of.year if as_of.month > 1 else as_of.year - 1
    day = min(account.statement_day, monthrange(year, month)[1])
    return date(year, month, day)


def mark_overdue_and_charge_fees(limit: int = 500) -> dict:
    """
    Take statements past their due date overdue, and charge the late fee once.

    `late_fee_charged_at` is the guard, not a check on the current date: a job
    that runs twice, or a day late, must not charge a second fee for the same
    cycle.
    """
    today = date.today()
    due = CreditStatements.query.filter(
        CreditStatements.due_date < today,
        CreditStatements.status.in_([
            StatementStatus.UNPAID, StatementStatus.OVERDUE,
        ]),
        CreditStatements.late_fee_charged_at.is_(None),
    ).limit(limit).all()

    fee_amount = money(settings.get_decimal(Key.LATE_PAYMENT_FEE))
    charged, marked = 0, 0

    for statement in due:
        # The minimum due being met is what avoids a late fee, not the balance
        # being cleared - that is how a revolving credit product works.
        if money(statement.amount_paid) >= money(statement.minimum_due):
            continue

        statement.status = StatementStatus.OVERDUE
        marked += 1

        if fee_amount <= ZERO:
            db.session.commit()
            continue

        try:
            charge_fee(
                account=statement.account,
                amount=fee_amount,
                description=f'Late payment fee - {statement.statement_number}',
                idempotency_key=f'latefee-{statement.statement_id}',
            )
            statement.late_fee_charged_at = utcnow()
            db.session.commit()
            charged += 1
        except DuplicateSpend:
            # Already charged on an earlier run that failed before stamping.
            statement.late_fee_charged_at = utcnow()
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            current_app.logger.error(
                f'[credit] late fee failed for {statement.statement_id}: {exc}'
            )

    # None rather than a dict of zeros: the scheduler logs a result at info and
    # a no-op at debug, so returning {'marked_overdue': 0} every quiet night
    # would fill the log with nothing happening.
    if not marked and not charged:
        return None
    return {'marked_overdue': marked, 'fees_charged': charged}


def charge_fee(*, account: CreditAccounts, amount, description: str,
               idempotency_key: str) -> CreditTransactions:
    """
    Add a platform charge to the line - a late fee, today.

    A fee increases what is owed and therefore consumes available credit, so it
    goes through the same locked path as a purchase. It is deliberately not
    limit-checked: a fee is owed whether or not there is room for it, and
    refusing to charge it because the line is full would reward being at the
    limit.
    """
    amount = money(amount)
    if amount <= ZERO:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR, 'A fee must be greater than zero.',
        )

    existing = CreditTransactions.query.filter_by(
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        raise DuplicateSpend(existing)

    try:
        with ledger_engine.atomic():
            locked = _lock(account.credit_account_id)

            outstanding = money(locked.current_outstanding) + amount
            # Available credit floors at zero: a fee may take the balance past
            # the limit, and a negative "available" would be a number no screen
            # can show honestly.
            available = money(locked.credit_limit) - outstanding
            if available < ZERO:
                available = ZERO

            txn = ledger_engine.post(
                user_id=locked.user_id,
                transaction_type=TransactionType.CREDIT_LATE_FEE,
                gross_amount=amount,
                net_amount=amount,
                fee_amount=amount,
                source_type=SourceType.CREDIT_LINE,
                source_masked_ref=locked.masked_number,
                dest_type=DestType.CREDIT_LINE,
                dest_masked_ref=locked.masked_number,
                gateway_provider=GatewayProvider.INTERNAL,
                idempotency_key=idempotency_key,
                status=TransactionStatus.SUCCEEDED,
                entries=ledger_engine.entries_for_late_fee(
                    amount, locked.masked_number,
                ),
                commit=False,
            )

            locked.current_outstanding = outstanding
            locked.available_credit = available

            record = CreditTransactions(
                credit_account_id=locked.credit_account_id,
                user_id=locked.user_id,
                transaction_id=txn.transaction_id,
                transaction_type=CreditTransactionType.FEE,
                status=CreditTransactionStatus.SUCCEEDED,
                amount=amount,
                balance_after=outstanding,
                available_after=available,
                description=description[:200],
                idempotency_key=idempotency_key,
                settled_at=utcnow(),
            )
            db.session.add(record)
    except IntegrityError:
        db.session.rollback()
        original = CreditTransactions.query.filter_by(
            idempotency_key=idempotency_key,
        ).first()
        if original:
            raise DuplicateSpend(original)
        raise

    return record


# ── Refunds ────────────────────────────────────────────────────────────────

def refund(*, purchase_txn: CreditTransactions, amount=None,
           idempotency_key: str) -> CreditTransactions:
    """
    Reverse a purchase, in full or in part.

    Written as a compensating row, never as an edit: the purchase may already
    appear on an issued statement, and changing what that statement said is not
    a correction but a falsification. Partial refunds are allowed, and the total
    refunded can never exceed the original.
    """
    if purchase_txn.transaction_type != CreditTransactionType.PURCHASE:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR, 'Only a purchase can be refunded.',
        )
    if purchase_txn.status != CreditTransactionStatus.SUCCEEDED:
        raise CreditError(
            ErrorCode.CONFLICT, 'Only a settled purchase can be refunded.',
        )

    already = money(db.session.query(
        db.func.coalesce(db.func.sum(CreditTransactions.amount), 0)
    ).filter(
        CreditTransactions.reverses_credit_transaction_id
        == purchase_txn.credit_transaction_id,
        CreditTransactions.status == CreditTransactionStatus.SUCCEEDED,
    ).scalar())

    refundable = money(purchase_txn.amount) - already
    amount = money(amount) if amount is not None else refundable

    if amount <= ZERO:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR, 'A refund must be greater than zero.',
        )
    if amount > refundable:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            f'Only Rs. {refundable:,.2f} of this purchase can still be refunded.',
        )

    existing = CreditTransactions.query.filter_by(
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        raise DuplicateSpend(existing)

    try:
        with ledger_engine.atomic():
            locked = _lock(purchase_txn.credit_account_id)

            # Below zero is a credit balance: a refund for something already
            # paid for. It used to be floored at zero, which swallowed the
            # refund - pay a 3,000 bill, get 3,000 refunded, and the holder
            # ended with nothing to show for it.
            outstanding = money(locked.current_outstanding) - amount
            available = money(locked.credit_limit) - outstanding

            txn = ledger_engine.post(
                user_id=locked.user_id,
                transaction_type=TransactionType.CREDIT_REFUND,
                gross_amount=amount,
                net_amount=amount,
                source_type=SourceType.CREDIT_LINE,
                source_masked_ref=purchase_txn.merchant_name or 'MERCHANT',
                dest_type=DestType.CREDIT_LINE,
                dest_masked_ref=locked.masked_number,
                gateway_provider=GatewayProvider.INTERNAL,
                idempotency_key=idempotency_key,
                status=TransactionStatus.SUCCEEDED,
                reverses_transaction_id=purchase_txn.transaction_id,
                entries=ledger_engine.entries_for_credit_refund(
                    amount, purchase_txn.merchant_name or 'MERCHANT',
                    locked.masked_number,
                ),
                commit=False,
            )

            locked.current_outstanding = outstanding
            locked.available_credit = available

            record = CreditTransactions(
                credit_account_id=locked.credit_account_id,
                user_id=locked.user_id,
                transaction_id=txn.transaction_id,
                transaction_type=CreditTransactionType.REFUND,
                status=CreditTransactionStatus.SUCCEEDED,
                amount=amount,
                balance_after=outstanding,
                available_after=available,
                merchant_name=purchase_txn.merchant_name,
                merchant_category=purchase_txn.merchant_category,
                description=f'Refund of {purchase_txn.merchant_name}',
                idempotency_key=idempotency_key,
                reverses_credit_transaction_id=purchase_txn.credit_transaction_id,
                is_test=purchase_txn.is_test,
                settled_at=utcnow(),
            )
            db.session.add(record)

            if amount >= refundable:
                purchase_txn.status = CreditTransactionStatus.REVERSED
    except IntegrityError:
        db.session.rollback()
        original = CreditTransactions.query.filter_by(
            idempotency_key=idempotency_key,
        ).first()
        if original:
            raise DuplicateSpend(original)
        raise

    return record


# ── Pay Bills ──────────────────────────────────────────────────────────────
#
# Credit drawn for a declared bill and paid out to the holder's own verified
# bank account. bill_pay_engine owns the request's lifecycle - eligibility,
# pricing, consent, OTP, the payout and its status - and calls in here only for
# the two steps that move the balance, because this module is the only thing
# permitted to.
#
#   draw_for_bill_pay     takes bill + fee + GST off available credit, under the
#                         same lock, limit check and velocity caps as a purchase
#   restore_bill_pay      gives the whole draw back when the payout fails or the
#                         bank returns it

def draw_for_bill_pay(*, account: CreditAccounts, bill_amount, fee, gst,
                      merchant_category: str, description: str, bank_ref: str,
                      idempotency_key: str):
    """
    Draw the credit line for a Pay Bills request.

    Returns (credit_transaction, master_transaction). The master row is left
    PROCESSING: the draw is certain, the payout is not, and History must not
    call it complete until the payout is confirmed.

    Counted as a PURCHASE on the line, so the daily and monthly spend caps and
    the statement treat it exactly like any other use of the credit. The total
    - fee and GST included - is what is checked against available credit.
    """
    bill_amount, fee, gst = money(bill_amount), money(fee), money(gst)
    total = bill_amount + fee + gst
    if bill_amount <= ZERO:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR, 'Amount must be greater than zero.',
        )

    existing = CreditTransactions.query.filter_by(
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        raise DuplicateSpend(existing)

    try:
        with ledger_engine.atomic():
            locked = _lock(account.credit_account_id)

            if not locked.can_spend:
                raise CreditError(
                    ErrorCode.FORBIDDEN,
                    _not_spendable_message(locked.status),
                    recovery=_not_spendable_recovery(locked.status),
                )

            if total > money(locked.available_credit):
                raise CreditError(
                    'INSUFFICIENT_CREDIT',
                    f'This payment needs Rs. {total:,.2f} including fees, but only '
                    f'Rs. {money(locked.available_credit):,.2f} of your credit '
                    f'limit is available.',
                    recovery='Enter a smaller amount, or pay your card bill to '
                             'free up credit.',
                )

            _check_velocity(locked, total)

            outstanding = money(locked.current_outstanding) + total
            available = money(locked.credit_limit) - outstanding
            _assert_invariant(locked, available, outstanding)

            txn = ledger_engine.post(
                user_id=locked.user_id,
                transaction_type=TransactionType.CREDIT_BILL_PAY,
                gross_amount=total,
                net_amount=bill_amount,
                fee_amount=fee,
                tax_amount=gst,
                source_type=SourceType.CREDIT_LINE,
                source_masked_ref=locked.masked_number,
                dest_type=DestType.BANK_ACCOUNT_IMPS,
                dest_masked_ref=bank_ref[:150],
                gateway_provider=GatewayProvider.SANDBOX,
                idempotency_key=idempotency_key,
                status=TransactionStatus.PROCESSING,
                entries=ledger_engine.entries_for_bill_pay_draw(
                    bill_amount, fee, gst, locked.masked_number, bank_ref,
                ),
                commit=False,
            )

            locked.current_outstanding = outstanding
            locked.available_credit = available

            record = CreditTransactions(
                credit_account_id=locked.credit_account_id,
                user_id=locked.user_id,
                transaction_id=txn.transaction_id,
                transaction_type=CreditTransactionType.PURCHASE,
                status=CreditTransactionStatus.SUCCEEDED,
                amount=total,
                balance_after=outstanding,
                available_after=available,
                merchant_name=f'Pay Bills · {bank_ref}'[:120],
                merchant_category=merchant_category,
                description=(description or '')[:200] or None,
                idempotency_key=idempotency_key,
                settled_at=utcnow(),
            )
            db.session.add(record)
    except IntegrityError:
        db.session.rollback()
        original = CreditTransactions.query.filter_by(
            idempotency_key=idempotency_key,
        ).first()
        if original:
            raise DuplicateSpend(original)
        raise

    audit.record(
        action='CREDIT_BILL_PAY_DRAW',
        entity_type='CreditTransactions',
        entity_id=record.credit_transaction_id,
        actor_user_id=record.user_id,
        after={
            'bill_amount': float(bill_amount),
            'fee': float(fee),
            'gst': float(gst),
            'total': float(total),
            'destination': bank_ref,
            'outstanding': float(record.balance_after),
        },
    )
    return record, txn


def restore_bill_pay(*, draw: CreditTransactions, reason: str, code: str,
                     returned: bool, idempotency_key: str) -> CreditTransactions:
    """
    Give a Pay Bills draw back to the credit line, in full.

    `returned` distinguishes the two ways it happens. False: the payout never
    completed, so the draw is marked FAILED in History. True: it completed and
    the bank sent it back, so it is marked REVERSED. Either way the fee and GST
    are restored with the bill - the holder is not charged for a payment that
    did not reach them.

    Idempotent: a second call for the same draw returns the first restoring row.
    The poller and a manual status check can both arrive here.
    """
    if draw.status == CreditTransactionStatus.REVERSED:
        existing = CreditTransactions.query.filter_by(
            reverses_credit_transaction_id=draw.credit_transaction_id,
            transaction_type=CreditTransactionType.REFUND,
        ).first()
        if existing:
            return existing

    master = None
    if draw.transaction_id:
        from portal.models.master_transactions import MasterTransactions
        master = MasterTransactions.query.filter_by(
            transaction_id=draw.transaction_id,
        ).first()

    amount = money(draw.amount)

    try:
        with ledger_engine.atomic():
            locked = _lock(draw.credit_account_id)

            outstanding = money(locked.current_outstanding) - amount
            available = money(locked.credit_limit) - outstanding

            reversal = None
            if master is not None:
                reversal = ledger_engine.reverse(
                    master, reason=reason, idempotency_key=idempotency_key,
                    commit=False,
                )
                reversal.status = TransactionStatus.SUCCEEDED
                # reverse() marks the original REVERSED. A payout that never
                # completed did not reverse anything - it failed - and History
                # should say so, with the reason.
                master.status = (
                    TransactionStatus.REVERSED if returned else TransactionStatus.FAILED
                )
                master.failure_code = code[:50]
                master.failure_reason = reason[:500]

            locked.current_outstanding = outstanding
            locked.available_credit = available

            record = CreditTransactions(
                credit_account_id=locked.credit_account_id,
                user_id=locked.user_id,
                transaction_id=reversal.transaction_id if reversal else None,
                transaction_type=CreditTransactionType.REFUND,
                status=CreditTransactionStatus.SUCCEEDED,
                amount=amount,
                balance_after=outstanding,
                available_after=available,
                merchant_name=draw.merchant_name,
                merchant_category=draw.merchant_category,
                description=(
                    'Pay Bills returned by bank' if returned
                    else 'Pay Bills payout failed - credit restored'
                ),
                idempotency_key=idempotency_key,
                reverses_credit_transaction_id=draw.credit_transaction_id,
                settled_at=utcnow(),
            )
            db.session.add(record)
            draw.status = CreditTransactionStatus.REVERSED
    except IntegrityError:
        db.session.rollback()
        original = CreditTransactions.query.filter_by(
            idempotency_key=idempotency_key,
        ).first()
        if original:
            return original
        raise

    audit.record(
        action='CREDIT_BILL_PAY_RESTORE',
        entity_type='CreditTransactions',
        entity_id=record.credit_transaction_id,
        actor_user_id=record.user_id,
        after={
            'restored': float(amount),
            'returned_by_bank': returned,
            'reason': reason,
            'outstanding': float(record.balance_after),
        },
    )
    return record


# ── Internals ──────────────────────────────────────────────────────────────

def _lock(credit_account_id: str) -> CreditAccounts:
    """
    Re-read the account with a row lock, and use the values that read returned.

    Every balance decision goes through this. Reading the account from the
    caller's earlier query and then writing it is the concurrency bug this whole
    module is arranged to avoid.

    populate_existing() is not optional here, and its absence is not a
    theoretical risk. Every caller has already loaded this account through an
    ordinary query - the route fetches it to check ownership - so the instance is
    in the session's identity map. Without populate_existing, SQLAlchemy issues
    the SELECT ... FOR UPDATE, takes the lock, and then *discards the row it
    read* in favour of the attributes already loaded. The lock is held and the
    arithmetic is done on a stale balance, which is the lost update the lock was
    taken to prevent.

    Measured, not assumed: five concurrent purchases of Rs. 100 against a
    balance of 1,500 all returned success and all wrote 1,600. Four of the five
    were silently lost, and the account's invariant still held afterwards - which
    is why tests/credit_concurrency.py asserts that each transaction recorded a
    *distinct* running balance rather than only that the totals add up.
    """
    account = (
        CreditAccounts.query
        .filter_by(credit_account_id=credit_account_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if account is None:
        raise CreditError(ErrorCode.NOT_FOUND, 'Credit line not found.')
    return account


def _assert_invariant(account: CreditAccounts, available: Decimal,
                      outstanding: Decimal):
    """
    Refuse to write balances that do not add up to the limit.

    The invariant is checked rather than trusted because every caller computes
    these two numbers itself, and an arithmetic slip in any of them would
    otherwise persist as a wrong balance that no later read could detect.
    """
    if money(available + outstanding) != money(account.credit_limit):
        raise CreditError(
            'LIMIT_INVARIANT_VIOLATED',
            'We could not complete that safely. Nothing has been charged.',
            recovery='Please try again.',
        )


def _not_spendable_message(status: str) -> str:
    return {
        CreditAccountStatus.PENDING_PURPOSE:
            'Tell us what you will use this credit for before spending.',
        CreditAccountStatus.PENDING_ACTIVATION:
            'Activate your credit line before spending.',
        CreditAccountStatus.BLOCKED:
            'This credit line is blocked.',
        CreditAccountStatus.CLOSED:
            'This credit line is closed.',
    }.get(status, 'This credit line cannot be used right now.')


def _not_spendable_recovery(status: str) -> str:
    return {
        CreditAccountStatus.PENDING_PURPOSE: 'Choose a purpose of credit.',
        CreditAccountStatus.PENDING_ACTIVATION: 'Activate your card.',
        CreditAccountStatus.BLOCKED: 'Unblock it from your card settings.',
    }.get(status)


def _open_application_for(user_id: str):
    return CreditApplications.query.filter(
        CreditApplications.user_id == user_id,
        CreditApplications.status.notin_(ApplicationStatus.TERMINAL),
    ).first()


def _live_account_for(user_id: str):
    return CreditAccounts.query.filter(
        CreditAccounts.user_id == user_id,
        CreditAccounts.status != CreditAccountStatus.CLOSED,
    ).first()


def account_for(user_id: str):
    """The user's live credit line, or None."""
    return _live_account_for(user_id)


def application_for(user_id: str):
    """The user's open application, or None."""
    return _open_application_for(user_id)


def _test_spend_allowed() -> bool:
    """
    Whether a test transaction may be recorded at all.

    Delegates to test_cards.enabled() rather than re-deriving the rule. That
    function already refuses in production, refuses outside the sandbox adapters
    and honours an explicit off switch; a second, subtly different gate here is
    how one of them ends up weaker than the other.
    """
    return test_cards.enabled()
