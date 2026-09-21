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
    # -- Transfer limits and pricing (PRD 9.2) -----------------------------
    (Key.TRANSFER_MIN_AMOUNT, '1', D.DECIMAL, 'TRANSFERS',
     'Minimum Transfer Amount', 'Smallest permitted credit-to-bank transfer.',
     # The lower bound is Rs. 1 because that is the payment gateway's own floor
     # - an order below 100 paise is rejected by Razorpay, so no configuration
     # below it could ever be honoured.
     '1', '10000', True),
    (Key.PAYMENT_MIN_AMOUNT, '1', D.DECIMAL, 'PAYMENTS',
     'Minimum Payment Amount',
     'Smallest amount any payment may collect - EMI, UPI or gateway. Bounded '
     'below by the gateway floor of 100 paise.',
     '1', '1000', True),
    (Key.TRANSFER_MAX_SINGLE_STANDARD_KYC, '50000', D.DECIMAL, 'TRANSFERS',
     'Max Single Transfer (Standard KYC)',
     'Per-transaction ceiling for a minimum-KYC user.', '1000', '100000', True),
    (Key.TRANSFER_MAX_SINGLE_FULL_KYC, '100000', D.DECIMAL, 'TRANSFERS',
     'Max Single Transfer (Full KYC)',
     'Per-transaction ceiling for a full-KYC user.', '1000', '500000', True),
    (Key.TRANSFER_DAILY_LIMIT, '100000', D.DECIMAL, 'TRANSFERS',
     'Daily Transfer Limit', 'Rolling 24-hour cumulative cap per user.',
     '1000', '1000000', True),
    (Key.TRANSFER_MONTHLY_LIMIT, '250000', D.DECIMAL, 'TRANSFERS',
     'Monthly Transfer Limit', 'Calendar-month cumulative cap per user.',
     '1000', '5000000', True),
    (Key.TRANSFER_CONVENIENCE_FEE_PERCENT, '1.95', D.DECIMAL, 'PRICING',
     'Convenience Fee (%)', 'Charged on the principal of every transfer.',
     '0', '5', True),
    (Key.GST_PERCENT, '18', D.DECIMAL, 'PRICING',
     'GST (%)', 'Applied to the convenience fee only, never the principal.',
     '0', '28', True),
    (Key.FULL_KYC_REQUIRED_ABOVE, '10000', D.DECIMAL, 'COMPLIANCE',
     'Full KYC Required Above',
     'Transfers above this amount require full KYC verification.',
     '1000', '100000', True),

    # -- Risk (PRD 16.1, ERR-011) -----------------------------------------
    (Key.VELOCITY_MAX_TRANSFERS_PER_HOUR, '3', D.INTEGER, 'RISK',
     'Max Transfers Per Hour', 'Velocity threshold before throttling (ERR-011).',
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

    # -- Payout retry (PRD 9.4) -------------------------------------------
    (Key.PAYOUT_MAX_RETRIES, '3', D.INTEGER, 'TRANSFERS',
     'Payout Max Retries', 'Attempts before a charged transfer is reversed.',
     '1', '5', True),
    (Key.PAYOUT_RETRY_BACKOFF_MINUTES, '2,5,15', D.STRING, 'TRANSFERS',
     'Payout Retry Backoff', 'Comma-separated minute delays between retries.',
     None, None, True),

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
