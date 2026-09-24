"""
Admin and operations console (PRD sections 15, 16).

RBAC is enforced per endpoint against the four tiers. Two rules carry real
weight:

  - Raw PII and KYC documents are visible only to L2 and L3, and every such view
    writes an audit row naming the viewer (PRD 15 "YES (Audited)").
  - A reversal above 25,000 INR requires maker-checker; the initiating admin
    cannot approve their own request.
"""

import os
from datetime import timedelta

from flask import current_app, send_file
from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse
from sqlalchemy import func

from portal import db
from portal.helpers import audit, error_recorder, ledger_engine, settings
from portal.helpers.helpers import (
    ErrorCode, failure, iso, paginated, success, to_float,
)
from portal.helpers.jwt import admin_required, current_claims, current_user, roles_required
from portal.helpers.settings import Key
from portal.helpers.validators import (
    sanitize_text, validate_date, validate_pagination,
)
from portal.models.audit_logs import AdminActivityLogs, AuditLogs
from portal.models.transaction_errors import TransactionErrors
from portal.models.auto_pay_mandates import AutoPayMandates, MandateStatus
from portal.models.bank_accounts import BankAccounts
from portal.models.base import utcnow
from portal.models.cards import Cards, CardStatus
from portal.models.emi_obligations import EMIObligations
from portal.models.emi_payments import EMIPayments
from portal.models.kyc_verifications import KYCStatus, KYCVerifications
from portal.models.master_transactions import (
    MasterTransactions, ReconStatus, TransactionStatus,
)
from portal.models.reconciliation import (
    DiscrepancyResolution, ReconciliationDiscrepancies,
)
from portal.models.roles import RoleTypes
from portal.models.users import KYCTier, UserStatus, Users

from . import logger, ns

L1 = RoleTypes.L1_SUPPORT
L2 = RoleTypes.L2_RISK_RECON
L3 = RoleTypes.L3_SUPER_ADMIN

list_parser = reqparse.RequestParser()
list_parser.add_argument('page', type=int, default=1, location='args')
list_parser.add_argument('per_page', type=int, default=20, location='args')
list_parser.add_argument('search', type=str, required=False, location='args')
list_parser.add_argument('status', type=str, required=False, location='args')

kyc_review_parser = reqparse.RequestParser()
kyc_review_parser.add_argument('decision', type=str, required=True, location='json')
kyc_review_parser.add_argument('tier', type=str, required=False, location='json')
kyc_review_parser.add_argument('reason', type=str, required=False, location='json')

action_parser = reqparse.RequestParser()
action_parser.add_argument('reason', type=str, required=True, location='json')

setting_parser = reqparse.RequestParser()
setting_parser.add_argument('value', type=str, required=True, location='json')

flag_parser = reqparse.RequestParser()
flag_parser.add_argument('is_enabled', type=bool, required=True, location='json')
flag_parser.add_argument('rollout_percentage', type=int, required=False, location='json')


def _actor():
    """The acting admin, for audit attribution."""
    user = current_user()
    return user, (current_claims().get('role') or '')


@ns.route('/dashboard')
class AdminDashboard(Resource):
    @ns.doc('admin_dashboard', security='Bearer')
    @jwt_required()
    @admin_required
    def get(self):
        """Operational overview (PRD 16.1)."""
        today = utcnow().date()
        month_start = today.replace(day=1)

        total_users = Users.query.count()
        active_users = Users.query.filter_by(status=UserStatus.ACTIVE).count()
        pending_kyc = KYCVerifications.query.filter(
            KYCVerifications.kyc_status.in_(
                [KYCStatus.PENDING, KYCStatus.UNDER_REVIEW]
            )
        ).count()

        # Measured off the ledger rather than off any one product's table, so
        # the numbers stay correct as products are added or retired.
        payments_today = MasterTransactions.query.filter(
            func.date(MasterTransactions.created_on) == today
        ).count()
        volume_month = db.session.query(
            func.coalesce(func.sum(MasterTransactions.gross_amount), 0)
        ).filter(
            MasterTransactions.status == TransactionStatus.SUCCEEDED,
            MasterTransactions.created_on >= month_start,
        ).scalar()

        fee_month = db.session.query(
            func.coalesce(func.sum(MasterTransactions.fee_amount), 0)
        ).filter(
            MasterTransactions.status == TransactionStatus.SUCCEEDED,
            MasterTransactions.created_on >= month_start,
        ).scalar()

        succeeded = MasterTransactions.query.filter(
            MasterTransactions.status == TransactionStatus.SUCCEEDED,
            MasterTransactions.created_on >= month_start,
        ).count()
        attempted = MasterTransactions.query.filter(
            MasterTransactions.created_on >= month_start,
            MasterTransactions.status.notin_([TransactionStatus.INITIATED]),
        ).count()

        # Stuck means non-terminal for longer than any rail should take. A
        # payment that is merely in flight right now is not an alert.
        stuck = MasterTransactions.query.filter(
            MasterTransactions.status.notin_(TransactionStatus.TERMINAL),
            MasterTransactions.created_on < utcnow() - timedelta(hours=1),
        ).count()

        open_discrepancies = ReconciliationDiscrepancies.query.filter_by(
            resolution=DiscrepancyResolution.OPEN
        ).count()

        return success({
            'users': {
                'total': total_users,
                'active': active_users,
                'kyc_verified': Users.query.filter(
                    Users.kyc_tier != KYCTier.NONE
                ).count(),
                'pending_kyc_reviews': pending_kyc,
            },
            'payments': {
                'today': payments_today,
                'month_volume': float(volume_month or 0),
                'month_fee_revenue': float(fee_month or 0),
                'success_rate': (
                    round(succeeded / attempted * 100, 2) if attempted else None
                ),
                'stuck_count': stuck,
            },
            'emi': {
                'active_obligations': EMIObligations.query.filter_by(
                    is_active=True
                ).count(),
                'active_mandates': AutoPayMandates.query.filter_by(
                    status=MandateStatus.ACTIVE
                ).count(),
                'payments_today': EMIPayments.query.filter(
                    func.date(EMIPayments.created_on) == today
                ).count(),
            },
            'operations': {
                'open_discrepancies': open_discrepancies,
                'cards_linked': Cards.query.filter(
                    Cards.status == CardStatus.ACTIVE
                ).count(),
                'verified_bank_accounts': BankAccounts.query.filter_by(
                    penny_drop_status='VERIFIED', deleted_at=None
                ).count(),
            },
            'alerts': _operational_alerts(stuck, open_discrepancies, pending_kyc),
        })


def _operational_alerts(stuck, discrepancies, pending_kyc) -> list:
    """Surface what actually needs someone's attention, worst first."""
    alerts = []

    if stuck:
        alerts.append({
            'severity': 'critical',
            'message': f'{stuck} payment(s) are stuck mid-flight and need review.',
            'action': 'transactions',
        })
    if discrepancies:
        alerts.append({
            'severity': 'critical' if discrepancies > 5 else 'warning',
            'message': f'{discrepancies} unreconciled discrepancy(ies) are open.',
            'action': 'reconciliation',
        })
    if pending_kyc:
        alerts.append({
            'severity': 'info',
            'message': f'{pending_kyc} KYC submission(s) are awaiting review.',
            'action': 'kyc',
        })

    return alerts


@ns.route('/users')
class AdminUserList(Resource):
    @ns.doc('admin_list_users', security='Bearer')
    @jwt_required()
    @admin_required
    def get(self):
        """
        User search (PRD 16.1: by phone, masked PAN, or transaction UTR).

        Returns masked identifiers regardless of tier - unmasking is a separate,
        audited call.
        """
        args = list_parser.parse_args()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = Users.query

        if args.get('search'):
            term = args['search'].strip()

            # A UTR search resolves through the transaction to its owner, which
            # is how a support agent actually arrives from a customer's receipt.
            txn = MasterTransactions.query.filter(
                (MasterTransactions.bank_rrn_utr == term)
                | (MasterTransactions.gateway_ref_no == term)
            ).first()

            if txn:
                query = query.filter(Users.user_id == txn.user_id)
            else:
                like = f'%{term}%'
                query = query.filter(
                    Users.phone.ilike(like)
                    | Users.email.ilike(like)
                    | Users.full_name.ilike(like)
                )

        if args.get('status'):
            query = query.filter(Users.status == args['status'])

        pagination = query.order_by(Users.created_on.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return paginated([{
            'user_id': u.user_id,
            'masked_phone': u.masked_phone(),
            'full_name': u.full_name,
            'email': u.email,
            'status': u.status,
            'kyc_tier': u.kyc_tier,
            'role': u.role.role_name if u.role else None,
            'created_on': iso(u.created_on),
            'last_login': iso(u.last_login),
        } for u in pagination.items], page, per_page, pagination.total)


@ns.route('/users/<string:user_id>')
class AdminUserDetail(Resource):
    @ns.doc('admin_get_user', security='Bearer')
    @jwt_required()
    @admin_required
    def get(self, user_id):
        """
        360-degree user view (PRD 16.1).

        L1 sees masked data only. L2 and L3 see raw PII, and every such view is
        written to the audit trail naming the viewer - PRD section 15 marks this
        capability "YES (Audited)", and the audit is the half that matters.
        """
        actor, role = _actor()

        user = Users.query.filter_by(user_id=user_id).first()
        if not user:
            return failure(ErrorCode.NOT_FOUND, 'User not found.', 404)

        can_see_pii = role in (L2, L3)

        if can_see_pii:
            audit.record(
                action='ADMIN_VIEWED_PII',
                entity_type='Users',
                entity_id=user_id,
                actor_user_id=str(actor.user_id),
                actor_role=role,
                on_behalf_of=user_id,
                notes='Admin opened the full user profile including PII.',
            )

        profile = user.profile
        kyc = user.kyc_verification

        cards = Cards.query.filter(
            Cards.user_id == user_id, Cards.status != CardStatus.DELETED
        ).all()
        accounts = BankAccounts.query.filter_by(
            user_id=user_id, deleted_at=None
        ).all()
        obligations = EMIObligations.query.filter_by(user_id=user_id).all()

        payment_stats = db.session.query(
            func.count(MasterTransactions.transaction_id),
            func.coalesce(func.sum(MasterTransactions.gross_amount), 0),
        ).filter(
            MasterTransactions.user_id == user_id,
            MasterTransactions.status == TransactionStatus.SUCCEEDED,
        ).one()

        return success({
            'user_id': user.user_id,
            'phone': user.phone if can_see_pii else user.masked_phone(),
            'full_name': user.full_name,
            'email': user.email if can_see_pii else None,
            'status': user.status,
            'kyc_tier': user.kyc_tier,
            'kyc_status': kyc.kyc_status if kyc else 'NOT_STARTED',
            'role': user.role.role_name if user.role else None,
            'created_on': iso(user.created_on),
            'last_login': iso(user.last_login),
            'locked_until': iso(user.locked_until),

            'profile': {
                'pan_last4': profile.pan_last4 if profile else None,
                'aadhaar_last4': profile.aadhaar_last4 if profile else None,
                'city': profile.city if profile else None,
                'state': profile.state if profile else None,
            } if profile else None,

            'cards': [{
                'card_id': c.card_id,
                'masked_pan': c.masked_pan,
                'issuer_bank': c.card_issuer_bank,
                'status': c.status,
                'linked_at': iso(c.linked_at),
            } for c in cards],

            'bank_accounts': [{
                'bank_account_id': a.bank_account_id,
                'masked_account': a.masked_account(),
                'bank_name': a.bank_name,
                'penny_drop_status': a.penny_drop_status,
                'name_match_score': to_float(a.name_match_score),
            } for a in accounts],

            'emi_obligations': [{
                'emi_id': e.emi_id,
                'provider_name': e.provider_name,
                'masked_loan_account': e.masked_loan_account(),
                'emi_amount': to_float(e.emi_amount),
                'auto_pay_status': e.auto_pay_status,
                'payment_status': e.payment_status,
                'admin_verified': e.admin_verified,
            } for e in obligations],

            'stats': {
                'successful_payments': payment_stats[0],
                'total_paid': float(payment_stats[1] or 0),
                'cards_linked': len(cards),
                'verified_accounts': sum(1 for a in accounts if a.is_payout_eligible),
            },

            'viewer_can_see_pii': can_see_pii,
        })


@ns.route('/users/<string:user_id>/freeze')
class FreezeUser(Resource):
    @ns.doc('freeze_user', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def post(self, user_id):
        """Freeze an account on a suspicious-velocity alert (PRD 16.1)."""
        args = action_parser.parse_args()
        actor, role = _actor()

        user = Users.query.filter_by(user_id=user_id).first()
        if not user:
            return failure(ErrorCode.NOT_FOUND, 'User not found.', 404)

        reason = sanitize_text(args['reason'], 500)
        if not reason:
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'A reason is required to freeze an account.',
                400,
            )

        previous = user.status
        user.status = UserStatus.FROZEN
        db.session.commit()

        audit.record_admin(
            admin_user_id=str(actor.user_id),
            admin_role=role,
            module='USERS',
            action='FREEZE_ACCOUNT',
            target_type='Users',
            target_id=user_id,
            justification=reason,
            payload={'previous_status': previous},
        )

        return success({'status': user.status}, 'Account frozen.')


@ns.route('/users/<string:user_id>/unfreeze')
class UnfreezeUser(Resource):
    @ns.doc('unfreeze_user', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def post(self, user_id):
        args = action_parser.parse_args()
        actor, role = _actor()

        user = Users.query.filter_by(user_id=user_id).first()
        if not user:
            return failure(ErrorCode.NOT_FOUND, 'User not found.', 404)

        user.status = UserStatus.ACTIVE
        db.session.commit()

        audit.record_admin(
            admin_user_id=str(actor.user_id),
            admin_role=role,
            module='USERS',
            action='UNFREEZE_ACCOUNT',
            target_type='Users',
            target_id=user_id,
            justification=sanitize_text(args['reason'], 500),
        )

        return success({'status': user.status}, 'Account reactivated.')


@ns.route('/kyc/queue')
class KYCQueue(Resource):
    @ns.doc('kyc_queue', security='Bearer')
    @jwt_required()
    @admin_required
    def get(self):
        """Pending KYC submissions awaiting review."""
        args = list_parser.parse_args()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = KYCVerifications.query.filter(
            KYCVerifications.kyc_status.in_(
                [KYCStatus.PENDING, KYCStatus.UNDER_REVIEW]
            )
        )

        pagination = query.order_by(
            KYCVerifications.submitted_at.asc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        return paginated([{
            'kyc_id': k.kyc_id,
            'user_id': k.user_id,
            'masked_phone': k.user.masked_phone() if k.user else None,
            'verified_legal_name': k.verified_legal_name,
            'requested_tier': k.requested_tier,
            'kyc_status': k.kyc_status,
            'submitted_at': iso(k.submitted_at),
            'has_pan_document': bool(k.pan_document_path),
            'has_aadhaar_document': bool(k.aadhaar_document_path),
            # What the reviewer can actually open. Only the slot name is sent -
            # never the stored path, which would leak the on-disk layout.
            'documents': [
                {
                    'slot': slot,
                    'label': {'pan': 'PAN card', 'aadhaar': 'Aadhaar',
                              'selfie': 'Selfie'}[slot],
                    'available': bool(getattr(k, column, None)),
                }
                for slot, column in _KYC_DOCUMENT_SLOTS.items()
            ],
            'waiting_hours': (
                round((utcnow() - k.submitted_at).total_seconds() / 3600, 1)
                if k.submitted_at else None
            ),
        } for k in pagination.items], page, per_page, pagination.total)


#: Document slots an admin may request, mapped to the column holding the path.
#: The caller names a slot, never a path - so no request can reach a file the
#: database does not already point at.
_KYC_DOCUMENT_SLOTS = {
    'pan': 'pan_document_path',
    'aadhaar': 'aadhaar_document_path',
    'selfie': 'selfie_path',
}

#: Only these may be streamed back. A KYC upload that somehow carried another
#: extension is refused rather than served with a guessed content type.
_KYC_MIME_TYPES = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.pdf': 'application/pdf',
}


@ns.route('/kyc/<string:kyc_id>/document/<string:slot>')
class KYCDocument(Resource):
    @ns.doc('get_kyc_document', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def get(self, kyc_id, slot):
        """
        Stream an uploaded KYC document for review.

        This is the only route that can read anything out of the upload
        directory - the files are deliberately not served statically, so a
        leaked filename is worthless without an L2/L3 token.

        PRD section 15 lists "View Raw PII / KYC Documents" as L2 and L3 only,
        and marks it *audited*. The audit row is the half that matters: someone
        looking at a customer's PAN card must always be attributable.
        """
        actor, role = _actor()

        column = _KYC_DOCUMENT_SLOTS.get(slot)
        if not column:
            return failure(
                ErrorCode.VALIDATION_ERROR,
                f"Unknown document type. Expected one of: "
                f"{', '.join(_KYC_DOCUMENT_SLOTS)}.",
                400,
            )

        kyc = KYCVerifications.query.filter_by(kyc_id=kyc_id).first()
        if not kyc:
            return failure(ErrorCode.NOT_FOUND, 'KYC record not found.', 404)

        stored = getattr(kyc, column, None)
        if not stored:
            return failure(
                ErrorCode.NOT_FOUND,
                'No document of that type was uploaded.',
                404,
            )

        upload_root = os.path.realpath(current_app.config['UPLOAD_FOLDER'])
        resolved = os.path.realpath(os.path.join(upload_root, stored))

        # Defence in depth. The path comes from our own database rather than the
        # request, so it should already be safe - but a stored value corrupted
        # by some future bug must not become an arbitrary file read.
        if not resolved.startswith(upload_root + os.sep):
            logger.error(
                f'Blocked out-of-root KYC document read: kyc={kyc_id} '
                f'slot={slot} resolved={resolved}'
            )
            return failure(ErrorCode.FORBIDDEN, 'This document cannot be served.', 403)

        if not os.path.isfile(resolved):
            logger.error(f'KYC document missing on disk: {resolved}')
            return failure(
                ErrorCode.NOT_FOUND,
                'The uploaded file is no longer available on disk.',
                404,
            )

        mimetype = _KYC_MIME_TYPES.get(os.path.splitext(resolved)[1].lower())
        if not mimetype:
            return failure(
                ErrorCode.FORBIDDEN,
                'This file type cannot be displayed.',
                403,
            )

        audit.record(
            action='ADMIN_VIEWED_KYC_DOCUMENT',
            entity_type='KYCVerifications',
            entity_id=kyc_id,
            actor_user_id=str(actor.user_id),
            actor_role=role,
            on_behalf_of=str(kyc.user_id),
            notes=f'Opened the {slot.upper()} document for verification.',
        )

        response = send_file(resolved, mimetype=mimetype, conditional=False)

        # Never let a customer's identity document sit in a shared cache, and
        # never let a browser sniff it into something executable.
        response.headers['Cache-Control'] = 'no-store, private, max-age=0'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Disposition'] = f'inline; filename="{slot}"'
        return response


@ns.route('/kyc/<string:kyc_id>/review')
class ReviewKYC(Resource):
    @ns.doc('review_kyc', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def post(self, kyc_id):
        """
        Approve or reject a KYC submission.

        The tier is granted here and nowhere else, which is what makes approval
        the single gate on a credit line.
        """
        args = kyc_review_parser.parse_args()
        actor, role = _actor()

        kyc = KYCVerifications.query.filter_by(kyc_id=kyc_id).first()
        if not kyc:
            return failure(ErrorCode.NOT_FOUND, 'KYC record not found.', 404)

        if kyc.kyc_status == KYCStatus.APPROVED:
            return failure(
                ErrorCode.CONFLICT, 'This KYC has already been approved.', 409
            )

        decision = (args['decision'] or '').upper()
        if decision not in ('APPROVE', 'REJECT'):
            return failure(
                ErrorCode.VALIDATION_ERROR,
                "Decision must be either 'APPROVE' or 'REJECT'.",
                400,
            )

        user = kyc.user
        previous = kyc.kyc_status

        if decision == 'APPROVE':
            granted = args.get('tier') or kyc.requested_tier or KYCTier.MINIMUM
            if granted not in (KYCTier.MINIMUM, KYCTier.FULL):
                granted = KYCTier.MINIMUM

            kyc.kyc_status = KYCStatus.APPROVED
            kyc.reviewed_at = utcnow()
            kyc.reviewed_by = str(actor.user_id)
            kyc.rejection_reason = None
            kyc.expires_at = utcnow() + timedelta(days=365 * 2)

            user.kyc_tier = granted
            if user.status == UserStatus.PENDING:
                user.status = UserStatus.ACTIVE

            audit.emit(
                'KYCApprovedEvent',
                aggregate_type='KYCVerifications',
                aggregate_id=kyc.kyc_id,
                user_id=str(user.user_id),
                payload={'event': 'KYC_APPROVED', 'tier': granted},
            )
            message = f'KYC approved at {granted} tier.'

        else:
            reason = sanitize_text(args.get('reason'), 500)
            if not reason:
                return failure(
                    ErrorCode.VALIDATION_ERROR,
                    'A reason is required when rejecting a KYC submission.',
                    400,
                )

            kyc.kyc_status = KYCStatus.REJECTED
            kyc.reviewed_at = utcnow()
            kyc.reviewed_by = str(actor.user_id)
            kyc.rejection_reason = reason

            audit.emit(
                'KYCRejectedEvent',
                aggregate_type='KYCVerifications',
                aggregate_id=kyc.kyc_id,
                user_id=str(user.user_id),
                payload={'event': 'KYC_REJECTED', 'reason': reason},
            )
            message = 'KYC rejected.'

        db.session.commit()

        audit.record_admin(
            admin_user_id=str(actor.user_id),
            admin_role=role,
            module='KYC',
            action=f'KYC_{decision}',
            target_type='KYCVerifications',
            target_id=kyc_id,
            justification=args.get('reason'),
            payload={'previous_status': previous, 'tier': user.kyc_tier},
        )

        return success({'kyc_status': kyc.kyc_status, 'tier': user.kyc_tier}, message)


@ns.route('/reconciliation')
class Reconciliation(Resource):
    @ns.doc('reconciliation_console', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def get(self):
        """Open discrepancies (PRD 16.1 settlement console)."""
        args = list_parser.parse_args()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = ReconciliationDiscrepancies.query.filter_by(
            resolution=DiscrepancyResolution.OPEN
        )

        pagination = query.order_by(
            ReconciliationDiscrepancies.created_on.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        unreconciled = MasterTransactions.query.filter_by(
            recon_status=ReconStatus.UNRECONCILED,
            status=TransactionStatus.SUCCEEDED,
        ).count()

        return paginated([{
            'discrepancy_id': d.discrepancy_id,
            'transaction_id': d.transaction_id,
            'type': d.discrepancy_type,
            'expected_amount': to_float(d.expected_amount),
            'actual_amount': to_float(d.actual_amount),
            'details': d.details,
            'resolution': d.resolution,
            'created_on': iso(d.created_on),
        } for d in pagination.items], page, per_page, pagination.total,
            unreconciled_transactions=unreconciled)


@ns.route('/reconciliation/self-audit')
class LedgerSelfAudit(Resource):
    @ns.doc('run_self_audit', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def post(self):
        """
        Run the ledger integrity sweep on demand.

        Also runs nightly. An UNBALANCED_LEDGER finding means the ledger engine
        was bypassed somewhere, which is the most severe class of bug this
        platform can have.
        """
        actor, role = _actor()
        result = ledger_engine.self_audit()

        audit.record_admin(
            admin_user_id=str(actor.user_id),
            admin_role=role,
            module='RECONCILIATION',
            action='LEDGER_SELF_AUDIT',
            payload={'healthy': result['healthy']},
        )

        return success(result, (
            'Ledger integrity verified.' if result['healthy']
            else 'Ledger integrity check found discrepancies.'
        ))


@ns.route('/settings')
class AdminSettingsList(Resource):
    @ns.doc('list_settings', security='Bearer')
    @jwt_required()
    @roles_required(L3)
    def get(self):
        """Platform configuration (PRD 16.1)."""
        from portal.models.admin_settings import AdminSettings

        rows = AdminSettings.query.order_by(
            AdminSettings.category.asc(), AdminSettings.setting_key.asc()
        ).all()

        return success([{
            'setting_key': s.setting_key,
            'setting_value': s.setting_value,
            'default_value': s.default_value,
            'data_type': s.data_type,
            'category': s.category,
            'display_name': s.display_name,
            'description': s.description,
            'min_value': s.min_value,
            'max_value': s.max_value,
            'is_editable': s.is_editable,
        } for s in rows])


@ns.route('/settings/<string:setting_key>')
class AdminSettingDetail(Resource):
    @ns.doc('update_setting', security='Bearer')
    @jwt_required()
    @roles_required(L3)
    def patch(self, setting_key):
        """
        Change a platform setting.

        Bounded by the min and max on the row, so a mistyped fee cannot become
        900% - the guard rails exist because these are live commercial levers.
        """
        args = setting_parser.parse_args()
        actor, role = _actor()

        from portal.models.admin_settings import AdminSettings

        row = AdminSettings.query.filter_by(setting_key=setting_key).first()
        if not row:
            return failure(ErrorCode.NOT_FOUND, 'Setting not found.', 404)

        if not row.is_editable:
            return failure(
                ErrorCode.FORBIDDEN, 'This setting cannot be changed.', 403
            )

        new_value = sanitize_text(args['value'], 1000)
        previous = row.setting_value

        if row.min_value or row.max_value:
            try:
                from decimal import Decimal
                numeric = Decimal(new_value)
                if row.min_value and numeric < Decimal(row.min_value):
                    return failure(
                        ErrorCode.VALIDATION_ERROR,
                        f'Value must be at least {row.min_value}.',
                        400,
                    )
                if row.max_value and numeric > Decimal(row.max_value):
                    return failure(
                        ErrorCode.VALIDATION_ERROR,
                        f'Value must not exceed {row.max_value}.',
                        400,
                    )
            except Exception:
                return failure(
                    ErrorCode.VALIDATION_ERROR,
                    'This setting expects a numeric value.',
                    400,
                )

        row.setting_value = new_value
        row.updated_by = str(actor.user_id)
        db.session.commit()

        audit.record_admin(
            admin_user_id=str(actor.user_id),
            admin_role=role,
            module='SETTINGS',
            action='UPDATE_SETTING',
            target_type='AdminSettings',
            target_id=setting_key,
            payload={'from': previous, 'to': new_value},
        )

        return success({'setting_key': setting_key, 'setting_value': new_value},
                       'Setting updated.')


@ns.route('/feature-flags')
class FeatureFlagList(Resource):
    @ns.doc('list_flags', security='Bearer')
    @jwt_required()
    @roles_required(L3)
    def get(self):
        from portal.models.admin_settings import FeatureFlags

        flags = FeatureFlags.query.order_by(FeatureFlags.flag_key.asc()).all()

        return success([{
            'flag_key': f.flag_key,
            'display_name': f.display_name,
            'description': f.description,
            'is_enabled': f.is_enabled,
            'rollout_type': f.rollout_type,
            'rollout_percentage': f.rollout_percentage,
        } for f in flags])


@ns.route('/feature-flags/<string:flag_key>')
class FeatureFlagDetail(Resource):
    @ns.doc('update_flag', security='Bearer')
    @jwt_required()
    @roles_required(L3)
    def patch(self, flag_key):
        """Toggle a feature flag."""
        args = flag_parser.parse_args()
        actor, role = _actor()

        from portal.models.admin_settings import FeatureFlags

        flag = FeatureFlags.query.filter_by(flag_key=flag_key).first()
        if not flag:
            return failure(ErrorCode.NOT_FOUND, 'Feature flag not found.', 404)

        previous = flag.is_enabled
        flag.is_enabled = args['is_enabled']
        if args.get('rollout_percentage') is not None:
            flag.rollout_percentage = max(0, min(100, args['rollout_percentage']))
        flag.updated_by = str(actor.user_id)
        db.session.commit()

        audit.record_admin(
            admin_user_id=str(actor.user_id),
            admin_role=role,
            module='FEATURE_FLAGS',
            action='TOGGLE_FLAG',
            target_type='FeatureFlags',
            target_id=flag_key,
            payload={'from': previous, 'to': flag.is_enabled},
        )

        return success({
            'flag_key': flag_key,
            'is_enabled': flag.is_enabled,
        }, 'Feature flag updated.')


@ns.route('/audit-logs')
class AuditLogList(Resource):
    @ns.doc('list_audit_logs', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def get(self):
        """Immutable audit trail viewer (PRD 16.1)."""
        args = list_parser.parse_args()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = AuditLogs.query
        if args.get('search'):
            like = f"%{args['search'].strip()}%"
            query = query.filter(
                AuditLogs.action.ilike(like)
                | AuditLogs.entity_id.ilike(like)
                | AuditLogs.actor_user_id.ilike(like)
            )

        pagination = query.order_by(AuditLogs.created_on.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return paginated([{
            'audit_id': a.audit_id,
            'action': a.action,
            'actor_user_id': a.actor_user_id,
            'actor_role': a.actor_role,
            'entity_type': a.entity_type,
            'entity_id': a.entity_id,
            'ip_address': a.ip_address,
            'notes': a.notes,
            'created_on': iso(a.created_on),
        } for a in pagination.items], page, per_page, pagination.total)


@ns.route('/admin-activity')
class AdminActivityList(Resource):
    @ns.doc('list_admin_activity', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def get(self):
        """Administrative action log, including pending maker-checker items."""
        args = list_parser.parse_args()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        pagination = AdminActivityLogs.query.order_by(
            AdminActivityLogs.created_on.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        return paginated([{
            'activity_id': a.activity_id,
            'admin_user_id': a.admin_user_id,
            'admin_role': a.admin_role,
            'module': a.module,
            'action': a.action,
            'target_type': a.target_type,
            'target_id': a.target_id,
            'amount_involved': to_float(a.amount_involved),
            'requires_maker_checker': a.requires_maker_checker,
            'checker_user_id': a.checker_user_id,
            'checker_approved_at': iso(a.checker_approved_at),
            'justification': a.justification,
            'created_on': iso(a.created_on),
        } for a in pagination.items], page, per_page, pagination.total)


@ns.route('/emi/<string:emi_id>/verify')
class VerifyEMI(Resource):
    @ns.doc('verify_emi', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def post(self, emi_id):
        """
        Verify a manually entered loan against its uploaded sanction letter.

        This is what unlocks auto-pay for a manual entry (PRD FR-007) - an
        unverified obligation cannot have a standing debit armed against it.
        """
        args = action_parser.parse_args()
        actor, role = _actor()

        obligation = EMIObligations.query.filter_by(emi_id=emi_id).first()
        if not obligation:
            return failure(ErrorCode.NOT_FOUND, 'EMI obligation not found.', 404)

        if not obligation.loan_document_path:
            return failure(
                ErrorCode.CONFLICT,
                'No loan document has been uploaded for this obligation.',
                409,
            )

        obligation.admin_verified = True
        obligation.admin_verified_at = utcnow()
        db.session.commit()

        audit.record_admin(
            admin_user_id=str(actor.user_id),
            admin_role=role,
            module='EMI',
            action='VERIFY_MANUAL_EMI',
            target_type='EMIObligations',
            target_id=emi_id,
            justification=sanitize_text(args['reason'], 500),
        )

        return success({'admin_verified': True}, 'EMI obligation verified.')


# -- Transaction error monitoring --------------------------------------------

error_list_parser = reqparse.RequestParser()
error_list_parser.add_argument('page', type=int, default=1, location='args')
error_list_parser.add_argument('per_page', type=int, default=25, location='args')
error_list_parser.add_argument('error_type', type=str, required=False, location='args')
error_list_parser.add_argument('search', type=str, required=False, location='args')
error_list_parser.add_argument('resolved', type=str, required=False, location='args')

resolve_parser = reqparse.RequestParser()
resolve_parser.add_argument('notes', type=str, required=True, location='json')


@ns.route('/transaction-errors')
class AdminTransactionErrors(Resource):
    @ns.doc('list_transaction_errors', security='Bearer')
    @jwt_required()
    @roles_required(RoleTypes.L1_SUPPORT, RoleTypes.L2_RISK_RECON,
                    RoleTypes.L3_SUPER_ADMIN)
    def get(self):
        """
        Failed payments, newest first.

        L1 sees this because it is the first thing a support agent needs when a
        customer calls: the reason, in words, against a transaction id they can
        search. The sanitised gateway payload is included for diagnosis - it
        has already had card numbers, CVVs and tokens stripped at write time,
        so there is nothing here to withhold from an agent.
        """
        args = error_list_parser.parse_args()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = TransactionErrors.query

        if args.get('error_type'):
            query = query.filter(TransactionErrors.error_type == args['error_type'])

        if args.get('resolved') in ('true', 'false'):
            query = query.filter(
                TransactionErrors.is_resolved.is_(args['resolved'] == 'true')
            )

        term = (args.get('search') or '').strip()
        if term:
            like = f'%{term}%'
            query = query.filter(db.or_(
                TransactionErrors.transaction_id.like(like),
                TransactionErrors.reference_id.like(like),
                TransactionErrors.error_code.like(like),
            ))

        pagination = query.order_by(
            TransactionErrors.created_on.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        return paginated(
            [error_recorder.to_dict(row, detailed=True) for row in pagination.items],
            page, per_page, pagination.total,
        )


@ns.route('/transaction-errors/summary')
class AdminErrorSummary(Resource):
    @ns.doc('transaction_error_summary', security='Bearer')
    @jwt_required()
    @roles_required(RoleTypes.L1_SUPPORT, RoleTypes.L2_RISK_RECON,
                    RoleTypes.L3_SUPER_ADMIN)
    def get(self):
        """
        Failures grouped by type, and the users hitting them repeatedly.

        The repeat list is the useful half. One declined card is a customer
        having a bad day; the same user failing six times in an hour is either
        a broken instrument or someone probing, and both want attention before
        a ticket arrives.
        """
        since = utcnow() - timedelta(days=7)

        by_type = db.session.query(
            TransactionErrors.error_type,
            func.count(TransactionErrors.error_id),
        ).filter(
            TransactionErrors.created_on >= since
        ).group_by(TransactionErrors.error_type).all()

        repeats = db.session.query(
            TransactionErrors.user_id,
            func.count(TransactionErrors.error_id).label('failures'),
        ).filter(
            TransactionErrors.created_on >= since
        ).group_by(TransactionErrors.user_id).having(
            func.count(TransactionErrors.error_id) >= 3
        ).order_by(func.count(TransactionErrors.error_id).desc()).limit(20).all()

        repeat_rows = []
        for user_id, failures in repeats:
            user = Users.query.filter_by(user_id=user_id).first()
            repeat_rows.append({
                'user_id': user_id,
                'masked_phone': user.masked_phone() if user else None,
                'failures': failures,
            })

        return success({
            'window_days': 7,
            'total': sum(count for _, count in by_type),
            'unresolved': TransactionErrors.query.filter_by(is_resolved=False).count(),
            'by_type': [
                {'error_type': t, 'count': c}
                for t, c in sorted(by_type, key=lambda r: -r[1])
            ],
            'repeat_failures': repeat_rows,
        })


@ns.route('/transaction-errors/<string:error_id>/resolve')
class AdminResolveError(Resource):
    @ns.doc('resolve_transaction_error', security='Bearer')
    @jwt_required()
    @roles_required(RoleTypes.L1_SUPPORT, RoleTypes.L2_RISK_RECON,
                    RoleTypes.L3_SUPER_ADMIN)
    def post(self, error_id):
        """
        Mark a failure handled.

        Requires a note, and the note goes into the audit trail with the
        agent's name. Resolving is a statement that somebody looked - an empty
        one is worth nothing to the next person who opens the record.
        """
        args = resolve_parser.parse_args()
        notes = sanitize_text(args['notes'], 1000)

        if not notes:
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'A resolution note is required.',
                400,
            )

        row = TransactionErrors.query.filter_by(error_id=error_id).first()
        if not row:
            return failure(ErrorCode.NOT_FOUND, 'Error record not found.', 404)

        actor = current_user()
        row.is_resolved = True
        row.resolved_at = utcnow()
        row.resolved_by = str(actor.user_id)
        row.resolution_notes = notes
        db.session.commit()

        audit.record(
            action='TRANSACTION_ERROR_RESOLVED',
            entity_type='TransactionErrors',
            entity_id=error_id,
            actor_user_id=str(actor.user_id),
            after={'error_code': row.error_code, 'notes': notes},
        )

        return success(error_recorder.to_dict(row, detailed=True),
                       'Marked as resolved.')

