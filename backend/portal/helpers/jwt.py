"""
portal/helpers/jwt.py
=====================
JWT wiring and the role/KYC decorators every protected route uses.

PRD FR-001: access token 15 minutes, refresh token 30 days rotated on every
use. PRD 15: four RBAC tiers. PRD 18: Full KYC gates transfers above 10,000.
"""

import functools
from datetime import datetime, timezone

from flask import current_app
from flask_jwt_extended import (
    JWTManager, create_access_token, create_refresh_token,
    get_jwt, get_jwt_identity, verify_jwt_in_request,
)

from portal.helpers.helpers import ErrorCode, failure

jwt_manager = JWTManager()


class Token:
    """Initializes JWTManager on the app and registers its error handlers."""

    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        jwt_manager.init_app(app)
        _register_handlers(jwt_manager)
        app.logger.info('Initialized JWT')


def _register_handlers(manager: JWTManager):
    """
    Uniform auth failures.

    flask-jwt-extended's defaults return a shape unlike the rest of the API, so
    the client would need a second error parser just for auth.
    """

    @manager.expired_token_loader
    def _expired(_header, _payload):
        return failure(
            ErrorCode.UNAUTHORIZED,
            'Your session has expired. Please sign in again.',
            401,
        )

    @manager.invalid_token_loader
    def _invalid(reason):
        return failure(ErrorCode.UNAUTHORIZED, 'Invalid authentication token.', 401,
                       details=str(reason))

    @manager.unauthorized_loader
    def _missing(reason):
        return failure(ErrorCode.UNAUTHORIZED, 'Authentication required.', 401,
                       details=str(reason))

    @manager.revoked_token_loader
    def _revoked(_header, _payload):
        return failure(ErrorCode.UNAUTHORIZED, 'This session has been revoked.', 401)


# ── Token issuance ─────────────────────────────────────────────────────────

def issue_tokens(user, session_id: str = None, device_uuid: str = None):
    """
    Mint an access/refresh pair.

    Role and KYC tier ride in the claims so the common authorization checks
    need no database round-trip. They are a snapshot: a role change takes
    effect for the user on their next refresh, at most 15 minutes later. Any
    action that must reflect an immediate change (an account freeze, a KYC
    approval) re-reads the user row instead of trusting the claim.
    """
    claims = {
        'role': user.role.role_name if user.role else None,
        'kyc_tier': user.kyc_tier,
        'phone': user.phone,
        'session_id': session_id,
        'device_uuid': device_uuid,
    }

    return (
        create_access_token(identity=str(user.user_id), additional_claims=claims),
        create_refresh_token(identity=str(user.user_id), additional_claims=claims),
    )


def current_user_id() -> str:
    return get_jwt_identity()


def current_claims() -> dict:
    return get_jwt()


def current_user():
    """
    Load the authenticated user row.

    Prefer this over the JWT claims wherever a stale value would be unsafe -
    a frozen account, a revoked session, a just-approved KYC tier.
    """
    from portal.models.users import Users
    return Users.query.filter_by(user_id=get_jwt_identity()).first()


# ── Guards ─────────────────────────────────────────────────────────────────

def roles_required(*allowed_roles):
    """Restrict a route to the given RBAC tiers (PRD section 15)."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            role = get_jwt().get('role')
            if role not in allowed_roles:
                current_app.logger.warning(
                    f'RBAC denial: user={get_jwt_identity()} role={role} '
                    f'attempted {fn.__qualname__}'
                )
                return failure(
                    ErrorCode.FORBIDDEN,
                    'You do not have permission to perform this action.',
                    403,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(fn):
    """Any administrative tier."""
    from portal.models.roles import RoleTypes

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        if get_jwt().get('role') not in RoleTypes.ADMIN_ROLES:
            return failure(
                ErrorCode.FORBIDDEN, 'Administrator access required.', 403
            )
        return fn(*args, **kwargs)

    return wrapper


def active_user_required(fn):
    """
    Reject suspended, banned or frozen accounts, and honour the session kill
    switch.

    This re-reads the user row rather than trusting the token, because an
    account frozen by a risk analyst must stop transacting immediately - not
    when their 15-minute access token happens to expire.
    """
    from portal.models.users import UserStatus

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        user = current_user()

        if not user:
            return failure(ErrorCode.UNAUTHORIZED, 'Account not found.', 401)

        if user.status in (UserStatus.SUSPENDED, UserStatus.BANNED):
            return failure(
                ErrorCode.FORBIDDEN,
                'Your account has been suspended. Please contact support.',
                403,
            )
        if user.status == UserStatus.FROZEN:
            return failure(
                ErrorCode.FORBIDDEN,
                'Your account is temporarily frozen pending a security review.',
                403,
            )
        if not user.is_active:
            return failure(ErrorCode.FORBIDDEN, 'This account is inactive.', 403)

        # Kill switch: a session issued before the invalidation point is dead.
        settings = user.security_settings
        if settings and settings.sessions_invalidated_at:
            issued_at = get_jwt().get('iat')
            if issued_at:
                issued_dt = datetime.fromtimestamp(issued_at, tz=timezone.utc).replace(
                    tzinfo=None
                )
                if issued_dt < settings.sessions_invalidated_at:
                    return failure(
                        ErrorCode.UNAUTHORIZED,
                        'This session has been signed out. Please sign in again.',
                        401,
                    )

        return fn(*args, **kwargs)

    return wrapper


def kyc_required(minimum_tier: str = 'MINIMUM'):
    """
    Gate a route behind a KYC tier (PRD section 18).

    FULL is required before a credit-to-bank transfer above 10,000 INR; the
    amount-sensitive part of that rule lives in transfer_engine, because it
    depends on the request body rather than the route.
    """
    from portal.models.users import KYCTier

    order = {KYCTier.NONE: 0, KYCTier.MINIMUM: 1, KYCTier.FULL: 2}

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            user = current_user()
            if not user:
                return failure(ErrorCode.UNAUTHORIZED, 'Account not found.', 401)

            if order.get(user.kyc_tier, 0) < order.get(minimum_tier, 1):
                return failure(
                    ErrorCode.KYC_REQUIRED,
                    'Complete your KYC verification to use this feature.',
                    403,
                    details={
                        'current_tier': user.kyc_tier,
                        'required_tier': minimum_tier,
                    },
                    recovery='Go to Profile and complete KYC verification.',
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
