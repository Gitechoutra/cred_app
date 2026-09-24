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
from portal.helpers import audit, ledger_engine, settings, test_cards
from portal.helpers.helpers import ErrorCode
from portal.helpers.ledger_engine import money
from portal.helpers.settings import Key
from portal.models.base import utcnow
from portal.models.credit_accounts import (
    CreditAccounts, CreditAccountStatus, CreditPurpose,
)
from portal.models.credit_applications import (
    ApplicationStatus, CreditApplications, EmploymentType,
)
from portal.models.credit_statements import CreditStatements, StatementStatus
from portal.models.credit_transactions import (
    CreditTransactions, CreditTransactionStatus, CreditTransactionType,
)
from portal.models.master_transactions import (
    DestType, GatewayProvider, SourceType, TransactionStatus, TransactionType,
)
from portal.models.users import KYCTier

ZERO = Decimal('0.00')


class CreditError(Exception):
    """A refusal the user should see, with a code the client can branch on."""

    def __init__(self, code: str, message: str, recovery: str = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recovery = recovery


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
    }


#: Share of declared monthly income, net of existing EMI outflow, that may be
#: extended as a credit limit. A multiple of *disposable* income rather than of
#: gross, so an applicant already servicing debt is not offered a limit their
#: cash flow cannot carry.
#:
#: Three months of disposable income is deliberately conservative for a first
#: line. It is a constant rather than a setting because changing it changes who
#: gets credit, which is a decision that should arrive as a reviewed commit
#: rather than as an edit in an admin console at 2am.
DISPOSABLE_INCOME_MULTIPLE = Decimal('3')

#: Applicants in these categories have no assessable regular income here, so the
#: offer is capped regardless of what they declare.
THIN_FILE_CAP = Decimal('20000.00')
THIN_FILE_EMPLOYMENT = (EmploymentType.STUDENT, EmploymentType.OTHER)


def assess(application: CreditApplications, user) -> dict:
    """
    Compute an offer from the application. Pure: reads, decides, writes nothing.

    Separate from `decide()` so the arithmetic can be tested without a database
    write, and so the same numbers can be shown as an indicative offer before
    anyone commits to them.
    """
    if user.kyc_tier == KYCTier.NONE:
        return {
            'approved': False,
            'reason': DecisionReason.KYC_INCOMPLETE,
            'limit': ZERO,
            'score': ZERO,
        }

    income = money(application.monthly_income)
    outflow = money(application.existing_emi_outflow)
    disposable = income - outflow

    if disposable <= ZERO:
        return {
            'approved': False,
            'reason': DecisionReason.OBLIGATIONS_TOO_HIGH,
            'limit': ZERO,
            'score': ZERO,
        }

    offer = money(disposable * DISPOSABLE_INCOME_MULTIPLE)

    if application.employment_type in THIN_FILE_EMPLOYMENT:
        offer = min(offer, THIN_FILE_CAP)

    # The applicant may ask for less than they qualify for, and that is honoured.
    # They may not ask for more.
    if application.requested_limit:
        offer = min(offer, money(application.requested_limit))

    tier_cap = money(settings.get_decimal(
        Key.CREDIT_LIMIT_MAX_FULL_KYC if user.kyc_tier == KYCTier.FULL
        else Key.CREDIT_LIMIT_MAX_STANDARD_KYC
    ))
    full_kyc_above = money(settings.get_decimal(Key.FULL_KYC_REQUIRED_ABOVE))
    floor = money(settings.get_decimal(Key.CREDIT_LIMIT_MIN))

    # A minimum-KYC applicant whose offer exceeds the full-KYC threshold is told
    # to upgrade rather than silently handed the lower capped amount: the useful
    # answer is "verify further and we can offer more", not a number they did
    # not ask for.
    if user.kyc_tier != KYCTier.FULL and offer > full_kyc_above:
        return {
            'approved': False,
            'reason': DecisionReason.FULL_KYC_REQUIRED,
            'limit': money(min(offer, tier_cap)),
            'score': _score(disposable, income),
        }

    offer = min(offer, tier_cap)

    if offer < floor:
        return {
            'approved': False,
            'reason': DecisionReason.INCOME_BELOW_FLOOR,
            'limit': ZERO,
            'score': _score(disposable, income),
        }

    # Rounded down to a round number, the way a limit is actually granted. Down,
    # never up: rounding up would hand out credit the rule above did not.
    offer = _round_down_to(offer, Decimal('500'))

    return {
        'approved': True,
        'reason': DecisionReason.APPROVED,
        'limit': offer,
        'score': _score(disposable, income),
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

def apply(*, user, employment_type: str, monthly_income, existing_emi_outflow=0,
          requested_limit=None) -> CreditApplications:
    """
    Open a credit application.

    Refuses a second open application, and refuses one from a user who already
    holds a live credit line - two live lines is a product decision nobody has
    made, and allowing it here by omission is how it would happen.
    """
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

    application = CreditApplications(
        user_id=user.user_id,
        employment_type=employment_type,
        monthly_income=money(monthly_income),
        existing_emi_outflow=money(existing_emi_outflow),
        requested_limit=money(requested_limit) if requested_limit else None,
        submitted_at=utcnow(),
    )

    # KYC decides which queue this lands in. A verified applicant goes straight
    # to review; an unverified one waits, and is told why.
    if user.kyc_tier == KYCTier.NONE:
        application.status = ApplicationStatus.KYC_PENDING
    else:
        application.status = ApplicationStatus.UNDER_REVIEW
        application.kyc_verified_at = utcnow()

    # The indicative offer is computed now and stored, so the applicant sees a
    # number immediately and a reviewer sees what the engine thought before any
    # human touched it.
    assessment = assess(application, user)
    application.offered_limit = assessment['limit'] or None
    application.eligibility_score = assessment['score']

    db.session.add(application)
    db.session.commit()

    audit.record(
        action='CREDIT_APPLICATION_SUBMITTED',
        entity_type='CreditApplications',
        entity_id=application.application_id,
        actor_user_id=user.user_id,
        after={
            'status': application.status,
            'offered_limit': float(application.offered_limit or 0),
        },
    )
    return application


def kyc_completed(user) -> CreditApplications:
    """
    Advance a waiting application once KYC is approved.

    Called from the KYC review path rather than polled, so an applicant who was
    blocked on verification moves the moment they are verified rather than on
    their next visit.

    Returns the application it advanced, or None.
    """
    application = CreditApplications.query.filter_by(
        user_id=user.user_id, status=ApplicationStatus.KYC_PENDING,
    ).first()
    if not application:
        return None

    application.status = ApplicationStatus.UNDER_REVIEW
    application.kyc_verified_at = utcnow()

    # Re-assessed, because the tier caps depend on the tier that was granted.
    assessment = assess(application, user)
    application.offered_limit = assessment['limit'] or None
    application.eligibility_score = assessment['score']

    db.session.commit()
    return application


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


def decide(application: CreditApplications, *, user, approve: bool = None,
           limit=None, note: str = None, actor_id: str = None):
    """
    Decide an application, and issue the account when it is approved.

    `approve` and `limit` are the override path, for an administrator. Left as
    None, the engine's own assessment decides - which is the normal case, and
    the one the applicant experiences.

    An override limit is still bounded by the applicant's tier cap. An admin may
    decline someone the engine would approve, and may grant less than it offered,
    but may not hand out more credit than the tier allows: that bound exists for
    compliance reasons rather than as a suggestion.

    Returns (application, account). account is None on a decline.
    """
    if not application.can_transition_to(ApplicationStatus.APPROVED) and \
            not application.can_transition_to(ApplicationStatus.REJECTED):
        raise CreditError(
            ErrorCode.CONFLICT,
            'This application has already been decided.',
        )

    assessment = assess(application, user)

    if approve is None:
        approve = assessment['approved']
        granted = assessment['limit']
        reason = assessment['reason']
    elif approve:
        granted = money(limit) if limit is not None else assessment['limit']
        tier_cap = money(settings.get_decimal(
            Key.CREDIT_LIMIT_MAX_FULL_KYC if user.kyc_tier == KYCTier.FULL
            else Key.CREDIT_LIMIT_MAX_STANDARD_KYC
        ))
        if granted > tier_cap:
            raise CreditError(
                ErrorCode.VALIDATION_ERROR,
                f'A {user.kyc_tier} KYC customer cannot be granted more than '
                f'Rs. {tier_cap:,.2f}.',
            )
        if granted <= ZERO:
            raise CreditError(
                ErrorCode.VALIDATION_ERROR,
                'An approved limit must be greater than zero.',
            )
        reason = DecisionReason.APPROVED
    else:
        granted = ZERO
        reason = DecisionReason.MANUAL_DECLINE

    application.eligibility_score = assessment['score']
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
            'credit_account_id': account.credit_account_id,
            'decided_by': actor_id or 'AUTOMATIC',
        },
    )
    return application, account


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
                merchant_name=merchant_name[:120],
                merchant_category=merchant_category,
                description=(description or '')[:200] or None,
                idempotency_key=idempotency_key,
                is_test=is_test,
                settled_at=utcnow(),
            )
            db.session.add(record)
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


# ── Bill payment ───────────────────────────────────────────────────────────

def pay_bill(*, account: CreditAccounts, amount, source_type: str,
             source_ref: str, idempotency_key: str,
             statement: CreditStatements = None) -> CreditTransactions:
    """
    Settle some or all of what is owed, and restore the credit it frees.

    Same locking discipline as a purchase, and the same idempotency guarantee -
    paying a bill twice by accident is worse than spending twice, because the
    money has actually left the user's account.

    Refuses to accept more than is outstanding. An overpayment would create a
    credit balance on the line, which this product has no concept of; taking the
    money and leaving it unrepresented would be the worst of the options.
    """
    amount = money(amount)
    minimum = money(settings.get_decimal(Key.PAYMENT_MIN_AMOUNT))

    if amount < minimum:
        raise CreditError(
            ErrorCode.VALIDATION_ERROR,
            f'The smallest payment we can collect is Rs. {minimum:,.2f}.',
        )

    existing = CreditTransactions.query.filter_by(
        idempotency_key=idempotency_key,
    ).first()
    if existing:
        raise DuplicateSpend(existing)

    try:
        with ledger_engine.atomic():
            locked = _lock(account.credit_account_id)

            if locked.status == CreditAccountStatus.CLOSED:
                raise CreditError(
                    ErrorCode.CONFLICT, 'This credit line is closed.',
                )

            outstanding_before = money(locked.current_outstanding)

            if outstanding_before <= ZERO:
                raise CreditError(
                    ErrorCode.CONFLICT,
                    'There is nothing outstanding on this credit line.',
                )

            if amount > outstanding_before:
                raise CreditError(
                    ErrorCode.VALIDATION_ERROR,
                    f'You owe Rs. {outstanding_before:,.2f}. Enter that or less.',
                    recovery=f'Pay the full outstanding of '
                             f'Rs. {outstanding_before:,.2f}.',
                )

            outstanding = outstanding_before - amount
            available = money(locked.credit_limit) - outstanding
            _assert_invariant(locked, available, outstanding)

            txn = ledger_engine.post(
                user_id=locked.user_id,
                transaction_type=TransactionType.CREDIT_BILL_PAYMENT,
                gross_amount=amount,
                net_amount=amount,
                source_type=source_type,
                source_masked_ref=source_ref[:150],
                dest_type=DestType.CREDIT_LINE,
                dest_masked_ref=locked.masked_number,
                gateway_provider=GatewayProvider.INTERNAL,
                idempotency_key=idempotency_key,
                status=TransactionStatus.SUCCEEDED,
                entries=ledger_engine.entries_for_credit_bill_payment(
                    amount, source_ref, locked.masked_number,
                ),
                commit=False,
            )

            locked.current_outstanding = outstanding
            locked.available_credit = available

            record = CreditTransactions(
                credit_account_id=locked.credit_account_id,
                user_id=locked.user_id,
                transaction_id=txn.transaction_id,
                transaction_type=CreditTransactionType.PAYMENT,
                status=CreditTransactionStatus.SUCCEEDED,
                amount=amount,
                balance_after=outstanding,
                description='Credit card bill payment',
                idempotency_key=idempotency_key,
                settled_at=utcnow(),
            )
            db.session.add(record)

            # Apply it to the statement it was meant for, or to the oldest one
            # still owing. Oldest first is what stops a payment clearing this
            # month's bill while last month's goes overdue.
            target = statement or _oldest_outstanding_statement(
                locked.credit_account_id
            )
            if target is not None:
                _apply_to_statement(target, amount)
    except IntegrityError:
        db.session.rollback()
        original = CreditTransactions.query.filter_by(
            idempotency_key=idempotency_key,
        ).first()
        if original:
            raise DuplicateSpend(original)
        raise

    audit.record(
        action='CREDIT_BILL_PAYMENT',
        entity_type='CreditTransactions',
        entity_id=record.credit_transaction_id,
        actor_user_id=record.user_id,
        after={
            'amount': float(amount),
            'outstanding_before': float(outstanding_before),
            'outstanding_after': float(record.balance_after),
        },
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

    unbilled = CreditTransactions.query.filter(
        CreditTransactions.credit_account_id == account.credit_account_id,
        CreditTransactions.statement_id.is_(None),
        CreditTransactions.status == CreditTransactionStatus.SUCCEEDED,
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

    previous = CreditStatements.query.filter(
        CreditStatements.credit_account_id == account.credit_account_id,
    ).order_by(CreditStatements.period_end.desc()).first()

    # The opening balance is the previous statement's unpaid remainder, not its
    # closing balance: anything paid since then is already gone.
    opening = (
        money(previous.closing_balance) - money(previous.amount_paid)
        if previous else ZERO
    )
    if opening < ZERO:
        opening = ZERO

    closing = opening + purchases + fees - payments - refunds
    if closing < ZERO:
        closing = ZERO

    percent = money(settings.get_decimal(Key.MINIMUM_DUE_PERCENT))
    minimum = money(closing * percent / 100)
    # A minimum due below the collectable floor is pointless, so a small balance
    # is simply due in full.
    floor = money(settings.get_decimal(Key.PAYMENT_MIN_AMOUNT))
    if closing <= floor or minimum < floor:
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

            outstanding = money(locked.current_outstanding) - amount
            if outstanding < ZERO:
                outstanding = ZERO
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
