"""
Seed - and keep in step with .env - the bootstrap administrator.

A platform with no administrator cannot approve the first KYC, which means no
user can transact - so one L3 account is created on first boot.

Its phone and MPIN come only from backend/.env (ADMIN_SEED_PHONE and
ADMIN_SEED_MPIN). There are no built-in defaults: a known default credential on
an account that can change limits and read raw PII is worse than an
administrator who is not created until the variables are set.

.env stays the source of truth after the first boot, too. This used to return
as soon as the admin existed, so changing ADMIN_SEED_MPIN did nothing - the old
hash stayed in the database, the new MPIN was refused, and a few tries locked
the account for half an hour. Now, on every boot, an admin whose stored MPIN
does not match .env gets the .env MPIN (hashed) and its lockout cleared. That
also repairs an MPIN typed straight into users.mpin_hash, which can never
verify because the column holds a salted PBKDF2 hash, not the MPIN itself.
"""

import logging
import os

from portal import db
from portal.helpers.encryption import hash_secret, verify_secret
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

    phone = (os.getenv('ADMIN_SEED_PHONE') or '').strip()
    mpin = (os.getenv('ADMIN_SEED_MPIN') or '').strip()

    if not phone or not mpin:
        logger.error(
            '[Seeders] seed_admin: ADMIN_SEED_PHONE and ADMIN_SEED_MPIN must both '
            'be set in backend/.env. The administrator was not created or updated.'
        )
        return
    if not (phone.isdigit() and len(phone) == 10):
        raise RuntimeError('ADMIN_SEED_PHONE must be a 10-digit mobile number.')
    if not (mpin.isdigit() and len(mpin) == 6):
        raise RuntimeError('ADMIN_SEED_MPIN must be 6 digits.')

    email = (os.getenv('ADMIN_SEED_EMAIL') or '').strip() or None

    existing = Users.query.filter_by(phone=phone).first()
    if existing:
        _sync(existing, mpin)
        return

    # A new ADMIN_SEED_PHONE with the same ADMIN_SEED_EMAIL is the existing
    # administrator changing number, not a second administrator - creating one
    # would also collide with the first on the unique email.
    holder = Users.query.filter_by(email=email).first() if email else None
    if holder:
        if not holder.is_admin:
            logger.error(
                f'[Seeders] seed_admin: ADMIN_SEED_EMAIL {email} belongs to a '
                'non-admin account. The administrator was not created or updated.'
            )
            return
        old = holder.phone
        holder.phone = phone
        db.session.commit()
        logger.warning(
            f'[Seeders] seed_admin: administrator {email} moved from '
            f'******{old[-4:]} to ******{phone[-4:]} (ADMIN_SEED_PHONE in .env).'
        )
        _sync(holder, mpin)
        return

    admin = Users(
        role_id=role.role_id,
        phone=phone,
        email=email,
        full_name=os.getenv('ADMIN_SEED_NAME') or 'CashU Administrator',
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

    logger.info(f'[Seeders] seed_admin: created L3 administrator ******{phone[-4:]}.')


def _sync(user: Users, mpin: str):
    """Bring an existing administrator's MPIN in line with .env."""
    if not user.is_admin:
        # Never promote, or overwrite the MPIN of, a member who happens to own
        # the configured number.
        logger.error(
            f'[Seeders] seed_admin: ******{user.phone[-4:]} belongs to a '
            'non-admin account. Set ADMIN_SEED_PHONE to the administrator\'s number.'
        )
        return

    if verify_secret(mpin, user.mpin_hash):
        return

    user.mpin_hash = hash_secret(mpin)
    user.failed_auth_attempts = 0
    user.locked_until = None
    security = UserSecuritySettings.query.filter_by(user_id=user.user_id).first()
    if security:
        security.mpin_set = True
        security.mpin_last_changed = utcnow()
    db.session.commit()

    logger.warning(
        f'[Seeders] seed_admin: administrator ******{user.phone[-4:]} MPIN updated '
        'from ADMIN_SEED_MPIN in .env, and its lockout cleared.'
    )
