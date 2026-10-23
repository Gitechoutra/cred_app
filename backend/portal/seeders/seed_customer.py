"""
Seed - and keep in step with .env - the bootstrap customer support agent.

The support desk portal (/support-desk/login) admits only L1_SUPPORT accounts.
Staff management can promote a member to L1 later, but that needs an
administrator first, so one agent is seeded here to make the portal usable on a
fresh database.

Its phone and MPIN come only from backend/.env (SUPPORT_SEED_PHONE and
SUPPORT_SEED_MPIN), read the same way as the administrator's - see
seed_admin._setting. There are no built-in defaults. Unlike the administrator
the agent is optional: with the variables unset nothing is seeded and boot
carries on.

On every boot an agent whose stored MPIN does not match .env gets the .env MPIN
(hashed) and its lockout cleared. A number that belongs to a member or an
administrator is left alone: the seeder never promotes or demotes anyone.
"""

import logging

from portal import db
from portal.helpers.encryption import hash_secret, verify_secret
from portal.helpers.validators import ValidationError, validate_mpin
from portal.models.base import utcnow
from portal.models.notifications import NotificationPreferences
from portal.models.roles import RoleTypes, Roles
from portal.models.user_security_settings import UserSecuritySettings
from portal.models.users import KYCTier, UserStatus, Users
from portal.seeders.seed_admin import _setting

logger = logging.getLogger('cashu')


def seed_customer():
    role = Roles.query.filter_by(role_name=RoleTypes.L1_SUPPORT).first()
    if not role:
        raise RuntimeError('L1_SUPPORT role is missing - seed_roles must run first.')

    phone = _setting('SUPPORT_SEED_PHONE')
    mpin = _setting('SUPPORT_SEED_MPIN')

    if not phone and not mpin:
        logger.info('[Seeders] seed_customer: SUPPORT_SEED_PHONE is not set, '
                    'no support agent seeded.')
        return
    if not phone or not mpin:
        logger.error(
            '[Seeders] seed_customer: SUPPORT_SEED_PHONE and SUPPORT_SEED_MPIN must '
            'both be set in backend/.env. The support agent was not created or updated.'
        )
        return
    if not (phone.isdigit() and len(phone) == 10):
        raise RuntimeError('SUPPORT_SEED_PHONE must be a 10-digit mobile number.')
    if phone == _setting('ADMIN_SEED_PHONE'):
        raise RuntimeError('SUPPORT_SEED_PHONE must differ from ADMIN_SEED_PHONE: '
                           'one account has one role.')
    try:
        validate_mpin(mpin)
    except ValidationError as exc:
        raise RuntimeError(f'SUPPORT_SEED_MPIN: {exc.message}') from exc

    email = _setting('SUPPORT_SEED_EMAIL') or None

    existing = Users.query.filter_by(phone=phone).first()
    if existing:
        _sync(existing, mpin)
        return

    # A new SUPPORT_SEED_PHONE with the same SUPPORT_SEED_EMAIL is the agent
    # changing number, not a second agent - and the email is unique.
    holder = Users.query.filter_by(email=email).first() if email else None
    if holder:
        if not _is_agent(holder):
            logger.error(
                f'[Seeders] seed_customer: SUPPORT_SEED_EMAIL {email} belongs to a '
                'non-support account. The support agent was not created or updated.'
            )
            return
        old = holder.phone
        holder.phone = phone
        db.session.commit()
        logger.warning(
            f'[Seeders] seed_customer: support agent {email} moved from '
            f'******{old[-4:]} to ******{phone[-4:]} (SUPPORT_SEED_PHONE in .env).'
        )
        _sync(holder, mpin)
        return

    agent = Users(
        role_id=role.role_id,
        phone=phone,
        email=email,
        full_name=_setting('SUPPORT_SEED_NAME') or 'CashU Support',
        mpin_hash=hash_secret(mpin),
        kyc_tier=KYCTier.FULL,
        status=UserStatus.ACTIVE,
        is_phone_verified=True,
        is_email_verified=bool(email),
        is_active=True,
        terms_accepted=True,
        terms_accepted_at=utcnow(),
    )
    db.session.add(agent)
    db.session.flush()

    db.session.add(UserSecuritySettings(
        user_id=agent.user_id, mpin_set=True, mpin_last_changed=utcnow()
    ))
    db.session.add(NotificationPreferences(user_id=agent.user_id))
    db.session.commit()

    logger.info(f'[Seeders] seed_customer: created L1 support agent ******{phone[-4:]}.')


def _is_agent(user: Users) -> bool:
    return user.role is not None and user.role.role_name in RoleTypes.SUPPORT_ROLES


def _sync(user: Users, mpin: str):
    """Bring an existing support agent's MPIN in line with .env."""
    if not _is_agent(user):
        logger.error(
            f'[Seeders] seed_customer: ******{user.phone[-4:]} belongs to a '
            'non-support account. Set SUPPORT_SEED_PHONE to the agent\'s number.'
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
        f'[Seeders] seed_customer: support agent ******{user.phone[-4:]} MPIN updated '
        'from SUPPORT_SEED_MPIN in .env, and its lockout cleared.'
    )


if __name__ == '__main__':
    # Sync the support agent from backend/.env without starting the server:
    #     cd backend && python -m portal.seeders.seed_customer
    from portal import InitApp

    with InitApp().app().app_context():
        from portal.seeders.seed_roles import seed_roles
        seed_roles()
        seed_customer()
        print('Support agent synced from backend/.env.')
