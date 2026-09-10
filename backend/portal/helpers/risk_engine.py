"""
portal/helpers/risk_engine.py
=============================
Pre-authorization risk checks for transfers (PRD FR-006, 16.1, ERR-011).

Runs at the INITIATED -> RISK_CHECKED edge of the transfer state machine, before
any money moves. Everything here is a hard gate: a REJECT is a refusal, not a
score to weigh later.

Order matters. The cheapest and most absolute checks run first so an obviously
invalid request never reaches a database aggregate or a vendor call.
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func

from portal import db
from portal.helpers import rate_limit, settings
from portal.helpers.helpers import ErrorCode
from portal.helpers.settings import Key
from portal.models.base import utcnow
from portal.models.transfer_limits import TransferLimitCounters
from portal.models.transfers import TransferStatus, Transfers
from portal.models.users import KYCTier


class RiskDecision:
    APPROVE = 'APPROVE'
    REJECT = 'REJECT'
    REVIEW = 'REVIEW'


class RiskResult:
    def __init__(
        self,
        decision: str,
        reason: str = None,
        error_code: str = None,
        score: float = 0.0,
        details: dict = None,
        recovery: str = None,
    ):
        self.decision = decision
        self.reason = reason
        self.error_code = error_code
        self.score = score
        self.details = details or {}
        self.recovery = recovery

    @property
    def approved(self) -> bool:
        return self.decision == RiskDecision.APPROVE

    def __repr__(self):
        return f'<RiskResult {self.decision} {self.reason}>'


def _window_keys():
    now = utcnow()
    return now.strftime('%Y-%m-%d'), now.strftime('%Y-%m')


def current_usage(user_id: str) -> dict:
    """
    Spend already committed in the current daily and monthly windows.

    Read from counter rows rather than aggregating `transfers`, so the check
    stays a constant-cost indexed read as history grows.
    """
    daily_key, monthly_key = _window_keys()

    rows = TransferLimitCounters.query.filter(
        TransferLimitCounters.user_id == user_id,
        db.or_(
            db.and_(
                TransferLimitCounters.window_type == 'DAILY',
                TransferLimitCounters.window_key == daily_key,
            ),
            db.and_(
                TransferLimitCounters.window_type == 'MONTHLY',
                TransferLimitCounters.window_key == monthly_key,
            ),
        ),
    ).all()

    usage = {
        'daily_amount': Decimal('0'),
        'daily_count': 0,
        'monthly_amount': Decimal('0'),
        'monthly_count': 0,
    }
    for row in rows:
        if row.window_type == 'DAILY':
            usage['daily_amount'] = Decimal(str(row.total_amount or 0))
            usage['daily_count'] = row.transfer_count or 0
        else:
            usage['monthly_amount'] = Decimal(str(row.total_amount or 0))
            usage['monthly_count'] = row.transfer_count or 0

    return usage


def evaluate_transfer(*, user, card, bank_account, amount: Decimal) -> RiskResult:
    """
    Decide whether a transfer may proceed.

    Every rejection carries the exact user-facing message from the PRD error
    matrix and the recovery action, so the client renders guidance rather than
    a generic decline.
    """
    amount = Decimal(str(amount))

    # -- Feature gate ------------------------------------------------------
    # PRD open decision 1 leaves the transfer merchant model unresolved, so the
    # whole feature must be switchable off without a deploy.
    if not settings.flag_enabled(
        settings.Flag.CREDIT_TO_BANK_TRANSFER, str(user.user_id)
    ):
        return RiskResult(
            RiskDecision.REJECT,
            'Card-to-bank transfers are currently unavailable.',
            ErrorCode.FEATURE_DISABLED,
            recovery='Please try again later or contact support.',
        )

    # -- Instrument eligibility -------------------------------------------
    from portal.models.cards import CardStatus

    if card.status != CardStatus.ACTIVE:
        return RiskResult(
            RiskDecision.REJECT,
            'This card is no longer active. Please link a valid card.',
            ErrorCode.ERR_009_TOKEN_EXPIRED,
            recovery='Link your renewed card and try again.',
        )
    if not card.is_transfer_eligible:
        return RiskResult(
            RiskDecision.REJECT,
            'This card is not eligible for transfers.',
            ErrorCode.INSTRUMENT_NOT_PERMITTED,
        )

    # -- Destination ownership (PMLA) -------------------------------------
    # The single most important control here: money may only land in an account
    # this user has been penny-drop verified to own.
    if not bank_account.is_payout_eligible:
        return RiskResult(
            RiskDecision.REJECT,
            'This bank account is not verified. Complete verification to '
            'receive transfers.',
            ErrorCode.ACCOUNT_NOT_VERIFIED,
            recovery='Verify your bank account from the Bank Accounts screen.',
        )
    if str(bank_account.user_id) != str(user.user_id):
        # Should be unreachable through the API, but a mis-scoped query
        # upstream would otherwise become a third-party transfer.
        return RiskResult(
            RiskDecision.REJECT,
            'Transfers are only permitted to your own verified bank account.',
            ErrorCode.FORBIDDEN,
        )

    # -- Amount bounds (PRD 9.2) -------------------------------------------
    minimum = settings.get_decimal(Key.TRANSFER_MIN_AMOUNT)
    if amount < minimum:
        return RiskResult(
            RiskDecision.REJECT,
            f'Minimum transfer amount is Rs. {minimum:,.2f}.',
            ErrorCode.VALIDATION_ERROR,
        )

    # -- KYC tiering (PRD section 18) --------------------------------------
    full_kyc_above = settings.get_decimal(Key.FULL_KYC_REQUIRED_ABOVE)
    if amount > full_kyc_above and user.kyc_tier != KYCTier.FULL:
        return RiskResult(
            RiskDecision.REJECT,
            f'Complete full KYC verification to transfer more than '
            f'Rs. {full_kyc_above:,.2f}.',
            ErrorCode.KYC_REQUIRED,
            details={'current_tier': user.kyc_tier, 'required_tier': KYCTier.FULL},
            recovery='Complete Aadhaar verification in Profile.',
        )

    single_max = (
        settings.get_decimal(Key.TRANSFER_MAX_SINGLE_FULL_KYC)
        if user.kyc_tier == KYCTier.FULL
        else settings.get_decimal(Key.TRANSFER_MAX_SINGLE_STANDARD_KYC)
    )
    if amount > single_max:
        return RiskResult(
            RiskDecision.REJECT,
            f'Maximum single transfer is Rs. {single_max:,.2f}.',
            ErrorCode.LIMIT_EXCEEDED,
            details={'limit': float(single_max), 'requested': float(amount)},
        )

    # -- Cumulative limits -------------------------------------------------
    usage = current_usage(user.user_id)
    daily_limit = settings.get_decimal(Key.TRANSFER_DAILY_LIMIT)
    monthly_limit = settings.get_decimal(Key.TRANSFER_MONTHLY_LIMIT)

    if usage['daily_amount'] + amount > daily_limit:
        remaining = max(Decimal('0'), daily_limit - usage['daily_amount'])
        return RiskResult(
            RiskDecision.REJECT,
            f'This exceeds your daily transfer limit. '
            f'Rs. {remaining:,.2f} remaining today.',
            ErrorCode.LIMIT_EXCEEDED,
            details={
                'limit': float(daily_limit),
                'used': float(usage['daily_amount']),
                'remaining': float(remaining),
                'window': 'DAILY',
            },
            recovery='Try a smaller amount, or transfer again tomorrow.',
        )

    if usage['monthly_amount'] + amount > monthly_limit:
        remaining = max(Decimal('0'), monthly_limit - usage['monthly_amount'])
        return RiskResult(
            RiskDecision.REJECT,
            f'This exceeds your monthly transfer limit. '
            f'Rs. {remaining:,.2f} remaining this month.',
            ErrorCode.LIMIT_EXCEEDED,
            details={
                'limit': float(monthly_limit),
                'used': float(usage['monthly_amount']),
                'remaining': float(remaining),
                'window': 'MONTHLY',
            },
        )

    # -- Velocity (ERR-011) ------------------------------------------------
    max_per_hour = settings.get_int(Key.VELOCITY_MAX_TRANSFERS_PER_HOUR)
    recent = db.session.query(func.count(Transfers.transfer_id)).filter(
        Transfers.user_id == user.user_id,
        Transfers.created_on >= utcnow() - timedelta(hours=1),
        Transfers.status.notin_([TransferStatus.RISK_FAILED, TransferStatus.FAILED]),
    ).scalar() or 0

    if recent >= max_per_hour:
        throttle = settings.get_int(Key.VELOCITY_THROTTLE_MINUTES)
        return RiskResult(
            RiskDecision.REJECT,
            f'Transaction limit reached. For security, please wait {throttle} '
            'minutes before trying again.',
            ErrorCode.ERR_011_VELOCITY_ABUSE,
            score=90.0,
            details={'transfers_last_hour': recent, 'max_per_hour': max_per_hour},
        )

    # -- Per-user request rate (PRD 17.1: 3/min on transaction initiation) --
    try:
        rate_limit.hit(
            rate_limit.user_scope('txn_init', str(user.user_id)), limit=3,
            window_seconds=60,
        )
    except rate_limit.RateLimitExceeded as exc:
        return RiskResult(
            RiskDecision.REJECT,
            'Too many transfer attempts. Please wait a moment and try again.',
            ErrorCode.ERR_011_VELOCITY_ABUSE,
            details={'retry_after_seconds': exc.retry_after_seconds},
        )

    # -- Score for the audit trail ----------------------------------------
    # Not a gate - everything above already refused what must be refused. This
    # records how close to the edges the approved transfer sat, which is what
    # an analyst reviewing a pattern after the fact actually needs.
    score = 0.0
    if amount > single_max * Decimal('0.8'):
        score += 25
    if usage['daily_count'] >= 2:
        score += 20
    if user.kyc_tier != KYCTier.FULL:
        score += 15
    if (utcnow() - (user.created_on or utcnow())).days < 7:
        score += 20   # new accounts are the usual shape of a mule account

    return RiskResult(
        RiskDecision.APPROVE,
        'Risk checks passed.',
        score=min(score, 100.0),
        details={
            'daily_used': float(usage['daily_amount']),
            'daily_limit': float(daily_limit),
            'monthly_used': float(usage['monthly_amount']),
            'monthly_limit': float(monthly_limit),
            'transfers_last_hour': recent,
        },
    )


def commit_usage(user_id: str, amount: Decimal, commit: bool = True):
    """
    Record spend against the rolling windows.

    Called only once a transfer is actually charged, not at initiation - a
    transfer that fails 3DS must not consume the user's daily headroom.
    """
    amount = Decimal(str(amount))
    daily_key, monthly_key = _window_keys()

    for window_type, window_key in (('DAILY', daily_key), ('MONTHLY', monthly_key)):
        counter = TransferLimitCounters.query.filter_by(
            user_id=user_id, window_type=window_type, window_key=window_key
        ).with_for_update(nowait=False).first()

        if not counter:
            counter = TransferLimitCounters(
                user_id=user_id,
                window_type=window_type,
                window_key=window_key,
                total_amount=0,
                transfer_count=0,
            )
            db.session.add(counter)
            db.session.flush()

        counter.total_amount = Decimal(str(counter.total_amount or 0)) + amount
        counter.transfer_count = (counter.transfer_count or 0) + 1

    if commit:
        db.session.commit()


def release_usage(user_id: str, amount: Decimal, commit: bool = True):
    """
    Give headroom back when a charged transfer is reversed.

    Without this a user whose payout failed and was refunded would still be
    locked out of their daily limit for money they never received.
    """
    amount = Decimal(str(amount))
    daily_key, monthly_key = _window_keys()

    for window_type, window_key in (('DAILY', daily_key), ('MONTHLY', monthly_key)):
        counter = TransferLimitCounters.query.filter_by(
            user_id=user_id, window_type=window_type, window_key=window_key
        ).with_for_update(nowait=False).first()

        if counter:
            counter.total_amount = max(
                Decimal('0'), Decimal(str(counter.total_amount or 0)) - amount
            )
            counter.transfer_count = max(0, (counter.transfer_count or 0) - 1)

    if commit:
        db.session.commit()
