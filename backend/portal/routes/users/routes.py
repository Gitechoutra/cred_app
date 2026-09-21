"""
User profile and security settings (PRD FR-012).

DPDPA 2023 obligations live here: granular consent, data export, and the right
to erasure - bounded by the PMLA requirement to retain financial records for ten
years, which is why erasure anonymises the identity rather than deleting the
transaction history.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal import db
from portal.helpers import audit
from portal.helpers.helpers import ErrorCode, failure, iso, success, to_float
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.validators import (
    validate_name,
    ValidationError, sanitize_text, validate_date, validate_email,
)
from portal.models.base import utcnow
from portal.models.login_history import LoginHistory

from . import logger, ns

profile_parser = reqparse.RequestParser()
profile_parser.add_argument('full_name', type=str, required=False, location='json')
profile_parser.add_argument('email', type=str, required=False, location='json')
profile_parser.add_argument('date_of_birth', type=str, required=False, location='json')
profile_parser.add_argument('address_line1', type=str, required=False, location='json')
profile_parser.add_argument('address_line2', type=str, required=False, location='json')
profile_parser.add_argument('city', type=str, required=False, location='json')
profile_parser.add_argument('state', type=str, required=False, location='json')
profile_parser.add_argument('pincode', type=str, required=False, location='json')
profile_parser.add_argument('occupation', type=str, required=False, location='json')

security_parser = reqparse.RequestParser()
security_parser.add_argument('biometric_enabled', type=bool, required=False, location='json')
security_parser.add_argument('login_alerts_enabled', type=bool, required=False, location='json')
security_parser.add_argument('two_factor_enabled', type=bool, required=False, location='json')


@ns.route('/me')
class Me(Resource):
    @ns.doc('get_me', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Full profile for the signed-in user."""
        user = current_user()
        profile = user.profile
        kyc = user.kyc_verification
        security = user.security_settings

        return success({
            'user_id': user.user_id,
            'phone': user.phone,
            'masked_phone': user.masked_phone(),
            'email': user.email,
            'full_name': user.full_name,
            'date_of_birth': iso(user.date_of_birth),
            'status': user.status,
            'kyc_tier': user.kyc_tier,
            'kyc_status': kyc.kyc_status if kyc else 'NOT_STARTED',
            'role': user.role.role_name if user.role else None,
            'is_phone_verified': user.is_phone_verified,
            'is_email_verified': user.is_email_verified,
            'terms_accepted': user.terms_accepted,
            'mpin_set': bool(user.mpin_hash),
            'member_since': iso(user.created_on),
            'last_login': iso(user.last_login),

            'profile': {
                'pan_last4': profile.pan_last4 if profile else None,
                'aadhaar_last4': profile.aadhaar_last4 if profile else None,
                'address_line1': profile.address_line1 if profile else None,
                'address_line2': profile.address_line2 if profile else None,
                'city': profile.city if profile else None,
                'state': profile.state if profile else None,
                'pincode': profile.pincode if profile else None,
                'occupation': profile.occupation if profile else None,
            } if profile else None,

            'security': {
                'biometric_enabled': security.biometric_enabled if security else False,
                'two_factor_enabled': security.two_factor_enabled if security else True,
                'login_alerts_enabled': (
                    security.login_alerts_enabled if security else True
                ),
                'mpin_last_changed': iso(security.mpin_last_changed) if security else None,
            } if security else None,
        })

    @ns.doc('update_me', security='Bearer')
    @jwt_required()
    @active_user_required
    def patch(self):
        """
        Update profile details.

        The registered phone number is deliberately not editable here - PRD
        FR-012 requires a change to trigger re-KYC and a 24-hour transaction
        freeze, so it goes through its own flow.
        """
        args = profile_parser.parse_args()
        user = current_user()

        before = {'full_name': user.full_name, 'email': user.email}

        try:
            if args.get('full_name') is not None:
                user.full_name = validate_name(args['full_name'])
            if args.get('email'):
                email = validate_email(args['email'])
                from portal.models.users import Users
                taken = Users.query.filter(
                    Users.email == email, Users.user_id != user.user_id
                ).first()
                if taken:
                    return failure(
                        ErrorCode.CONFLICT,
                        'This email is already linked to another account.',
                        409,
                    )
                if email != user.email:
                    user.email = email
                    user.is_email_verified = False
            if args.get('date_of_birth'):
                user.date_of_birth = validate_date(
                    args['date_of_birth'], 'date_of_birth'
                )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        profile = user.profile
        if not profile:
            from portal.models.user_profiles import UserProfiles
            profile = UserProfiles(user_id=user.user_id)
            db.session.add(profile)

        for field in (
            'address_line1', 'address_line2', 'city', 'state',
            'pincode', 'occupation',
        ):
            if args.get(field) is not None:
                setattr(profile, field, sanitize_text(args[field], 255))

        db.session.commit()

        audit.record(
            action='PROFILE_UPDATED',
            entity_type='Users',
            entity_id=user.user_id,
            actor_user_id=str(user.user_id),
            before=before,
            after={'full_name': user.full_name, 'email': user.email},
        )

        return success(None, 'Profile updated.')


@ns.route('/me/security')
class SecuritySettings(Resource):
    @ns.doc('update_security', security='Bearer')
    @jwt_required()
    @active_user_required
    def patch(self):
        """Toggle biometric unlock, login alerts and 2FA."""
        args = security_parser.parse_args()
        user = current_user()
        settings_row = user.security_settings

        if not settings_row:
            from portal.models.user_security_settings import UserSecuritySettings
            settings_row = UserSecuritySettings(user_id=user.user_id)
            db.session.add(settings_row)

        if args.get('biometric_enabled') is not None:
            settings_row.biometric_enabled = args['biometric_enabled']
            user.biometric_enabled = args['biometric_enabled']
        if args.get('login_alerts_enabled') is not None:
            settings_row.login_alerts_enabled = args['login_alerts_enabled']
        if args.get('two_factor_enabled') is not None:
            settings_row.two_factor_enabled = args['two_factor_enabled']

        db.session.commit()

        audit.record(
            action='SECURITY_SETTINGS_UPDATED',
            entity_type='Users',
            entity_id=user.user_id,
            actor_user_id=str(user.user_id),
        )

        return success({
            'biometric_enabled': settings_row.biometric_enabled,
            'two_factor_enabled': settings_row.two_factor_enabled,
            'login_alerts_enabled': settings_row.login_alerts_enabled,
        }, 'Security settings updated.')


@ns.route('/me/login-history')
class LoginHistoryList(Resource):
    @ns.doc('get_login_history', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Recent sign-in attempts, so a user can spot an intrusion."""
        user = current_user()

        history = LoginHistory.query.filter_by(
            user_id=user.user_id
        ).order_by(LoginHistory.created_on.desc()).limit(25).all()

        return success([{
            'login_id': h.login_id,
            'status': h.status,
            'ip_address': h.ip_address,
            'device_uuid': h.device_uuid,
            'location': h.location,
            'created_on': iso(h.created_on),
            'failure_reason': h.failure_reason,
        } for h in history])


@ns.route('/me/export')
class DataExport(Resource):
    @ns.doc('export_data', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Export personal data (DPDPA 2023).

        Assembled from what the user themselves provided plus their transaction
        history. Encrypted identifiers are returned masked - the export is a
        transparency right, not a way to extract another copy of raw PII.
        """
        user = current_user()
        profile = user.profile

        from portal.models.bank_accounts import BankAccounts
        from portal.models.cards import Cards, CardStatus
        from portal.models.emi_obligations import EMIObligations
        from portal.models.master_transactions import MasterTransactions

        cards = Cards.query.filter(
            Cards.user_id == user.user_id, Cards.status != CardStatus.DELETED
        ).all()
        accounts = BankAccounts.query.filter_by(
            user_id=user.user_id, deleted_at=None
        ).all()
        obligations = EMIObligations.query.filter_by(user_id=user.user_id).all()
        transactions = MasterTransactions.query.filter_by(
            user_id=user.user_id
        ).order_by(MasterTransactions.created_on.desc()).limit(1000).all()

        if user.security_settings:
            user.security_settings.data_export_requested_at = utcnow()
            db.session.commit()

        audit.record(
            action='DATA_EXPORT_REQUESTED',
            entity_type='Users',
            entity_id=user.user_id,
            actor_user_id=str(user.user_id),
        )

        return success({
            'generated_at': utcnow().isoformat(),
            'account': {
                'user_id': user.user_id,
                'phone': user.phone,
                'email': user.email,
                'full_name': user.full_name,
                'date_of_birth': iso(user.date_of_birth),
                'member_since': iso(user.created_on),
                'kyc_tier': user.kyc_tier,
            },
            'profile': {
                'pan_last4': profile.pan_last4 if profile else None,
                'address': {
                    'line1': profile.address_line1,
                    'line2': profile.address_line2,
                    'city': profile.city,
                    'state': profile.state,
                    'pincode': profile.pincode,
                } if profile else None,
            } if profile else None,
            'cards': [{
                'masked_pan': c.masked_pan,
                'issuer': c.card_issuer_bank,
                'network': c.card_network,
                'linked_at': iso(c.linked_at),
            } for c in cards],
            'bank_accounts': [{
                'masked_account': a.masked_account(),
                'bank_name': a.bank_name,
                'ifsc_code': a.ifsc_code,
                'verified': a.is_payout_eligible,
            } for a in accounts],
            'emi_obligations': [{
                'provider': e.provider_name,
                'masked_loan_account': e.masked_loan_account(),
                'emi_amount': to_float(e.emi_amount),
                'is_active': e.is_active,
            } for e in obligations],
            'transactions': [{
                'transaction_id': t.transaction_id,
                'type': t.transaction_type,
                'amount': to_float(t.gross_amount),
                'status': t.status,
                'date': iso(t.created_on),
            } for t in transactions],
        }, 'Your data export is ready.')


@ns.route('/me/erasure')
class DataErasure(Resource):
    @ns.doc('request_erasure', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Request account erasure (DPDPA 2023).

        Recorded rather than executed. PMLA requires financial transaction
        records to be retained for ten years, so erasure anonymises identity
        fields and leaves the ledger intact - a decision that needs an operator,
        not a button.
        """
        user = current_user()

        from portal.models.transfers import TransferStatus, Transfers

        in_flight = Transfers.query.filter(
            Transfers.user_id == user.user_id,
            Transfers.status.notin_(TransferStatus.TERMINAL),
        ).count()
        if in_flight:
            return failure(
                ErrorCode.CONFLICT,
                'You have a transfer in progress. Please wait for it to complete '
                'before requesting erasure.',
                409,
            )

        if user.security_settings:
            user.security_settings.erasure_requested_at = utcnow()
            db.session.commit()

        audit.record(
            action='ERASURE_REQUESTED',
            entity_type='Users',
            entity_id=user.user_id,
            actor_user_id=str(user.user_id),
            notes='DPDPA erasure request logged for compliance review.',
        )

        return success({
            'requested_at': utcnow().isoformat(),
            'retention_notice': (
                'Financial transaction records are retained for 10 years as '
                'required by the Prevention of Money Laundering Act. Your '
                'identity details will be anonymised once your request is '
                'processed.'
            ),
        }, 'Erasure request received. Our compliance team will process it within '
           '30 days.')
