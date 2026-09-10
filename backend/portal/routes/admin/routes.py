"""
Admin and operations console (PRD sections 15, 16).

RBAC is enforced per endpoint against the four tiers. Two rules carry real
weight:

  - Raw PII and KYC documents are visible only to L2 and L3, and every such view
    writes an audit row naming the viewer (PRD 15 "YES (Audited)").
  - A reversal above 25,000 INR requires maker-checker; the initiating admin
    cannot approve their own request.
"""

from datetime import timedelta

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse
from sqlalchemy import func

from portal import db
from portal.helpers import audit, ledger_engine, settings, transfer_engine
from portal.helpers.helpers import (
    ErrorCode, failure, iso, paginated, success, to_float,
)
from portal.helpers.jwt import admin_required, current_claims, current_user, roles_required
from portal.helpers.settings import Key
from portal.helpers.validators import (
    sanitize_text, validate_date, validate_pagination,
)
from portal.models.audit_logs import AdminActivityLogs, AuditLogs
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
from portal.models.transfers import TransferStatus, Transfers
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

        transfers_today = Transfers.query.filter(
            func.date(Transfers.created_on) == today
        ).count()
        volume_month = db.session.query(
            func.coalesce(func.sum(Transfers.principal_amount), 0)
        ).filter(
            Transfers.status == TransferStatus.SUCCEEDED,
            Transfers.created_on >= month_start,
        ).scalar()

        fee_month = db.session.query(
            func.coalesce(func.sum(Transfers.convenience_fee), 0)
        ).filter(
            Transfers.status == TransferStatus.SUCCEEDED,
            Transfers.created_on >= month_start,
        ).scalar()

        succeeded = Transfers.query.filter(
            Transfers.status == TransferStatus.SUCCEEDED,
            Transfers.created_on >= month_start,
        ).count()
        attempted = Transfers.query.filter(
            Transfers.created_on >= month_start,
            Transfers.status.notin_([TransferStatus.INITIATED]),
        ).count()

        stuck = Transfers.query.filter(
            Transfers.status.in_([
                TransferStatus.PAYOUT_PROCESSING,
                TransferStatus.PENDING_RECONCILIATION,
                TransferStatus.REVERSAL_INIT,
            ])
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
            'transfers': {
                'today': transfers_today,
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
            'message': f'{stuck} transfer(s) are stuck mid-flight and need review.',
            'action': 'transfers',
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

        transfer_stats = db.session.query(
            func.count(Transfers.transfer_id),
            func.coalesce(func.sum(Transfers.principal_amount), 0),
        ).filter(
            Transfers.user_id == user_id,
            Transfers.status == TransferStatus.SUCCEEDED,
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
                'successful_transfers': transfer_stats[0],
                'total_transferred': float(transfer_stats[1] or 0),
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
            'waiting_hours': (
                round((utcnow() - k.submitted_at).total_seconds() / 3600, 1)
                if k.submitted_at else None
            ),
        } for k in pagination.items], page, per_page, pagination.total)


@ns.route('/kyc/<string:kyc_id>/review')
class ReviewKYC(Resource):
    @ns.doc('review_kyc', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def post(self, kyc_id):
        """
        Approve or reject a KYC submission.

        The tier is granted here and nowhere else, which is what makes approval
        the single gate on higher transfer limits.
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


@ns.route('/transfers')
class AdminTransferList(Resource):
    @ns.doc('admin_list_transfers', security='Bearer')
    @jwt_required()
    @admin_required
    def get(self):
        """Transaction monitoring telemetry (PRD 16.1)."""
        args = list_parser.parse_args()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = Transfers.query
        if args.get('status'):
            query = query.filter(Transfers.status == args['status'])
        if args.get('search'):
            like = f"%{args['search'].strip()}%"
            query = query.filter(
                Transfers.bank_rrn_utr.ilike(like)
                | Transfers.gateway_order_id.ilike(like)
                | Transfers.transfer_id.ilike(like)
            )

        pagination = query.order_by(Transfers.created_on.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return paginated([{
            'transfer_id': t.transfer_id,
            'user_id': t.user_id,
            'principal_amount': to_float(t.principal_amount),
            'total_charged': to_float(t.total_charged_to_card),
            'fee': to_float(t.convenience_fee),
            'status': t.status,
            'utr': t.bank_rrn_utr,
            'risk_score': to_float(t.risk_score),
            'payout_retry_count': t.payout_retry_count,
            'failure_reason': t.failure_reason,
            'created_on': iso(t.created_on),
        } for t in pagination.items], page, per_page, pagination.total)


@ns.route('/transfers/stuck')
class StuckTransfers(Resource):
    @ns.doc('stuck_transfers', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def get(self):
        """
        The failed-transaction and reversal operations queue (PRD 16.1).

        These are transfers where the card is charged but the money has not
        reached the user - the highest-priority queue on the platform.
        """
        stuck = Transfers.query.filter(
            Transfers.status.in_([
                TransferStatus.PAYOUT_PROCESSING,
                TransferStatus.PENDING_RECONCILIATION,
                TransferStatus.REVERSAL_INIT,
            ])
        ).order_by(Transfers.created_on.asc()).limit(100).all()

        threshold = settings.get_decimal(Key.MAKER_CHECKER_THRESHOLD)

        return success([{
            'transfer_id': t.transfer_id,
            'user_id': t.user_id,
            'principal_amount': to_float(t.principal_amount),
            'total_charged': to_float(t.total_charged_to_card),
            'status': t.status,
            'payout_retry_count': t.payout_retry_count,
            'next_retry_at': iso(t.next_retry_at),
            'charged_at': iso(t.charged_at),
            'stuck_for_hours': (
                round((utcnow() - t.charged_at).total_seconds() / 3600, 1)
                if t.charged_at else None
            ),
            'failure_reason': t.failure_reason,
            'requires_maker_checker': (
                float(t.total_charged_to_card or 0) > float(threshold)
            ),
        } for t in stuck])


@ns.route('/transfers/<string:transfer_id>/retry-payout')
class RetryPayout(Resource):
    @ns.doc('retry_payout', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def post(self, transfer_id):
        """Re-queue a failed payout."""
        args = action_parser.parse_args()
        actor, role = _actor()

        transfer = Transfers.query.filter_by(transfer_id=transfer_id).first()
        if not transfer:
            return failure(ErrorCode.NOT_FOUND, 'Transfer not found.', 404)

        if transfer.status not in (
            TransferStatus.PAYOUT_PROCESSING,
            TransferStatus.PENDING_RECONCILIATION,
        ):
            return failure(
                ErrorCode.CONFLICT,
                f'A transfer in {transfer.status} cannot be re-queued.',
                409,
            )

        try:
            transfer.next_retry_at = None
            transfer = transfer_engine.dispatch_payout(transfer)
        except Exception as exc:
            logger.exception(f'Manual payout retry failed for {transfer_id}: {exc}')
            return failure(
                ErrorCode.PROVIDER_ERROR, 'The payout retry could not be sent.', 502
            )

        audit.record_admin(
            admin_user_id=str(actor.user_id),
            admin_role=role,
            module='TRANSFERS',
            action='MANUAL_PAYOUT_RETRY',
            target_type='Transfers',
            target_id=transfer_id,
            amount=float(transfer.principal_amount or 0),
            justification=sanitize_text(args['reason'], 500),
        )

        return success({'status': transfer.status}, 'Payout re-queued.')


@ns.route('/transfers/<string:transfer_id>/reverse')
class ManualReversal(Resource):
    @ns.doc('manual_reversal', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def post(self, transfer_id):
        """
        Refund a charged transfer to the source card.

        PRD 16.1 requires maker-checker above 25,000 INR. L2 initiates and the
        request waits for a second approver; L3 may act alone, because the tier
        that can approve is also the tier that can act.
        """
        args = action_parser.parse_args()
        actor, role = _actor()

        transfer = Transfers.query.filter_by(transfer_id=transfer_id).first()
        if not transfer:
            return failure(ErrorCode.NOT_FOUND, 'Transfer not found.', 404)

        reason = sanitize_text(args['reason'], 500)
        if not reason:
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'A reason is required to reverse a transfer.',
                400,
            )

        threshold = float(settings.get_decimal(Key.MAKER_CHECKER_THRESHOLD))
        amount = float(transfer.total_charged_to_card or 0)

        if amount > threshold and role != L3:
            pending = audit.record_admin(
                admin_user_id=str(actor.user_id),
                admin_role=role,
                module='TRANSFERS',
                action='REVERSAL_REQUESTED',
                target_type='Transfers',
                target_id=transfer_id,
                amount=amount,
                justification=reason,
            )
            return success({
                'requires_approval': True,
                'approval_request_id': pending.activity_id if pending else None,
                'threshold': threshold,
            }, f'This reversal exceeds Rs. {threshold:,.2f} and needs approval '
               'from a senior administrator.', 202)

        try:
            transfer = transfer_engine.reverse_to_card(transfer, reason=reason)
        except transfer_engine.TransferError as exc:
            return failure(exc.code, exc.message, 409)
        except Exception as exc:
            logger.exception(f'Manual reversal failed for {transfer_id}: {exc}')
            return failure(
                ErrorCode.PROVIDER_ERROR, 'The reversal could not be completed.', 502
            )

        audit.record_admin(
            admin_user_id=str(actor.user_id),
            admin_role=role,
            module='TRANSFERS',
            action='MANUAL_REVERSAL',
            target_type='Transfers',
            target_id=transfer_id,
            amount=amount,
            justification=reason,
        )

        return success({'status': transfer.status}, 'Transfer reversed to card.')


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
