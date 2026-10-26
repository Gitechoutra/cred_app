"""
Keep the staff accounts a seeder lists in step with the database.

seed_admin.py and seed_customer.py each hold a list of accounts and call
sync_staff() with it. Their files are the source of truth for those accounts,
and every boot (and every save of backend/.env under `python app.py`, which
restarts the dev server) brings the database in line:

    entry added                    -> account created
    phone, email or MPIN changed   -> account updated and signed out everywhere
    full_name changed              -> account updated
    entry removed                  -> account SUSPENDED and signed out
    entry put back                 -> SUSPENDED account reinstated

Each entry's `key` is how its account is found (users.seed_key), so keep it the
same for the life of the account. An account seeded before keys existed is
adopted by its phone, then its email, the first time its entry is synced.

Staff sign in like everyone else: mobile number + 6-digit MPIN on their own
portal (/admin/login, /support-desk/login). The MPIN is stored only as a
salted PBKDF2 hash, and is read from backend/.env rather than written in the
seeder files, so it never reaches git.

Guard rails:
- An account is never promoted out of, or demoted into, a member account: a
  number or email that belongs to someone outside the seeder's role is refused.
- SUSPENDED is the seeder's own status. An administrator's FROZEN or BANNED is
  left alone, and never undone by a boot.
- A badly formed entry stops the boot with a message naming it, the same as a
  bad ADMIN_SEED_PHONE always has.
"""

import logging
import os
from pathlib import Path

from dotenv import dotenv_values

from portal import db
from portal.helpers.encryption import hash_secret, verify_secret
from portal.helpers.validators import (
    ValidationError, validate_email, validate_mobile, validate_mpin,
)
from portal.models.base import utcnow
from portal.models.notifications import NotificationPreferences
from portal.models.roles import Roles
from portal.models.user_security_settings import UserSecuritySettings
from portal.models.user_sessions import SessionStatus, UserSessions
from portal.models.users import KYCTier, UserStatus, Users

logger = logging.getLogger('cashu')

#: backend/.env
ENV_FILE = Path(__file__).resolve().parents[2] / '.env'


def env(key: str) -> str:
    """
    A value from backend/.env, read from the file itself on every run.

    Not os.getenv alone: load_dotenv never overwrites a variable that is
    already set, and the debug reloader's child processes inherit the values
    the parent loaded at first start - so an edited .env would otherwise go
    unseen until a full stop and start. The process environment is still the
    fallback, for Docker, where the values arrive via env_file with no .env.
    """
    value = dotenv_values(ENV_FILE).get(key) if ENV_FILE.is_file() else None
    if value is None:
        value = os.getenv(key)
    return (value or '').strip()


class _Refused(Exception):
    """An entry that cannot be applied without touching someone else's account."""


def sync_staff(accounts, role_name, source):
    """Create, update and suspend `role_name` accounts to match `accounts`."""
    role = Roles.query.filter_by(role_name=role_name).first()
    if not role:
        raise RuntimeError(f'{source}: role {role_name} is missing - seed_roles must run first.')

    listed = set()
    counts = {'created': 0, 'updated': 0, 'suspended': 0}

    for entry in accounts:
        key = (entry.get('key') or '').strip()
        if not key:
            raise RuntimeError(f'{source}: every account needs a `key`.')
        if key in listed:
            raise RuntimeError(f'{source}: key {key} is listed twice.')
        listed.add(key)

        fields = _validated(entry, key, source)
        if fields is None:
            continue

        try:
            user = _find(key, fields, role)
            if user is None:
                _create(key, fields, role)
                counts['created'] += 1
                logger.info(f'[Seeders] {source}: created {role_name} {key} '
                            f'******{fields["phone"][-4:]}.')
            elif _update(user, key, fields, role, source):
                counts['updated'] += 1
            db.session.commit()
        except _Refused as exc:
            db.session.rollback()
            logger.error(f'[Seeders] {source}: {key}: {exc} The account was not '
                         'created or updated.')

    # Entries taken out of the file: suspend their accounts, never delete -
    # audit logs, tickets and sessions all point at them.
    removed = Users.query.filter(
        Users.role_id == role.role_id,
        Users.seed_key.isnot(None),
        Users.seed_key.notin_(listed) if listed else Users.seed_key.isnot(None),
        Users.status != UserStatus.SUSPENDED,
    ).all()
    for user in removed:
        user.status = UserStatus.SUSPENDED
        _sign_out(user, f'Removed from {source}')
        counts['suspended'] += 1
        logger.warning(f'[Seeders] {source}: {user.seed_key} ******{user.phone[-4:]} '
                       f'is no longer listed - suspended and signed out.')
    if removed:
        db.session.commit()

    return counts


def _validated(entry, key, source):
    """The entry's fields, normalised, or None when it is not configured yet."""
    phone = (entry.get('phone') or '').strip()
    mpin = (entry.get('mpin') or '').strip()

    if not phone and not mpin:
        logger.warning(f'[Seeders] {source}: {key} has no phone or MPIN set in '
                       'backend/.env - skipped.')
        return None
    if not phone or not mpin:
        logger.error(f'[Seeders] {source}: {key} needs both a phone and an MPIN in '
                     'backend/.env - skipped.')
        return None

    try:
        phone = validate_mobile(phone)
        validate_mpin(mpin)
        email = validate_email(entry['email']) if entry.get('email') else None
    except ValidationError as exc:
        raise RuntimeError(f'{source}: {key}: {exc.message}') from exc

    return {
        'phone': phone,
        'mpin': mpin,
        'email': email,
        'full_name': (entry.get('full_name') or '').strip() or None,
    }


def _find(key, fields, role):
    """The account behind `key`, adopting a pre-key account by phone or email."""
    user = Users.query.filter_by(seed_key=key).first()
    if user:
        return user

    for column, value in (('phone', fields['phone']), ('email', fields['email'])):
        if not value:
            continue
        holder = Users.query.filter(getattr(Users, column) == value).first()
        if not holder:
            continue
        if holder.role_id != role.role_id:
            raise _Refused(f'its {column} belongs to a {_role_of(holder)} account, '
                           'which a seeder never promotes.')
        if holder.seed_key:
            raise _Refused(f'its {column} belongs to the account listed as '
                           f'{holder.seed_key}.')
        return holder
    return None


def _create(key, fields, role):
    user = Users(
        role_id=role.role_id,
        seed_key=key,
        phone=fields['phone'],
        email=fields['email'],
        full_name=fields['full_name'],
        mpin_hash=hash_secret(fields['mpin']),
        kyc_tier=KYCTier.FULL,
        status=UserStatus.ACTIVE,
        is_phone_verified=True,
        is_email_verified=bool(fields['email']),
        is_active=True,
        terms_accepted=True,
        terms_accepted_at=utcnow(),
    )
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSecuritySettings(
        user_id=user.user_id, mpin_set=True, mpin_last_changed=utcnow()
    ))
    db.session.add(NotificationPreferences(user_id=user.user_id))


def _update(user, key, fields, role, source):
    """Apply the entry to an existing account. True when anything changed."""
    changes, sign_out = [], False

    if user.seed_key != key:
        user.seed_key = key
        changes.append('key')

    if user.role_id != role.role_id:
        # Listed in the file but given another role on the Staff screen. The
        # file wins, and says so - edit the file to change a seeded account.
        logger.warning(f'[Seeders] {source}: {key} had role {_role_of(user)}; '
                       f'restored to {role.role_name} as the file lists it.')
        user.role_id = role.role_id
        changes.append('role')
        sign_out = True

    if user.phone != fields['phone']:
        _ensure_free('phone', fields['phone'], user)
        user.phone = fields['phone']
        changes.append('phone')
        sign_out = True

    if (user.email or None) != fields['email']:
        if fields['email']:
            _ensure_free('email', fields['email'], user)
        user.email = fields['email']
        user.is_email_verified = bool(fields['email'])
        changes.append('email')
        sign_out = True

    if fields['full_name'] and user.full_name != fields['full_name']:
        user.full_name = fields['full_name']
        changes.append('name')

    if not user.mpin_hash or not verify_secret(fields['mpin'], user.mpin_hash):
        user.mpin_hash = hash_secret(fields['mpin'])
        user.failed_auth_attempts = 0
        user.locked_until = None
        security = _security(user)
        security.mpin_set = True
        security.mpin_last_changed = utcnow()
        changes.append('MPIN')
        sign_out = True

    if user.status == UserStatus.SUSPENDED:
        user.status = UserStatus.ACTIVE
        changes.append('reinstated')

    if sign_out:
        _sign_out(user, f'Credentials changed in {source}')

    if changes:
        logger.warning(f'[Seeders] {source}: {key} ******{user.phone[-4:]} updated '
                       f'({", ".join(changes)})' + (', signed out everywhere.' if sign_out else '.'))
    return bool(changes)


def _ensure_free(column, value, user):
    holder = Users.query.filter(getattr(Users, column) == value,
                                Users.user_id != user.user_id).first()
    if holder:
        raise _Refused(f'its new {column} already belongs to another account.')


def _security(user):
    security = UserSecuritySettings.query.filter_by(user_id=user.user_id).first()
    if not security:
        security = UserSecuritySettings(user_id=user.user_id)
        db.session.add(security)
    return security


def _sign_out(user, reason):
    """Revoke every session, so tokens issued before the change stop working."""
    _security(user).sessions_invalidated_at = utcnow()
    UserSessions.query.filter_by(
        user_id=user.user_id, status=SessionStatus.ACTIVE,
    ).update({'status': SessionStatus.REVOKED, 'revoked_at': utcnow(),
              'revoked_reason': reason})


def _role_of(user):
    return user.role.role_name if user.role else 'unknown'
