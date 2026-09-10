"""
Seed the bootstrap administrator.

A platform with no administrator cannot approve the first KYC, which means no
user can transact - so one L3 account is created on first boot.

The MPIN comes from ADMIN_SEED_MPIN. Outside development the seeder refuses to
invent one: a known default credential on an account that can change transfer
limits and read raw PII is a far worse failure than a boot that stops and tells
you to set a variable.
"""

import logging
import os

from portal import db
from portal.helpers.encryption import hash_secret
from portal.models.base import utcnow
from portal.models.notifications import NotificationPreferences
from portal.models.roles import RoleTypes, Roles
from portal.models.user_security_settings import UserSecuritySettings
from portal.models.users import KYCTier, UserStatus, Users

logger = logging.getLogger('cashu')


def seed_admin():
    role = Roles.query.filter_by(role_name=RoleTypes.L3_SUPER_ADMIN).first()
    if not role:
        raise RuntimeError(
            'L3_SUPER_ADMIN role is missing - seed_roles must run first.'
        )

    phone = os.getenv('ADMIN_SEED_PHONE', '9999999999')

    if Users.query.filter_by(phone=phone).first():
        return

    mpin = os.getenv('ADMIN_SEED_MPIN', '')
    is_dev = os.getenv('Backend', 'DEV').upper() == 'DEV'

    if not mpin:
        if not is_dev:
            raise RuntimeError(
                'ADMIN_SEED_MPIN must be set before seeding the administrator '
                'outside development.'
            )
        mpin = '135790'
        logger.warning(
            '[Seeders] seed_admin: using the development MPIN. Set '
            'ADMIN_SEED_MPIN before deploying anywhere real.'
        )

    admin = Users(
        role_id=role.role_id,
        phone=phone,
        email=os.getenv('ADMIN_SEED_EMAIL', 'admin@cashu.app'),
        full_name=os.getenv('ADMIN_SEED_NAME', 'CashU Administrator'),
        mpin_hash=hash_secret(mpin),
        kyc_tier=KYCTier.FULL,
        status=UserStatus.ACTIVE,
        is_phone_verified=True,
        is_email_verified=True,
        is_active=True,
        terms_accepted=True,
        terms_accepted_at=utcnow(),
    )
    db.session.add(admin)
    db.session.flush()

    db.session.add(UserSecuritySettings(
        user_id=admin.user_id, mpin_set=True, mpin_last_changed=utcnow()
    ))
    db.session.add(NotificationPreferences(user_id=admin.user_id))
    db.session.commit()

    logger.info(f'[Seeders] seed_admin: created L3 administrator {phone}.')
