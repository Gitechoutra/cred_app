"""
portal/helpers/otp.py
=====================
OTP issuance and verification (PRD FR-001).

    6 digits, 3-minute lifetime, verified against a PBKDF2 hash
    3 resends per 15-minute rolling window per phone and per IP
    3 verification attempts, then the code is burned
    3 failed authentications lock the account for 30 minutes

The plaintext code exists only long enough to hand to the SMS gateway. It is
never stored, never logged, and never returned in an API response outside DEBUG.
"""

import secrets
from datetime import timedelta

from flask import current_app

from portal import db
from portal.helpers import rate_limit, settings
from portal.helpers.encryption import hash_secret, verify_secret
from portal.helpers.settings import Key
from portal.models.base import utcnow
from portal.models.otp_verifications import (
    OTPPurpose, OTPStatus, OTPVerifications,
)


class OTPError(Exception):
    def __init__(self, message: str, code: str = 'OTP_INVALID', retry_after: int = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.retry_after = retry_after


def _generate(length: int) -> str:
    """
    Cryptographically random digits.

    secrets, not random: the latter is a Mersenne Twister whose future output
    is predictable from a handful of past values, which for an auth code is
    fatal.
    """
    return ''.join(secrets.choice('0123456789') for _ in range(length))


def issue(
    phone: str,
    purpose: str = OTPPurpose.LOGIN,
    user_id: str = None,
    ip: str = None,
    device_uuid: str = None,
) -> dict:
    """
    Create and dispatch an OTP.

    Rate limited per phone and per IP: per-phone alone lets one host spray codes
    across many numbers, and per-IP alone lets a botnet hammer one number.
    """
    length = settings.get_int(Key.OTP_LENGTH)
    ttl_seconds = settings.get_int(Key.OTP_EXPIRY_SECONDS)
    max_resends = settings.get_int(Key.OTP_MAX_RESENDS_PER_WINDOW)
    window_minutes = settings.get_int(Key.OTP_RESEND_WINDOW_MINUTES)
    window_seconds = window_minutes * 60

    try:
        rate_limit.hit(
            rate_limit.phone_scope('otp', phone), max_resends, window_seconds
        )
        if ip:
            rate_limit.hit(
                rate_limit.ip_scope('otp', ip), max_resends * 3, window_seconds
            )
    except rate_limit.RateLimitExceeded as exc:
        raise OTPError(
            f'Too many OTP requests. Please try again in '
            f'{max(1, exc.retry_after_seconds // 60)} minute(s).',
            code='OTP_RATE_LIMITED',
            retry_after=exc.retry_after_seconds,
        )

    # Any earlier live code for this phone and purpose is burned, so only the
    # most recent one works. Otherwise a user with three unread SMS could
    # authenticate with a code issued before a suspicious-activity lock.
    OTPVerifications.query.filter_by(
        phone=phone, purpose=purpose, status=OTPStatus.PENDING
    ).update({'status': OTPStatus.EXPIRED})

    code = _generate(length)

    record = OTPVerifications(
        user_id=user_id,
        phone=phone,
        otp_hash=hash_secret(code),
        purpose=purpose,
        status=OTPStatus.PENDING,
        expires_at=utcnow() + timedelta(seconds=ttl_seconds),
        request_ip=ip,
        device_uuid=device_uuid,
    )
    db.session.add(record)
    db.session.commit()

    from portal.helpers import sms
    sms.send_otp(phone, code, purpose=purpose, ttl_seconds=ttl_seconds)

    response = {
        'otp_id': record.otp_id,
        'expires_at': record.expires_at.isoformat(),
        'expires_in_seconds': ttl_seconds,
        'length': length,
        'resends_remaining': max(
            0, max_resends - rate_limit.peek(
                rate_limit.phone_scope('otp', phone), window_seconds
            )
        ),
    }

    # Development affordance: without a live DLT-registered SMS gateway there is
    # no other way to complete a login locally. Guarded on DEBUG so it can never
    # leak from a deployed environment.
    if current_app.debug:
        response['debug_otp'] = code
        current_app.logger.info(f'[otp] DEV code for {phone}: {code}')

    return response


def verify(
    phone: str,
    code: str,
    purpose: str = OTPPurpose.LOGIN,
) -> OTPVerifications:
    """
    Check a submitted code.

    Returns the consumed record on success. Raises OTPError with the exact
    user-facing message the PRD specifies for each failure.
    """
    record = OTPVerifications.query.filter_by(
        phone=phone, purpose=purpose, status=OTPStatus.PENDING
    ).order_by(OTPVerifications.created_on.desc()).first()

    if not record:
        raise OTPError(
            'No active OTP found. Please request a new one.', code='OTP_INVALID'
        )

    if utcnow() > record.expires_at:
        record.status = OTPStatus.EXPIRED
        db.session.commit()
        # PRD FR-001 specifies this wording verbatim.
        raise OTPError('OTP expired. Request a new OTP.', code='OTP_EXPIRED')

    if record.attempts >= record.max_attempts:
        record.status = OTPStatus.FAILED
        db.session.commit()
        raise OTPError(
            'Too many incorrect attempts. Please request a new OTP.',
            code='OTP_MAX_RETRY',
        )

    if not verify_secret(code, record.otp_hash):
        record.attempts += 1
        remaining = record.max_attempts - record.attempts

        if remaining <= 0:
            record.status = OTPStatus.FAILED
            db.session.commit()
            raise OTPError(
                'Too many incorrect attempts. Please request a new OTP.',
                code='OTP_MAX_RETRY',
            )

        db.session.commit()
        raise OTPError(
            f'Incorrect OTP. {remaining} attempt(s) remaining.', code='OTP_INVALID'
        )

    # Single use: consumed the moment it succeeds, so a replayed code fails.
    record.status = OTPStatus.VERIFIED
    record.verified_at = utcnow()
    db.session.commit()

    return record


def purge_expired(older_than_hours: int = 24) -> int:
    """Janitor sweep - the MySQL stand-in for a Redis TTL."""
    cutoff = utcnow() - timedelta(hours=older_than_hours)
    deleted = OTPVerifications.query.filter(
        OTPVerifications.expires_at < cutoff
    ).delete()
    db.session.commit()
    return deleted
