"""
Authentication (PRD FR-001).

Mobile-first, passwordless: phone + OTP establishes identity, a 6-digit MPIN
unlocks the app afterwards. Access tokens live 15 minutes; refresh tokens live
30 days and rotate on every use.
"""

from datetime import timedelta

from flask import current_app
from flask_jwt_extended import get_jwt, jwt_required
from flask_restx import Resource, reqparse

from portal import db
from portal.helpers import audit, otp as otp_helper, rate_limit, settings
from portal.helpers.encryption import hash_secret, verify_secret
from portal.helpers.helpers import ErrorCode, client_ip, device_uuid, failure, success, user_agent
from portal.helpers.jwt import current_user, issue_tokens
from portal.helpers.settings import Key
from portal.helpers.validators import (
    ValidationError, validate_email, validate_mobile, validate_mpin, validate_otp,
)
from portal.models.base import utcnow
from portal.models.device_bindings import DeviceBindings
from portal.models.login_history import LoginHistory, LoginStatus
from portal.models.notifications import NotificationEvent
from portal.models.otp_verifications import OTPPurpose
from portal.models.roles import RoleTypes, Roles
from portal.models.user_security_settings import UserSecuritySettings
from portal.models.user_sessions import SessionStatus, UserSessions
from portal.models.users import KYCTier, UserStatus, Users

from . import logger, ns

send_otp_parser = reqparse.RequestParser()
send_otp_parser.add_argument('phone', type=str, required=True, location='json')
send_otp_parser.add_argument('purpose', type=str, required=False, location='json',
                             default=OTPPurpose.LOGIN)

verify_otp_parser = reqparse.RequestParser()
verify_otp_parser.add_argument('phone', type=str, required=True, location='json')
verify_otp_parser.add_argument('otp', type=str, required=True, location='json')
verify_otp_parser.add_argument('purpose', type=str, required=False, location='json',
                               default=OTPPurpose.LOGIN)
verify_otp_parser.add_argument('device_name', type=str, required=False, location='json')
verify_otp_parser.add_argument('platform', type=str, required=False, location='json')
verify_otp_parser.add_argument('portal', type=str, required=False, location='json')

register_parser = reqparse.RequestParser()
register_parser.add_argument('full_name', type=str, required=True, location='json')
register_parser.add_argument('email', type=str, required=False, location='json')
register_parser.add_argument('date_of_birth', type=str, required=False, location='json')
register_parser.add_argument('terms_accepted', type=bool, required=True, location='json')

mpin_parser = reqparse.RequestParser()
mpin_parser.add_argument('mpin', type=str, required=True, location='json')

mpin_login_parser = reqparse.RequestParser()
mpin_login_parser.add_argument('phone', type=str, required=True, location='json')
mpin_login_parser.add_argument('mpin', type=str, required=True, location='json')
mpin_login_parser.add_argument('portal', type=str, required=False, location='json')

reset_request_parser = reqparse.RequestParser()
reset_request_parser.add_argument('phone', type=str, required=True, location='json')

reset_confirm_parser = reqparse.RequestParser()
reset_confirm_parser.add_argument('phone', type=str, required=True, location='json')
reset_confirm_parser.add_argument('otp', type=str, required=True, location='json')
reset_confirm_parser.add_argument('mpin', type=str, required=True, location='json')

email_token_parser = reqparse.RequestParser()
email_token_parser.add_argument('token', type=str, required=True, location='json')

#: Display names for the portals, used in "please use the X sign-in".
_PORTAL_NAMES = {'USER': 'customer', 'ADMIN': 'admin', 'SUPPORT': 'customer support'}


def _portal_for(role_name: str) -> str:
    for portal, roles in RoleTypes.PORTALS.items():
        if role_name in roles:
            return portal
    return 'USER'


def _portal_refusal(user, portal):
    """
    Refuse a sign-in made through the wrong portal, or None to allow it.

    Called only after the credentials are proven, so naming the right portal
    tells nothing to someone guessing numbers. This is a convenience boundary;
    the real one is the role check on every endpoint. A request that names no
    portal (older clients, scripts) is not refused.
    """
    if not portal:
        return None
    portal = portal.upper()
    if portal not in RoleTypes.PORTALS:
        return failure(ErrorCode.VALIDATION_ERROR, 'Unknown sign-in portal.', 400)
    role_name = user.role.role_name if user.role else RoleTypes.NORMAL_USER
    if role_name in RoleTypes.PORTALS[portal]:
        return None
    _log_login(user.phone, LoginStatus.FAILED_MPIN, user.user_id,
               f'Wrong portal: {role_name} via {portal}')
    right = _portal_for(role_name)
    return failure(
        'WRONG_PORTAL',
        'This account cannot sign in here. Please use the '
        f'{_PORTAL_NAMES[right]} sign-in.',
        403, details={'portal': right},
    )


def _log_login(phone, status, user_id=None, reason=None):
    db.session.add(LoginHistory(
        user_id=user_id,
        phone=phone,
        status=status,
        ip_address=client_ip(),
        user_agent=user_agent(),
        device_uuid=device_uuid(),
        failure_reason=reason,
    ))
    db.session.commit()


def _locked_response(user):
    remaining = int((user.locked_until - utcnow()).total_seconds() // 60) + 1
    return failure(
        ErrorCode.ACCOUNT_LOCKED,
        f'Too many failed attempts. Please try again in {remaining} minute(s).',
        423,
        recovery='Wait for the lockout to expire, or contact support.',
    )


def _is_locked(user) -> bool:
    return bool(user.locked_until and user.locked_until > utcnow())


def _register_failure(user, status):
    """
    Count a failed authentication and lock the account at the threshold.

    PRD FR-001: three failures locks auth for 30 minutes.
    """
    max_attempts = settings.get_int(Key.AUTH_MAX_FAILED_ATTEMPTS)
    lockout_minutes = settings.get_int(Key.AUTH_LOCKOUT_MINUTES)

    user.failed_auth_attempts = (user.failed_auth_attempts or 0) + 1
    if user.failed_auth_attempts >= max_attempts:
        user.locked_until = utcnow() + timedelta(minutes=lockout_minutes)
        user.failed_auth_attempts = 0
        db.session.commit()
        _log_login(user.phone, LoginStatus.LOCKED, user.user_id, 'Max attempts exceeded')
        return True

    db.session.commit()
    _log_login(user.phone, status, user.user_id)
    return False


def _bind_device(user, device_name=None, platform=None):
    """
    Record the device and report whether it is new.

    A previously unseen device is a security-relevant event (PRD 14.1
    "Suspicious Login / New Device"), so the caller notifies on it.
    """
    uuid_value = device_uuid()
    if not uuid_value:
        return None, False

    binding = DeviceBindings.query.filter_by(
        user_id=user.user_id, device_uuid=uuid_value
    ).first()

    is_new = binding is None
    if is_new:
        binding = DeviceBindings(
            user_id=user.user_id,
            device_uuid=uuid_value,
            device_name=device_name,
            platform=platform,
            # The first device a user registers on is trusted implicitly; every
            # later one has to be earned by an OTP challenge.
            is_trusted=not user.devices.count(),
        )
        db.session.add(binding)

    binding.last_seen_at = utcnow()
    db.session.commit()
    return binding, is_new


def _open_session(user, device_binding=None):
    import secrets

    raw_token = secrets.token_urlsafe(48)
    session = UserSessions(
        user_id=user.user_id,
        refresh_token_hash=hash_secret(raw_token),
        device_uuid=device_uuid() or None,
        device_name=device_binding.device_name if device_binding else None,
        ip_address=client_ip(),
        user_agent=user_agent(),
        status=SessionStatus.ACTIVE,
        expires_at=utcnow() + timedelta(
            days=settings.get_int('JWT_REFRESH_TOKEN_EXPIRES_DAYS') or 30
        ),
        last_used_at=utcnow(),
    )
    db.session.add(session)
    db.session.commit()
    return session


def _auth_payload(user, session):
    access_token, refresh_token = issue_tokens(
        user, session_id=session.session_id, device_uuid=device_uuid()
    )
    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'expires_in': int(
            current_app.config['JWT_ACCESS_TOKEN_EXPIRES'].total_seconds()
        ),
        'user': {
            'user_id': user.user_id,
            'phone': user.phone,
            'full_name': user.full_name,
            'email': user.email,
            'kyc_tier': user.kyc_tier,
            'status': user.status,
            'role': user.role.role_name if user.role else None,
            'mpin_set': bool(user.mpin_hash),
            'biometric_enabled': user.biometric_enabled,
            'is_profile_complete': bool(user.full_name),
        },
    }


@ns.route('/otp/send')
class SendOTP(Resource):
    @ns.doc('send_otp')
    def post(self):
        """Send a 6-digit OTP to an Indian mobile number."""
        args = send_otp_parser.parse_args()

        try:
            phone = validate_mobile(args['phone'])
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        # Public endpoint: 5 requests/min per IP (PRD 17.1).
        try:
            rate_limit.hit(rate_limit.ip_scope('auth', client_ip()), 5, 60)
        except rate_limit.RateLimitExceeded as exc:
            return failure(
                ErrorCode.ERR_011_VELOCITY_ABUSE, exc.message, 429,
                details={'retry_after_seconds': exc.retry_after_seconds},
            )

        if not settings.flag_enabled(settings.Flag.NEW_USER_REGISTRATION):
            existing = Users.query.filter_by(phone=phone).first()
            if not existing:
                return failure(
                    ErrorCode.FEATURE_DISABLED,
                    'New registrations are temporarily closed.',
                    403,
                )

        user = Users.query.filter_by(phone=phone).first()

        if user and _is_locked(user):
            return _locked_response(user)

        if user and user.status in (UserStatus.SUSPENDED, UserStatus.BANNED):
            return failure(
                ErrorCode.FORBIDDEN,
                'Your account has been suspended. Please contact support.',
                403,
            )

        try:
            result = otp_helper.issue(
                phone,
                purpose=args['purpose'],
                user_id=user.user_id if user else None,
                ip=client_ip(),
                device_uuid=device_uuid(),
            )
        except otp_helper.OTPError as exc:
            return failure(
                exc.code, exc.message, 429,
                details={'retry_after_seconds': exc.retry_after},
            )

        return success(
            {**result, 'is_new_user': user is None},
            'OTP sent successfully.',
        )


@ns.route('/otp/verify')
class VerifyOTP(Resource):
    @ns.doc('verify_otp')
    def post(self):
        """
        Verify an OTP and open a session.

        A first-time number is provisioned here with PENDING status; the client
        then completes the profile through /register.
        """
        args = verify_otp_parser.parse_args()

        try:
            phone = validate_mobile(args['phone'])
            code = validate_otp(args['otp'])
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        user = Users.query.filter_by(phone=phone).first()
        portal = (args.get('portal') or '').upper() or None

        if user and _is_locked(user):
            return _locked_response(user)

        try:
            otp_helper.verify(phone, code, purpose=args['purpose'])
        except otp_helper.OTPError as exc:
            if user:
                locked = _register_failure(user, LoginStatus.FAILED_OTP)
                if locked:
                    return _locked_response(user)
            else:
                _log_login(phone, LoginStatus.FAILED_OTP, reason=exc.message)
            return failure(exc.code, exc.message, 400)

        is_new_user = user is None

        # Staff accounts are created by an administrator, never by an OTP.
        if is_new_user and portal in ('ADMIN', 'SUPPORT'):
            return failure(
                ErrorCode.UNAUTHORIZED,
                'There is no staff account for this number.', 401,
            )
        if not is_new_user:
            refusal = _portal_refusal(user, portal)
            if refusal:
                return refusal

        if is_new_user:
            role = Roles.query.filter_by(role_name=RoleTypes.NORMAL_USER).first()
            if not role:
                logger.error('NORMAL_USER role missing; seeders have not run.')
                return failure(
                    ErrorCode.INTERNAL_ERROR,
                    'Account setup is unavailable. Please try again shortly.',
                    500,
                )

            user = Users(
                role_id=role.role_id,
                phone=phone,
                status=UserStatus.PENDING,
                kyc_tier=KYCTier.NONE,
                is_phone_verified=True,
            )
            db.session.add(user)
            db.session.flush()

            db.session.add(UserSecuritySettings(user_id=user.user_id))

            from portal.models.notifications import NotificationPreferences
            db.session.add(NotificationPreferences(user_id=user.user_id))
            db.session.commit()

            audit.record(
                action='USER_REGISTERED',
                entity_type='Users',
                entity_id=user.user_id,
                actor_user_id=str(user.user_id),
                after={'phone': user.masked_phone()},
            )
        else:
            user.is_phone_verified = True
            user.failed_auth_attempts = 0
            user.locked_until = None
            user.last_login = utcnow()
            db.session.commit()

        binding, is_new_device = _bind_device(
            user, args.get('device_name'), args.get('platform')
        )

        if is_new_device and not is_new_user:
            from portal.helpers import notify
            notify.dispatch(user, NotificationEvent.SUSPICIOUS_LOGIN, {
                'device': args.get('device_name') or 'a new device',
                'location': client_ip(),
            })

        session = _open_session(user, binding)
        _log_login(phone, LoginStatus.SUCCESS, user.user_id)

        payload = _auth_payload(user, session)
        payload['is_new_user'] = is_new_user
        payload['requires_profile'] = not bool(user.full_name)
        payload['requires_mpin'] = not bool(user.mpin_hash)

        return success(payload, 'Verified successfully.')


@ns.route('/register')
class CompleteRegistration(Resource):
    @ns.doc('complete_registration', security='Bearer')
    @jwt_required()
    def post(self):
        """Capture the legal name and terms acceptance after OTP verification."""
        args = register_parser.parse_args()
        user = current_user()

        if not user:
            return failure(ErrorCode.UNAUTHORIZED, 'Account not found.', 401)

        if not args['terms_accepted']:
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'You must accept the Terms of Service to continue.',
                400,
            )

        try:
            from portal.helpers.validators import sanitize_text, validate_date

            user.full_name = sanitize_text(args['full_name'], 200)
            if not user.full_name:
                raise ValidationError('Enter your full name as per PAN.', 'full_name')

            if args.get('email'):
                user.email = validate_email(args['email'])
            if args.get('date_of_birth'):
                user.date_of_birth = validate_date(
                    args['date_of_birth'], 'date_of_birth'
                )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        user.terms_accepted = True
        user.terms_accepted_at = utcnow()
        user.status = UserStatus.ACTIVE
        db.session.commit()

        audit.record(
            action='PROFILE_COMPLETED',
            entity_type='Users',
            entity_id=user.user_id,
            actor_user_id=str(user.user_id),
        )

        return success({
            'user_id': user.user_id,
            'full_name': user.full_name,
            'status': user.status,
            'requires_mpin': not bool(user.mpin_hash),
        }, 'Registration completed.')


@ns.route('/mpin/set')
class SetMPIN(Resource):
    @ns.doc('set_mpin', security='Bearer')
    @jwt_required()
    def post(self):
        """Set or change the 6-digit MPIN."""
        args = mpin_parser.parse_args()
        user = current_user()

        if not user:
            return failure(ErrorCode.UNAUTHORIZED, 'Account not found.', 401)

        try:
            mpin = validate_mpin(args['mpin'])
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        user.mpin_hash = hash_secret(mpin)
        settings_row = user.security_settings
        if settings_row:
            settings_row.mpin_set = True
            settings_row.mpin_last_changed = utcnow()
        db.session.commit()

        audit.record(
            action='MPIN_SET',
            entity_type='Users',
            entity_id=user.user_id,
            actor_user_id=str(user.user_id),
        )

        return success({'mpin_set': True}, 'MPIN set successfully.')


@ns.route('/mpin/verify')
class VerifyMPIN(Resource):
    @ns.doc('verify_mpin')
    def post(self):
        """Unlock with phone + MPIN, skipping the OTP round trip."""
        args = mpin_login_parser.parse_args()

        try:
            phone = validate_mobile(args['phone'])
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        try:
            rate_limit.hit(rate_limit.ip_scope('auth', client_ip()), 5, 60)
        except rate_limit.RateLimitExceeded as exc:
            return failure(ErrorCode.ERR_011_VELOCITY_ABUSE, exc.message, 429)

        user = Users.query.filter_by(phone=phone).first()

        # Same response whether the number is unknown or the MPIN is wrong, so
        # this endpoint cannot be used to enumerate registered users.
        if not user or not user.mpin_hash:
            _log_login(phone, LoginStatus.FAILED_MPIN, reason='Unknown or MPIN unset')
            return failure(
                ErrorCode.MPIN_INVALID, 'Incorrect phone number or MPIN.', 401
            )

        if _is_locked(user):
            return _locked_response(user)

        if not verify_secret(args['mpin'], user.mpin_hash):
            locked = _register_failure(user, LoginStatus.FAILED_MPIN)
            if locked:
                return _locked_response(user)
            # Deliberately the *same* string the unknown-number branch above
            # returns. It used to name the attempts remaining, which was a
            # helpful touch that also turned this endpoint into an account
            # enumerator: only a registered number could produce a countdown,
            # so anyone could test a list of phone numbers against it. The
            # remaining count is still enforced - the lockout below fires - it
            # is just no longer broadcast to an unauthenticated caller.
            remaining = settings.get_int(Key.AUTH_MAX_FAILED_ATTEMPTS) - (
                user.failed_auth_attempts or 0
            )
            logger.info(
                f'[auth] failed MPIN for {phone[-4:]}; {max(0, remaining)} left'
            )
            return failure(
                ErrorCode.MPIN_INVALID, 'Incorrect phone number or MPIN.', 401
            )

        if user.status in (UserStatus.SUSPENDED, UserStatus.BANNED):
            return failure(
                ErrorCode.FORBIDDEN,
                'Your account has been suspended. Please contact support.',
                403,
            )

        refusal = _portal_refusal(user, args.get('portal'))
        if refusal:
            return refusal

        user.failed_auth_attempts = 0
        user.locked_until = None
        user.last_login = utcnow()
        db.session.commit()

        binding, _ = _bind_device(user)
        session = _open_session(user, binding)
        _log_login(phone, LoginStatus.SUCCESS, user.user_id)

        return success(_auth_payload(user, session), 'Signed in successfully.')


@ns.route('/refresh')
class RefreshToken(Resource):
    @ns.doc('refresh_token', security='Bearer')
    @jwt_required(refresh=True)
    def post(self):
        """
        Rotate the token pair.

        PRD FR-001 rotates the refresh token on every use, so a stolen token is
        usable at most once before the legitimate client's next refresh
        invalidates it.
        """
        user = current_user()
        if not user:
            return failure(ErrorCode.UNAUTHORIZED, 'Account not found.', 401)

        if user.status in (UserStatus.SUSPENDED, UserStatus.BANNED, UserStatus.FROZEN):
            return failure(
                ErrorCode.FORBIDDEN, 'This account is not currently active.', 403
            )

        session_id = get_jwt().get('session_id')
        session = UserSessions.query.filter_by(session_id=session_id).first()

        if not session or session.status != SessionStatus.ACTIVE:
            return failure(
                ErrorCode.UNAUTHORIZED,
                'This session is no longer valid. Please sign in again.',
                401,
            )

        if session.expires_at < utcnow():
            session.status = SessionStatus.EXPIRED
            db.session.commit()
            return failure(
                ErrorCode.UNAUTHORIZED,
                'Your session has expired. Please sign in again.',
                401,
            )

        session.last_used_at = utcnow()
        db.session.commit()

        return success(_auth_payload(user, session), 'Token refreshed.')


@ns.route('/logout')
class Logout(Resource):
    @ns.doc('logout', security='Bearer')
    @jwt_required()
    def post(self):
        """Revoke the current session."""
        session_id = get_jwt().get('session_id')

        if session_id:
            session = UserSessions.query.filter_by(session_id=session_id).first()
            if session:
                session.status = SessionStatus.REVOKED
                session.revoked_at = utcnow()
                session.revoked_reason = 'User signed out'
                db.session.commit()

        return success(None, 'Signed out successfully.')


@ns.route('/sessions')
class Sessions(Resource):
    @ns.doc('list_sessions', security='Bearer')
    @jwt_required()
    def get(self):
        """Active sessions for this account (PRD FR-012 session kill switch)."""
        user = current_user()
        current_session_id = get_jwt().get('session_id')

        sessions = UserSessions.query.filter_by(
            user_id=user.user_id, status=SessionStatus.ACTIVE
        ).order_by(UserSessions.last_used_at.desc()).all()

        return success([{
            'session_id': s.session_id,
            'device_name': s.device_name,
            'ip_address': s.ip_address,
            'last_used_at': s.last_used_at.isoformat() if s.last_used_at else None,
            'created_on': s.created_on.isoformat(),
            'is_current': s.session_id == current_session_id,
        } for s in sessions])

    @ns.doc('revoke_all_sessions', security='Bearer')
    @jwt_required()
    def delete(self):
        """
        Sign out everywhere.

        Stamps sessions_invalidated_at so tokens already issued stop working
        immediately, rather than remaining valid until they expire.
        """
        user = current_user()

        UserSessions.query.filter_by(
            user_id=user.user_id, status=SessionStatus.ACTIVE
        ).update({
            'status': SessionStatus.REVOKED,
            'revoked_at': utcnow(),
            'revoked_reason': 'User revoked all sessions',
        })

        if user.security_settings:
            user.security_settings.sessions_invalidated_at = utcnow()
        db.session.commit()

        audit.record(
            action='ALL_SESSIONS_REVOKED',
            entity_type='Users',
            entity_id=user.user_id,
            actor_user_id=str(user.user_id),
        )

        return success(None, 'All sessions have been signed out.')


# -- Forgot MPIN -------------------------------------------------------------

@ns.route('/mpin/reset/request')
class MPINResetRequest(Resource):
    @ns.doc('mpin_reset_request')
    def post(self):
        """
        Send an MPIN-reset OTP to the registered mobile.

        Answers the same whether or not the number has an account, so it
        cannot be used to find out who is registered.
        """
        args = reset_request_parser.parse_args()
        try:
            phone = validate_mobile(args['phone'])
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        try:
            rate_limit.hit(rate_limit.ip_scope('auth', client_ip()), 5, 60)
        except rate_limit.RateLimitExceeded as exc:
            return failure(ErrorCode.ERR_011_VELOCITY_ABUSE, exc.message, 429,
                           details={'retry_after_seconds': exc.retry_after_seconds})

        data = {}
        user = Users.query.filter_by(phone=phone).first()
        if user and user.mpin_hash and user.status not in (
                UserStatus.SUSPENDED, UserStatus.BANNED):
            try:
                result = otp_helper.issue(
                    phone, purpose=OTPPurpose.MPIN_RESET, user_id=user.user_id,
                    ip=client_ip(), device_uuid=device_uuid(),
                )
            except otp_helper.OTPError as exc:
                return failure(exc.code, exc.message, 429,
                               details={'retry_after_seconds': exc.retry_after})
            data = {k: v for k, v in result.items()
                    if k in ('expires_in_seconds', 'length', 'resends_remaining',
                             'debug_otp')}

        return success(data, 'If this number is registered, we have sent it an OTP.')


@ns.route('/mpin/reset/confirm')
class MPINResetConfirm(Resource):
    @ns.doc('mpin_reset_confirm')
    def post(self):
        """
        Set a new MPIN with the reset OTP.

        Signs the account out everywhere: whoever could not get in may not be
        the only person who knew the old MPIN.
        """
        args = reset_confirm_parser.parse_args()
        try:
            phone = validate_mobile(args['phone'])
            code = validate_otp(args['otp'])
            mpin = validate_mpin(args['mpin'])
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        user = Users.query.filter_by(phone=phone).first()
        try:
            otp_helper.verify(phone, code, purpose=OTPPurpose.MPIN_RESET)
        except otp_helper.OTPError as exc:
            if user:
                _register_failure(user, LoginStatus.FAILED_OTP)
            return failure(exc.code, exc.message, 400)
        if not user:
            return failure(ErrorCode.OTP_INVALID, 'The OTP is incorrect.', 400)

        user.mpin_hash = hash_secret(mpin)
        user.failed_auth_attempts = 0
        user.locked_until = None
        if user.security_settings:
            user.security_settings.mpin_set = True
            user.security_settings.mpin_last_changed = utcnow()
            user.security_settings.sessions_invalidated_at = utcnow()
        UserSessions.query.filter_by(
            user_id=user.user_id, status=SessionStatus.ACTIVE,
        ).update({'status': SessionStatus.REVOKED, 'revoked_at': utcnow(),
                  'revoked_reason': 'MPIN reset'})
        db.session.commit()

        audit.record(action='MPIN_RESET', entity_type='Users',
                     entity_id=user.user_id, actor_user_id=str(user.user_id))

        role_name = user.role.role_name if user.role else RoleTypes.NORMAL_USER
        return success({'portal': _portal_for(role_name)},
                       'Your MPIN has been reset. Please sign in with the new MPIN.')


# -- Email verification ------------------------------------------------------

_EMAIL_SALT = 'cashu-email-verify'
_EMAIL_MAX_AGE = 24 * 3600


def _email_serializer():
    from itsdangerous import URLSafeTimedSerializer
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=_EMAIL_SALT)


@ns.route('/email/verify/request')
class EmailVerifyRequest(Resource):
    @ns.doc('email_verify_request', security='Bearer')
    @jwt_required()
    def post(self):
        """Email a signed, 24-hour verification link to the address on file."""
        from portal.helpers import email as email_helper

        user = current_user()
        if not user or not user.email:
            return failure(ErrorCode.VALIDATION_ERROR,
                           'Add an email address to your profile first.', 400)
        if user.is_email_verified:
            return failure(ErrorCode.CONFLICT, 'Your email is already verified.', 409)

        try:
            rate_limit.hit(f'email_verify:user:{user.user_id}', 3, 3600)
        except rate_limit.RateLimitExceeded as exc:
            return failure(ErrorCode.ERR_011_VELOCITY_ABUSE,
                           'Too many verification emails. Please try again later.',
                           429, details={'retry_after_seconds': exc.retry_after_seconds})

        token = _email_serializer().dumps({'u': user.user_id, 'e': user.email})
        base = (current_app.config.get('FRONTEND_BASE_URL') or '').rstrip('/')
        link = f'{base}/verify-email?token={token}'
        sent = email_helper.send(
            user.email, 'Verify your email for CashU',
            f'Hi {user.full_name or "there"},\n\nConfirm this is your email '
            f'address:\n{link}\n\nThe link expires in 24 hours. If you did not '
            'ask for this, ignore this email.',
        )
        if not sent.get('ok'):
            return failure(ErrorCode.PROVIDER_ERROR,
                           'We could not send the email right now. Please try again.',
                           503)

        data = {'sent_to': user.email, 'delivery': sent.get('provider')}
        # Without SMTP the email is only logged. In a debug build the link is
        # returned so the flow can be finished locally, like debug_otp.
        if sent.get('provider') == 'LOG' and current_app.debug:
            data['debug_link'] = link
        return success(data, f'We sent a verification link to {user.email}.')


@ns.route('/email/verify')
class EmailVerify(Resource):
    @ns.doc('email_verify')
    def post(self):
        """Confirm an email address from the link's token."""
        from itsdangerous import BadSignature, SignatureExpired

        args = email_token_parser.parse_args()
        try:
            payload = _email_serializer().loads(args['token'], max_age=_EMAIL_MAX_AGE)
        except SignatureExpired:
            return failure('TOKEN_EXPIRED', 'This link has expired. Request a new '
                           'one from your profile.', 400)
        except BadSignature:
            return failure(ErrorCode.VALIDATION_ERROR, 'This link is not valid.', 400)

        user = Users.query.filter_by(user_id=payload.get('u')).first()
        if not user or (user.email or '').lower() != (payload.get('e') or '').lower():
            return failure(ErrorCode.VALIDATION_ERROR,
                           'This link is for an email address no longer on the '
                           'account.', 400)

        if not user.is_email_verified:
            user.is_email_verified = True
            db.session.commit()
            audit.record(action='EMAIL_VERIFIED', entity_type='Users',
                         entity_id=user.user_id, actor_user_id=str(user.user_id))

        return success({'email': user.email, 'verified': True}, 'Email verified.')
