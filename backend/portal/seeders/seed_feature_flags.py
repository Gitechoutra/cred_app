"""
Seed feature flags.

CARD_ISSUANCE ships ON in development so the flow is walkable, but the flag
exists precisely because a credit line is the regulated part of this platform -
issuance must be switchable off from the console, without a deploy, the moment
compliance or the issuing partner says so.
"""

import logging

from portal import db
from portal.helpers.settings import Flag
from portal.models.admin_settings import FeatureFlags, FlagRolloutType

logger = logging.getLogger('cashu')

FLAGS = [
    (Flag.CARD_ISSUANCE, 'Card Issuance',
     'Master switch for new credit-line applications and activations. Turn off '
     'to stop issuing immediately, without a deploy. Existing cards keep '
     'working.', True),
    (Flag.EMI_MANUAL_PAY, 'Manual EMI Payment',
     'Allows users to pay EMI installments on demand (FR-008).', True),
    (Flag.EMI_AUTO_PAY, 'EMI Auto-Pay Mandates',
     'Allows NPCI e-Mandate and UPI AutoPay registration (FR-009).', True),
    (Flag.CARD_LINKING, 'Card Linking',
     'Allows new credit cards to be tokenized and linked (FR-003).', True),
    (Flag.NEW_USER_REGISTRATION, 'New User Registration',
     'Allows previously unseen phone numbers to open an account.', True),
    (Flag.MAINTENANCE_MODE, 'Maintenance Mode',
     'Blocks all money movement while planned work is in progress.', False),
]


def seed_feature_flags():
    created = 0

    for flag_key, display_name, description, enabled in FLAGS:
        if not FeatureFlags.query.filter_by(flag_key=flag_key).first():
            db.session.add(FeatureFlags(
                flag_key=flag_key,
                display_name=display_name,
                description=description,
                is_enabled=enabled,
                rollout_type=FlagRolloutType.BOOLEAN,
                rollout_percentage=100 if enabled else 0,
            ))
            created += 1

    if created:
        db.session.commit()
        logger.info(f'[Seeders] seed_feature_flags: created {created} flag(s).')
