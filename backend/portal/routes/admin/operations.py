"""
Admin console: support staff, payment records and card records.

Staff management is L3 only. A staff account is an existing, registered
CashU account (mobile OTP + MPIN, the one sign-in system) given a staff role;
there is no separate staff password to issue or leak. Changing a role signs
the account out everywhere, because the role travels in its tokens.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse
from sqlalchemy import func

from portal import db
from portal.helpers import audit
from portal.helpers.helpers import ErrorCode, failure, iso, paginated, success, to_float
from portal.helpers.jwt import current_user, roles_required
from portal.helpers.validators import ValidationError, validate_mobile, validate_pagination
from portal.models.base import utcnow
from portal.models.roles import RoleTypes, Roles
from portal.models.user_sessions import SessionStatus, UserSessions
from portal.models.users import UserStatus, Users

from . import ns

L2, L3 = RoleTypes.L2_RISK_RECON, RoleTypes.L3_SUPER_ADMIN

#: Roles an L3 may grant here. A new L3 is made by changing the seed config,
#: not from a screen.
GRANTABLE = [RoleTypes.L1_SUPPORT, RoleTypes.L2_RISK_RECON]

ROLE_LABELS = {
    RoleTypes.L1_SUPPORT: 'Customer support (L1)',
    RoleTypes.L2_RISK_RECON: 'Risk & reconciliation admin (L2)',
    RoleTypes.L3_SUPER_ADMIN: 'Super admin (L3)',
}

staff_add_parser = reqparse.RequestParser()
staff_add_parser.add_argument('phone', type=str, required=True, location='json')
staff_add_parser.add_argument('role', type=str, required=True, location='json')

staff_update_parser = reqparse.RequestParser()
# A grantable role, or NORMAL_USER to take staff access away.
staff_update_parser.add_argument('role', type=str, required=True, location='json')

records_parser = reqparse.RequestParser()
records_parser.add_argument('page', type=int, default=1, location='args')
records_parser.add_argument('per_page', type=int, default=25, location='args')
# FAILED | PENDING | SUCCESS
records_parser.add_argument('status', type=str, required=False, location='args')
# CREDIT | EMI | BILL   (payments)  /  TOKENISED | MANUAL  (cards)
records_parser.add_argument('kind', type=str, required=False, location='args')


def _staff_dict(user) -> dict:
    role = user.role.role_name if user.role else None
    return {
        'user_id': user.user_id,
        'full_name': user.full_name,
        'phone_masked': user.masked_phone(),
        'role': role,
        'role_label': ROLE_LABELS.get(role, role),
        'status': user.status,
        'mpin_set': bool(user.mpin_hash),
        'last_login': iso(user.last_login),
    }


def _sign_out_everywhere(user, reason):
    UserSessions.query.filter_by(user_id=user.user_id, status=SessionStatus.ACTIVE).update(
        {'status': SessionStatus.REVOKED, 'revoked_at': utcnow(), 'revoked_reason': reason})
    if user.security_settings:
        user.security_settings.sessions_invalidated_at = utcnow()


@ns.route('/staff')
class StaffList(Resource):
    @ns.doc('list_staff', security='Bearer')
    @jwt_required()
    @roles_required(L3)
    def get(self):
        """Every account with a staff role."""
        staff = Users.query.join(Roles, Roles.role_id == Users.role_id).filter(
            Roles.role_name.in_(RoleTypes.STAFF_ROLES)).order_by(Users.full_name).all()
        return success({
            'staff': [_staff_dict(u) for u in staff],
            'grantable_roles': [{'role': r, 'label': ROLE_LABELS[r]} for r in GRANTABLE],
        })

    @ns.doc('add_staff', security='Bearer')
    @jwt_required()
    @roles_required(L3)
    def post(self):
        """Give an existing, registered customer account a staff role."""
        args = staff_add_parser.parse_args()
        admin = current_user()
        try:
            phone = validate_mobile(args['phone'])
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': 'phone'})
        role_name = (args['role'] or '').upper()
        if role_name not in GRANTABLE:
            return failure(ErrorCode.VALIDATION_ERROR,
                           'Choose customer support or risk & reconciliation.', 400,
                           details={'field': 'role'})

        user = Users.query.filter_by(phone=phone).first()
        if not user or user.status != UserStatus.ACTIVE or not user.mpin_hash:
            return failure(
                ErrorCode.NOT_FOUND,
                'No active, registered account has this number. Ask the person to '
                'sign up in the CashU app and set an MPIN first, then add them here.',
                404, details={'field': 'phone'})
        if user.role and user.role.role_name in RoleTypes.STAFF_ROLES:
            return failure(ErrorCode.CONFLICT,
                           'This account is already staff. Change its role instead.', 409)

        return _set_role(user, role_name, admin, 'STAFF_ADDED')


@ns.route('/staff/<string:user_id>')
class StaffMember(Resource):
    @ns.doc('update_staff', security='Bearer')
    @jwt_required()
    @roles_required(L3)
    def patch(self, user_id):
        """Change a staff role, or set NORMAL_USER to remove staff access."""
        args = staff_update_parser.parse_args()
        admin = current_user()
        user = Users.query.filter_by(user_id=user_id).first()
        if not user or not user.role or user.role.role_name not in RoleTypes.STAFF_ROLES:
            return failure(ErrorCode.NOT_FOUND, 'Staff member not found.', 404)
        if user.user_id == admin.user_id:
            return failure(ErrorCode.FORBIDDEN, 'You cannot change your own role.', 403)
        if user.role.role_name == RoleTypes.L3_SUPER_ADMIN:
            return failure(ErrorCode.FORBIDDEN,
                           'Super admin accounts are managed through the server '
                           'configuration, not from this screen.', 403)
        role_name = (args['role'] or '').upper()
        if role_name not in GRANTABLE + [RoleTypes.NORMAL_USER]:
            return failure(ErrorCode.VALIDATION_ERROR, 'Unknown role.', 400,
                           details={'field': 'role'})
        return _set_role(user, role_name, admin,
                         'STAFF_REMOVED' if role_name == RoleTypes.NORMAL_USER
                         else 'STAFF_ROLE_CHANGED')


def _set_role(user, role_name, admin, action):
    role = Roles.query.filter_by(role_name=role_name).first()
    if not role:
        return failure(ErrorCode.INTERNAL_ERROR, 'That role is not set up.', 500)
    before = user.role.role_name if user.role else None
    user.role_id = role.role_id
    _sign_out_everywhere(user, f'Role changed to {role_name}')
    db.session.commit()
    audit.record(action=action, entity_type='Users', entity_id=user.user_id,
                 actor_user_id=str(admin.user_id), actor_role=RoleTypes.L3_SUPER_ADMIN,
                 before={'role': before}, after={'role': role_name})
    db.session.refresh(user)
    message = {
        'STAFF_ADDED': 'Staff access granted. They sign in through their portal.',
        'STAFF_REMOVED': 'Staff access removed and the account signed out.',
    }.get(action, 'Role updated and the account signed out.')
    return success(_staff_dict(user), message)


# -- Payment records -----------------------------------------------------

#: Every payment table's status words, sorted into the three buckets the
#: console filters on.
_BUCKETS = {
    'SUCCESS': {'SUCCEEDED', 'SUCCESSFUL', 'SETTLED'},
    'FAILED': {'FAILED', 'REVERSED', 'CANCELLED', 'EXPIRED', 'REFUNDED'},
    'PENDING': {'PENDING', 'PROCESSING', 'INITIATED', 'AWAITING_OTP'},
}


def _bucket(status):
    for name, members in _BUCKETS.items():
        if status in members:
            return name
    return 'OTHER'


@ns.route('/payments')
class PaymentRecords(Resource):
    @ns.doc('payment_records', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def get(self):
        """
        Payments across the credit line, EMIs and Pay Bills, newest first,
        filterable by outcome. Status is the server's record - set by gateway
        verification and webhooks - never what a client reported.
        """
        from portal.models.bill_payments import BillPayments
        from portal.models.credit_transactions import CreditTransactions
        from portal.models.emi_payments import EMIPayments

        args = records_parser.parse_args()
        page, per_page = validate_pagination(args['page'], args['per_page'])
        bucket = (args.get('status') or '').upper()
        kind = (args.get('kind') or '').upper()
        statuses = _BUCKETS.get(bucket)
        window = page * per_page

        rows = []
        sources = [
            ('CREDIT', CreditTransactions, lambda t: {
                'type': t.transaction_type, 'amount': to_float(t.amount),
                'reference': t.gateway_reference or t.gateway_payment_id or t.credit_transaction_id,
                'method': t.payment_method, 'failure_reason': t.failure_reason,
                'id': t.credit_transaction_id}),
            ('EMI', EMIPayments, lambda p: {
                'type': p.payment_mode, 'amount': to_float(p.amount),
                'reference': p.bbps_rrn or p.gateway_payment_id or p.payment_id,
                'method': p.payment_mode, 'failure_reason': None, 'id': p.payment_id}),
            ('BILL', BillPayments, lambda b: {
                'type': b.category, 'amount': to_float(b.total_amount),
                'reference': b.reference, 'method': 'PAYOUT', 'failure_reason': None,
                'id': b.bill_payment_id}),
        ]
        total = 0
        for name, model, shape in sources:
            if kind and kind != name:
                continue
            query = model.query
            if statuses:
                query = query.filter(model.status.in_(statuses))
            total += query.count()
            for row in query.order_by(model.created_on.desc()).limit(window).all():
                owner = Users.query.filter_by(user_id=row.user_id).first()
                rows.append({
                    'kind': name, 'status': row.status, 'outcome': _bucket(row.status),
                    'at': iso(row.created_on),
                    'customer': owner.full_name if owner else None,
                    'customer_phone': owner.masked_phone() if owner else None,
                    **shape(row),
                })
        rows.sort(key=lambda r: r['at'] or '', reverse=True)
        start = (page - 1) * per_page
        return paginated(rows[start:start + per_page], page, per_page, total)


# -- Card records ----------------------------------------------------------

@ns.route('/cards')
class CardRecords(Resource):
    @ns.doc('card_records', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def get(self):
        """
        Every card on file and where its figures came from.

        A manually entered card is reported as user-entered and unverified,
        always: nothing on this screen can mark it bank-verified, because no
        bank has confirmed it.
        """
        from portal.models.cards import Cards, CardStatus
        from portal.models.manual_cards import ManualCards

        args = records_parser.parse_args()
        page, per_page = validate_pagination(args['page'], args['per_page'])
        kind = (args.get('kind') or '').upper()

        def owner(user_id):
            user = Users.query.filter_by(user_id=user_id).first()
            return (user.full_name, user.masked_phone()) if user else (None, None)

        rows = []
        if kind in ('', 'TOKENISED'):
            for card in Cards.query.filter(Cards.status != CardStatus.DELETED).all():
                name, phone = owner(card.user_id)
                rows.append({
                    'source': 'TOKENISED',
                    'source_label': 'Tokenised - limit set by CashU',
                    'verification': 'Sandbox token' if card.token_provider == 'SANDBOX'
                    else f'Token via {card.token_provider}',
                    'issuer_bank': card.card_issuer_bank, 'last4': card.last4,
                    'network': card.card_network, 'status': card.status,
                    'credit_limit': to_float(card.card_limit),
                    'outstanding': to_float(card.outstanding_amount),
                    'is_test_card': bool(card.test_scenario),
                    'customer': name, 'customer_phone': phone,
                    'added_at': iso(card.linked_at or card.created_on),
                })
        if kind in ('', 'MANUAL'):
            for card in ManualCards.query.all():
                name, phone = owner(card.user_id)
                rows.append({
                    'source': 'MANUAL',
                    'source_label': 'User-entered - Not Bank Verified',
                    'verification': 'Not verified by any bank',
                    'issuer_bank': card.issuer_bank, 'last4': card.last4,
                    'network': card.network, 'status': card.status,
                    'credit_limit': to_float(card.credit_limit),
                    'outstanding': to_float(card.outstanding_balance),
                    'is_test_card': False,
                    'customer': name, 'customer_phone': phone,
                    'added_at': iso(card.created_on),
                })
        rows.sort(key=lambda r: r['added_at'] or '', reverse=True)
        start = (page - 1) * per_page
        counts = {
            'tokenised': Cards.query.filter(Cards.status != CardStatus.DELETED).count(),
            'manual': ManualCards.query.count(),
        }
        return paginated(rows[start:start + per_page], page, per_page, len(rows),
                         counts=counts)


@ns.route('/support/escalations')
class Escalations(Resource):
    @ns.doc('escalations', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def get(self):
        """Tickets support has escalated, unresolved first."""
        from portal.models.support_messages import SupportTickets, TicketStatus
        from portal.routes.support_desk.routes import desk_ticket_dict

        tickets = SupportTickets.query.filter(SupportTickets.escalated.is_(True)).order_by(
            SupportTickets.status.in_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
            SupportTickets.escalated_at.desc()).limit(100).all()
        return success([desk_ticket_dict(t) for t in tickets])


@ns.route('/support/escalations/count')
class EscalationCount(Resource):
    @ns.doc('escalation_count', security='Bearer')
    @jwt_required()
    @roles_required(L2, L3)
    def get(self):
        from portal.models.support_messages import SupportTickets, TicketStatus
        count = db.session.query(func.count(SupportTickets.ticket_id)).filter(
            SupportTickets.escalated.is_(True),
            SupportTickets.status.notin_([TicketStatus.RESOLVED, TicketStatus.CLOSED]),
        ).scalar()
        return success({'open_escalations': count})
