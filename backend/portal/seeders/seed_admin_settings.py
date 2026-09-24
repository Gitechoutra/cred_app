"""
Seed platform settings (PRD 9.2, 12, 17.1).

Defaults come straight from the PRD. min_value and max_value are guard rails so
an operator cannot fat-finger a 1.95% fee into 195% on a live platform.
"""

import logging

from portal import db
from portal.helpers.settings import Key
from portal.models.admin_settings import AdminSettings, SettingDataType

logger = logging.getLogger('cashu')

D = SettingDataType

# (key, value, type, category, display name, description, min, max, editable)
SETTINGS = [
    # -- Payments ----------------------------------------------------------
    (Key.PAYMENT_MIN_AMOUNT, '1', D.DECIMAL, 'PAYMENTS',
     'Minimum Payment Amount',
     'Smallest amount any payment may collect - a card bill, an EMI or a '
     'scanned QR. Bounded below by the gateway floor of 100 paise.',
     '1', '1000', True),
    (Key.GST_PERCENT, '18', D.DECIMAL, 'PRICING',
     'GST (%)', 'Applied to fees only, never to principal.',
     '0', '28', True),

    # -- Credit line -------------------------------------------------------
    (Key.CREDIT_LIMIT_MIN, '5000', D.DECIMAL, 'CREDIT',
     'Minimum Credit Limit',
     'Smallest credit line worth issuing. An approval that scores below this '
     'is declined rather than issued.', '1000', '50000', True),
    (Key.CREDIT_LIMIT_MAX_STANDARD_KYC, '50000', D.DECIMAL, 'CREDIT',
     'Max Credit Limit (Standard KYC)',
     'Ceiling on the credit line a minimum-KYC user may be granted.',
     '5000', '100000', True),
    (Key.CREDIT_LIMIT_MAX_FULL_KYC, '200000', D.DECIMAL, 'CREDIT',
     'Max Credit Limit (Full KYC)',
     'Ceiling on the credit line a full-KYC user may be granted.',
     '10000', '1000000', True),
    (Key.CREDIT_DAILY_SPEND_LIMIT, '100000', D.DECIMAL, 'CREDIT',
     'Daily Spend Limit', 'Rolling 24-hour cumulative cap per card.',
     '1000', '1000000', True),
    (Key.CREDIT_MONTHLY_SPEND_LIMIT, '250000', D.DECIMAL, 'CREDIT',
     'Monthly Spend Limit', 'Calendar-month cumulative cap per card.',
     '1000', '5000000', True),
    (Key.FULL_KYC_REQUIRED_ABOVE, '50000', D.DECIMAL, 'COMPLIANCE',
     'Full KYC Required Above',
     'A credit limit above this amount requires full KYC verification.',
     '1000', '200000', True),

    # -- Statement and billing ---------------------------------------------
    (Key.STATEMENT_CYCLE_DAY, '1', D.INTEGER, 'BILLING',
     'Statement Cycle Day',
     'Day of the month the statement is cut. Spends after it fall into the '
     'next cycle.', '1', '28', True),
    (Key.STATEMENT_GRACE_DAYS, '18', D.INTEGER, 'BILLING',
     'Grace Period (days)',
     'Days between the statement date and the payment due date.',
     '10', '45', True),
    (Key.MINIMUM_DUE_PERCENT, '5', D.DECIMAL, 'BILLING',
     'Minimum Due (%)',
     'Smallest share of the statement balance that may be paid to stay current.',
     '1', '100', True),
    (Key.LATE_PAYMENT_FEE, '500', D.DECIMAL, 'BILLING',
     'Late Payment Fee',
     'Charged once when a statement passes its due date unpaid.',
     '0', '5000', True),

    # -- Risk (PRD 16.1, ERR-011) -----------------------------------------
    (Key.VELOCITY_MAX_PAYMENTS_PER_HOUR, '3', D.INTEGER, 'RISK',
     'Max Payments Per Hour', 'Velocity threshold before throttling (ERR-011).',
     '1', '20', True),
    (Key.VELOCITY_THROTTLE_MINUTES, '30', D.INTEGER, 'RISK',
     'Velocity Throttle (minutes)', 'How long a user is throttled after a breach.',
     '5', '240', True),
    (Key.MAKER_CHECKER_THRESHOLD, '25000', D.DECIMAL, 'RISK',
     'Maker-Checker Threshold',
     'Reversals above this amount need a second administrator to approve.',
     '1000', '500000', True),

    # -- Authentication (PRD FR-001, 17.1) --------------------------------
    (Key.OTP_LENGTH, '6', D.INTEGER, 'AUTH',
     'OTP Length', 'Number of digits in an OTP.', '4', '8', False),
    (Key.OTP_EXPIRY_SECONDS, '180', D.INTEGER, 'AUTH',
     'OTP Validity (seconds)', 'How long an OTP remains usable.',
     '60', '600', True),
    (Key.OTP_MAX_RESENDS_PER_WINDOW, '3', D.INTEGER, 'AUTH',
     'Max OTP Resends', 'Resends permitted per rolling window.', '1', '10', True),
    (Key.OTP_RESEND_WINDOW_MINUTES, '15', D.INTEGER, 'AUTH',
     'OTP Resend Window (minutes)', 'Length of the OTP resend window.',
     '5', '60', True),
    (Key.AUTH_MAX_FAILED_ATTEMPTS, '3', D.INTEGER, 'AUTH',
     'Max Failed Auth Attempts', 'Failures before the account is locked.',
     '3', '10', True),
    (Key.AUTH_LOCKOUT_MINUTES, '30', D.INTEGER, 'AUTH',
     'Auth Lockout (minutes)', 'How long an account stays locked.',
     '5', '1440', True),

    # -- Mandates (PRD 12) -------------------------------------------------
    (Key.MANDATE_CAP_MULTIPLIER, '1.10', D.DECIMAL, 'MANDATES',
     'Mandate Cap Multiplier',
     'Mandate ceiling as a multiple of the EMI, to absorb interest adjustments.',
     '1', '2', True),
    (Key.MANDATE_PREDEBIT_NOTICE_HOURS, '48', D.INTEGER, 'MANDATES',
     'Pre-Debit Notice (hours)',
     'Notice before a recurring debit. RBI requires at least 24.',
     '24', '168', True),
    (Key.UPI_AUTOPAY_MAX_AMOUNT, '15000', D.DECIMAL, 'MANDATES',
     'UPI AutoPay Ceiling',
     'Above this, e-NACH is used instead of UPI AutoPay.', '1000', '100000', True),
    (Key.ENACH_MAX_AMOUNT, '1000000', D.DECIMAL, 'MANDATES',
     'e-NACH Ceiling', 'Maximum permitted e-NACH mandate value.',
     '10000', '10000000', True),

    # -- Penny drop (PRD FR-005) ------------------------------------------
    (Key.PENNY_DROP_MATCH_THRESHOLD, '80', D.DECIMAL, 'COMPLIANCE',
     'Name Match Threshold (%)',
     'Confidence at or above which a bank account is auto-verified.',
     '50', '100', True),
    (Key.PENNY_DROP_REVIEW_THRESHOLD, '70', D.DECIMAL, 'COMPLIANCE',
     'Name Match Review Threshold (%)',
     'Below this, the account is held under PMLA third-party rules.',
     '40', '95', True),

    (Key.PLATFORM_DEFAULT_CURRENCY, 'INR', D.STRING, 'PLATFORM',
     'Default Currency', 'CashU operates in Indian Rupees only.',
     None, None, False),
]


def seed_admin_settings():
    created = 0

    for (key, value, data_type, category, display_name,
         description, min_value, max_value, editable) in SETTINGS:
        # Only insert what is missing. An operator's tuned value must survive a
        # restart, so an existing row is never overwritten.
        if not AdminSettings.query.filter_by(setting_key=key).first():
            db.session.add(AdminSettings(
                setting_key=key,
                setting_value=value,
                default_value=value,
                data_type=data_type,
                category=category,
                display_name=display_name,
                description=description,
                min_value=min_value,
                max_value=max_value,
                is_editable=editable,
            ))
            created += 1

    if created:
        db.session.commit()
        logger.info(f'[Seeders] seed_admin_settings: created {created} setting(s).')
