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
    BillPaymentMethod, CreditTransactions, CreditTransactionStatus,
    CreditTransactionType,
)
from portal.models.master_transactions import (
    DestType, GatewayProvider, SourceType, TransactionStatus, TransactionType,
)
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
            if amount > outstanding:
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
    while the payment was in flight - a refund landed - the part that no longer
    has anything to settle is recorded for operations to return, rather than
    written as a credit balance the product cannot represent.
    """
    amount = money(record.amount)

    with ledger_engine.atomic():
        account = _lock(record.credit_account_id)

        outstanding_before = money(account.current_outstanding)
        applied = min(amount, outstanding_before)
        excess = amount - applied
        outstanding = outstanding_before - applied
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

    if excess > ZERO:
        current_app.logger.error(
            f'[credit] bill payment {record.credit_transaction_id} collected '
            f'Rs. {excess} more than was owed; queued for return.'
        )
        error_recorder.record(
            user_id=record.user_id,
            code='BILL_OVERPAYMENT',
            reason=f'Collected Rs. {excess} above the outstanding balance.',
            reference_type='CreditTransactions',
            reference_id=record.credit_transaction_id,
            transaction_id=record.transaction_id,
            payment_method=record.payment_method,
            gateway=record.gateway_provider,
            amount=excess,
            transaction_status=record.status,
        )

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

    fresh = (
        CreditAccounts.query
        .filter_by(credit_account_id=account.credit_account_id)
        .populate_existing()
        .first()
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
