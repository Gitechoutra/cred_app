"""
portal/helpers/settings.py
==========================
Typed reads of admin_settings and feature_flags.

Transaction limits and the convenience fee are commercial levers that change
without a deploy (PRD 16.1), so they live in the database. Every read is
defensive: a missing or corrupted row falls back to the seeded default rather
than raising, because a settings lookup failing should not take down the
transfer path.
"""

import json
from decimal import Decimal, InvalidOperation

from flask import current_app

from portal.models.admin_settings import AdminSettings, FeatureFlags


class Key:
    """Setting keys, so a typo is an import error rather than a silent default."""

    # -- Payments ------------------------------------------------------------
    #: Floor for any collected payment - a card bill, an EMI, a scanned QR.
    #: Bounded below by the gateway's own 100-paise minimum.
    PAYMENT_MIN_AMOUNT = 'PAYMENT_MIN_AMOUNT'
    GST_PERCENT = 'GST_PERCENT'

    # -- Credit line (issuance and spending) ---------------------------------
    #: Ceiling on the credit limit a KYC tier may be granted. The limit itself
    #: is decided by the backend at approval; these bound that decision.
    CREDIT_LIMIT_MAX_STANDARD_KYC = 'CREDIT_LIMIT_MAX_STANDARD_KYC'
    CREDIT_LIMIT_MAX_FULL_KYC = 'CREDIT_LIMIT_MAX_FULL_KYC'
    CREDIT_LIMIT_MIN = 'CREDIT_LIMIT_MIN'
    CREDIT_DAILY_SPEND_LIMIT = 'CREDIT_DAILY_SPEND_LIMIT'
    CREDIT_MONTHLY_SPEND_LIMIT = 'CREDIT_MONTHLY_SPEND_LIMIT'
    #: A credit limit above this needs full KYC, not just minimum KYC.
    FULL_KYC_REQUIRED_ABOVE = 'FULL_KYC_REQUIRED_ABOVE'

    # -- Statement and billing ----------------------------------------------
    #: Day of the month the statement is cut. Due date follows it by the grace
    #: period below.
    STATEMENT_CYCLE_DAY = 'STATEMENT_CYCLE_DAY'
    STATEMENT_GRACE_DAYS = 'STATEMENT_GRACE_DAYS'
    #: Smallest share of the statement balance a payment may settle, as a
    #: percentage. RBI-style minimum due.
    MINIMUM_DUE_PERCENT = 'MINIMUM_DUE_PERCENT'
    LATE_PAYMENT_FEE = 'LATE_PAYMENT_FEE'

    # -- Risk (PRD 16.1, ERR-011) -------------------------------------------
    VELOCITY_MAX_PAYMENTS_PER_HOUR = 'VELOCITY_MAX_PAYMENTS_PER_HOUR'
    VELOCITY_THROTTLE_MINUTES = 'VELOCITY_THROTTLE_MINUTES'
    MAKER_CHECKER_THRESHOLD = 'MAKER_CHECKER_THRESHOLD'

    # -- Auth (PRD FR-001, 17.1) --------------------------------------------
    OTP_LENGTH = 'OTP_LENGTH'
    OTP_EXPIRY_SECONDS = 'OTP_EXPIRY_SECONDS'
    OTP_MAX_RESENDS_PER_WINDOW = 'OTP_MAX_RESENDS_PER_WINDOW'
    OTP_RESEND_WINDOW_MINUTES = 'OTP_RESEND_WINDOW_MINUTES'
    AUTH_MAX_FAILED_ATTEMPTS = 'AUTH_MAX_FAILED_ATTEMPTS'
    AUTH_LOCKOUT_MINUTES = 'AUTH_LOCKOUT_MINUTES'

    # -- Mandates (PRD 12) ---------------------------------------------------
    MANDATE_CAP_MULTIPLIER = 'MANDATE_CAP_MULTIPLIER'
    MANDATE_PREDEBIT_NOTICE_HOURS = 'MANDATE_PREDEBIT_NOTICE_HOURS'
    UPI_AUTOPAY_MAX_AMOUNT = 'UPI_AUTOPAY_MAX_AMOUNT'
    ENACH_MAX_AMOUNT = 'ENACH_MAX_AMOUNT'

    # -- Penny drop (PRD FR-005) --------------------------------------------
    PENNY_DROP_MATCH_THRESHOLD = 'PENNY_DROP_MATCH_THRESHOLD'
    PENNY_DROP_REVIEW_THRESHOLD = 'PENNY_DROP_REVIEW_THRESHOLD'

    PLATFORM_DEFAULT_CURRENCY = 'PLATFORM_DEFAULT_CURRENCY'


class Flag:
    """Feature flag keys."""

    CARD_ISSUANCE = 'CARD_ISSUANCE'
    EMI_AUTO_PAY = 'EMI_AUTO_PAY'
    EMI_MANUAL_PAY = 'EMI_MANUAL_PAY'
    CARD_LINKING = 'CARD_LINKING'
    NEW_USER_REGISTRATION = 'NEW_USER_REGISTRATION'
    MAINTENANCE_MODE = 'MAINTENANCE_MODE'


#: Fallbacks used when the row is missing. Mirrors the seeder so behaviour is
#: identical on a fresh database and a seeded one.
_DEFAULTS = {
    Key.PAYMENT_MIN_AMOUNT: '1',
    Key.GST_PERCENT: '18',
    Key.CREDIT_LIMIT_MAX_STANDARD_KYC: '50000',
    Key.CREDIT_LIMIT_MAX_FULL_KYC: '200000',
    Key.CREDIT_LIMIT_MIN: '5000',
    Key.CREDIT_DAILY_SPEND_LIMIT: '100000',
    Key.CREDIT_MONTHLY_SPEND_LIMIT: '250000',
    Key.FULL_KYC_REQUIRED_ABOVE: '50000',
    Key.STATEMENT_CYCLE_DAY: '1',
    Key.STATEMENT_GRACE_DAYS: '18',
    Key.MINIMUM_DUE_PERCENT: '5',
    Key.LATE_PAYMENT_FEE: '500',
    Key.VELOCITY_MAX_PAYMENTS_PER_HOUR: '3',
    Key.VELOCITY_THROTTLE_MINUTES: '30',
    Key.MAKER_CHECKER_THRESHOLD: '25000',
    Key.OTP_LENGTH: '6',
    Key.OTP_EXPIRY_SECONDS: '180',
    Key.OTP_MAX_RESENDS_PER_WINDOW: '3',
    Key.OTP_RESEND_WINDOW_MINUTES: '15',
    Key.AUTH_MAX_FAILED_ATTEMPTS: '3',
    Key.AUTH_LOCKOUT_MINUTES: '30',
    Key.MANDATE_CAP_MULTIPLIER: '1.10',
    Key.MANDATE_PREDEBIT_NOTICE_HOURS: '48',
    Key.UPI_AUTOPAY_MAX_AMOUNT: '15000',
    Key.ENACH_MAX_AMOUNT: '1000000',
    Key.PENNY_DROP_MATCH_THRESHOLD: '80',
    Key.PENNY_DROP_REVIEW_THRESHOLD: '70',
    Key.PLATFORM_DEFAULT_CURRENCY: 'INR',
}


def get(key: str, default=None) -> str:
    try:
        row = AdminSettings.query.filter_by(setting_key=key).first()
        if row and row.setting_value is not None:
            return row.setting_value
    except Exception as exc:
        current_app.logger.warning(f'[settings] read failed for {key}: {exc}')

    return default if default is not None else _DEFAULTS.get(key)


def get_decimal(key: str, default=None) -> Decimal:
    raw = get(key, default)
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        current_app.logger.warning(
            f'[settings] {key}={raw!r} is not a number; using the seeded default.'
        )
        return Decimal(str(_DEFAULTS.get(key, 0)))


def get_int(key: str, default=None) -> int:
    try:
        return int(Decimal(str(get(key, default))))
    except (InvalidOperation, TypeError, ValueError):
        return int(_DEFAULTS.get(key, 0))


def get_list_int(key: str) -> list:
    """Parse a comma-separated setting such as the retry backoff ladder."""
    raw = get(key) or ''
    out = []
    for part in str(raw).split(','):
        part = part.strip()
        if part:
            try:
                out.append(int(part))
            except ValueError:
                continue
    return out or [int(p) for p in str(_DEFAULTS.get(key, '')).split(',') if p.strip()]


def get_bool(key: str, default: bool = False) -> bool:
    raw = get(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in ('true', '1', 'yes', 'on')


def set_value(key: str, value, updated_by: str = None):
    from portal import db

    row = AdminSettings.query.filter_by(setting_key=key).first()
    if not row:
        row = AdminSettings(setting_key=key, default_value=str(value))
        db.session.add(row)

    row.setting_value = str(value)
    row.updated_by = updated_by
    db.session.commit()
    return row


# ── Feature flags ──────────────────────────────────────────────────────────

def flag_enabled(flag_key: str, user_id: str = None) -> bool:
    """
    Resolve a feature flag.

    A missing flag is treated as OFF. For a platform where one flag gates a
    feature with an unresolved regulatory model (PRD open decision 1), failing
    closed is the only safe default.
    """
    try:
        flag = FeatureFlags.query.filter_by(flag_key=flag_key).first()
        if not flag:
            return False
        if not flag.is_enabled:
            return False

        from portal.models.admin_settings import FlagRolloutType

        if flag.rollout_type == FlagRolloutType.BOOLEAN:
            return True

        if flag.rollout_type == FlagRolloutType.USER_LIST:
            if not user_id or not flag.target_user_ids:
                return False
            try:
                return str(user_id) in json.loads(flag.target_user_ids)
            except (ValueError, TypeError):
                return False

        if flag.rollout_type == FlagRolloutType.PERCENTAGE:
            if not user_id:
                return False
            # Stable bucketing: the same user always lands in the same bucket,
            # so a rollout does not flicker a feature on and off between calls.
            bucket = int(str(user_id).replace('-', '')[-8:], 16) % 100
            return bucket < (flag.rollout_percentage or 0)

        return False

    except Exception as exc:
        current_app.logger.warning(f'[flags] read failed for {flag_key}: {exc}')
        return False
