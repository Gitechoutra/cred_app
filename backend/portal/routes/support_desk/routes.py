"""
The customer support desk.

For L1 support agents, and for administrators handling escalations. What an
agent can do is deliberately narrow:

    may     search customers, read a masked profile and the status of their
            cards and payments, reply on tickets, add internal notes, set a
            ticket's status, take or hand over a ticket, escalate to an admin
    may not change a credit limit, approve or refund anything, unblock an
            account, see an MPIN, a full phone number, PAN, Aadhaar or any
            card credential

Nothing here writes to a money or limit table - the restrictions are the
absence of such endpoints, not a flag that could be flipped. Every action is
written to the audit log against the ticket, and the ticket page shows that
trail.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse
from sqlalchemy import func, or_

from portal import db
from portal.helpers import audit
from portal.helpers.helpers import ErrorCode, failure, iso, paginated, success, to_float
from portal.helpers.jwt import current_user, roles_required
from portal.helpers.validators import sanitize_text, validate_pagination
from portal.models.audit_logs import AuditLogs
from portal.models.base import utcnow
from portal.models.roles import RoleTypes, Roles
from portal.models.support_messages import (
    SupportMessages, SupportSenderRole, SupportTickets, TicketStatus,
)
from portal.models.users import Users

from . import ns

DESK = RoleTypes.SUPPORT_DESK_ROLES

ticket_list_parser = reqparse.RequestParser()
ticket_list_parser.add_argument('page', type=int, default=1, location='args')
ticket_list_parser.add_argument('per_page', type=int, default=20, location='args')
# OPEN | IN_PROGRESS | RESOLVED | CLOSED (IN_PROGRESS covers the AWAITING_*).
ticket_list_parser.add_argument('status', type=str, required=False, location='args')
# me | unassigned
ticket_list_parser.add_argument('assigned', type=str, required=False, location='args')
ticket_list_parser.add_argument('escalated', type=str, required=False, location='args')
ticket_list_parser.add_argument('q', type=str, required=False, location='args')

message_parser = reqparse.RequestParser()
message_parser.add_argument('message', type=str, required=True, location='json')

status_parser = reqparse.RequestParser()
status_parser.add_argument('status', type=str, required=True, location='json')
status_parser.add_argument('resolution_notes', type=str, required=False, location='json')

assign_parser = reqparse.RequestParser()
# 'me', or empty to unassign.
assign_parser.add_argument('agent', type=str, required=False, location='json')

escalate_parser = reqparse.RequestParser()
escalate_parser.add_argument('reason', type=str, required=True, location='json')

search_parser = reqparse.RequestParser()
search_parser.add_argument('q', type=str, required=True, location='args')


# -- Masking -------------------------------------------------------------

def _mask_email(email):
    if not email or '@' not in email:
        return None
    name, domain = email.split('@', 1)
    return f'{name[:1]}{"*" * max(1, len(name) - 1)}@{domain}'


def _agent_name(user_id):
    if not user_id:
        return None
    agent = Users.query.filter_by(user_id=user_id).first()
    return agent.full_name if agent else None


def _customer_summary(user) -> dict:
    """Who the customer is, masked. Never the PAN, Aadhaar, MPIN or full phone."""
    return {
        'user_id': user.user_id,
        'full_name': user.full_name,
        'phone_masked': user.masked_phone(),
        'email_masked': _mask_email(user.email),
        'email_verified': bool(user.is_email_verified),
        'kyc_tier': user.kyc_tier,
        'status': user.status,
        'member_since': iso(user.created_on),
        'last_login': iso(user.last_login),
    }


# -- Tickets -------------------------------------------------------------

def _status_filter(query, status):
    status = (status or '').upper()
    if status == TicketStatus.IN_PROGRESS:
        return query.filter(SupportTickets.status.in_([
            TicketStatus.IN_PROGRESS, TicketStatus.AWAITING_USER,
            TicketStatus.AWAITING_AGENT]))
    if status in TicketStatus.CHOICES:
        return query.filter(SupportTickets.status == status)
    return query


def desk_ticket_dict(ticket, with_thread=False) -> dict:
    customer = Users.query.filter_by(user_id=ticket.user_id).first()
    data = {
        'ticket_id': ticket.ticket_id,
        'ticket_number': ticket.ticket_number,
        'subject': ticket.subject,
        'category': ticket.category,
        'status': ticket.status,
        'status_label': TicketStatus.DISPLAY.get(ticket.status, ticket.status),
        'waiting_on': {TicketStatus.AWAITING_USER: 'customer',
                       TicketStatus.AWAITING_AGENT: 'agent'}.get(ticket.status),
        'priority': ticket.priority,
        'related_entity_type': ticket.related_entity_type,
        'related_entity_id': ticket.related_entity_id,
        'assigned_agent_id': ticket.assigned_agent_id,
        'assigned_agent_name': _agent_name(ticket.assigned_agent_id),
        'escalated': bool(ticket.escalated),
        'escalated_at': iso(ticket.escalated_at),
        'escalation_reason': ticket.escalation_reason,
        'resolution_notes': ticket.resolution_notes,
        'resolved_at': iso(ticket.resolved_at),
        'created_on': iso(ticket.created_on),
        'updated_on': iso(ticket.updated_on),
        'customer': {
            'user_id': customer.user_id if customer else None,
            'full_name': customer.full_name if customer else None,
            'phone_masked': customer.masked_phone() if customer else None,
        },
    }
    if with_thread:
        data['messages'] = [{
            'message_id': m.message_id,
            'sender_role': m.sender_role,
            'sender_name': m.sender_name,
            'body': m.body,
            'is_internal': bool(m.is_internal),
            'created_on': iso(m.created_on),
        } for m in ticket.messages.order_by(SupportMessages.created_on.asc()).all()]
        data['audit_trail'] = [{
            'action': row.action,
            'actor_user_id': row.actor_user_id,
            'actor_name': _agent_name(row.actor_user_id),
            'actor_role': row.actor_role,
            'notes': row.notes,
            'at': iso(row.created_on),
        } for row in AuditLogs.query.filter_by(
            entity_type='SupportTickets', entity_id=ticket.ticket_id,
        ).order_by(AuditLogs.created_on.asc()).all()]
    return data


def _ticket_or_404(ticket_id):
    return SupportTickets.query.filter_by(ticket_id=ticket_id).first()


def _audit(ticket, action, agent, notes=None, before=None, after=None):
    audit.record(
        action=action, entity_type='SupportTickets', entity_id=ticket.ticket_id,
        actor_user_id=str(agent.user_id),
        actor_role=agent.role.role_name if agent.role else None,
        on_behalf_of=str(ticket.user_id), notes=notes, before=before, after=after,
    )


@ns.route('/overview')
class DeskOverview(Resource):
    @ns.doc('desk_overview', security='Bearer')
    @jwt_required()
    @roles_required(*DESK)
    def get(self):
        """Queue counts for the desk's home screen."""
        agent = current_user()
        counts = dict(db.session.query(SupportTickets.status, func.count())
                      .group_by(SupportTickets.status).all())
        in_progress = sum(counts.get(s, 0) for s in (
            TicketStatus.IN_PROGRESS, TicketStatus.AWAITING_USER,
            TicketStatus.AWAITING_AGENT))
        open_states = [TicketStatus.OPEN, TicketStatus.IN_PROGRESS,
                       TicketStatus.AWAITING_USER, TicketStatus.AWAITING_AGENT]
        return success({
            'open': counts.get(TicketStatus.OPEN, 0),
            'in_progress': in_progress,
            'awaiting_agent': counts.get(TicketStatus.AWAITING_AGENT, 0),
            'resolved': counts.get(TicketStatus.RESOLVED, 0),
            'closed': counts.get(TicketStatus.CLOSED, 0),
            'mine': SupportTickets.query.filter(
                SupportTickets.assigned_agent_id == agent.user_id,
                SupportTickets.status.in_(open_states)).count(),
            'unassigned': SupportTickets.query.filter(
                SupportTickets.assigned_agent_id.is_(None),
                SupportTickets.status.in_(open_states)).count(),
            'escalated': SupportTickets.query.filter(
                SupportTickets.escalated.is_(True),
                SupportTickets.status.in_(open_states)).count(),
            'agent': {'user_id': agent.user_id, 'full_name': agent.full_name,
                      'role': agent.role.role_name if agent.role else None},
        })


@ns.route('/tickets')
class DeskTicketList(Resource):
    @ns.doc('desk_tickets', security='Bearer')
    @jwt_required()
    @roles_required(*DESK)
    def get(self):
        """The ticket queue, newest activity first, with filters."""
        args = ticket_list_parser.parse_args()
        agent = current_user()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = _status_filter(SupportTickets.query, args.get('status'))
        if args.get('assigned') == 'me':
            query = query.filter(SupportTickets.assigned_agent_id == agent.user_id)
        elif args.get('assigned') == 'unassigned':
            query = query.filter(SupportTickets.assigned_agent_id.is_(None))
        if (args.get('escalated') or '').lower() == 'true':
            query = query.filter(SupportTickets.escalated.is_(True))
        term = sanitize_text(args.get('q') or '', 100)
        if term:
            like = f'%{term}%'
            query = query.join(Users, Users.user_id == SupportTickets.user_id).filter(or_(
                SupportTickets.ticket_number.ilike(like),
                SupportTickets.subject.ilike(like),
                Users.full_name.ilike(like),
                Users.phone.like(f'%{term[-10:]}') if term.isdigit() else False,
            ))

        pagination = query.order_by(SupportTickets.updated_on.desc()).paginate(
            page=page, per_page=per_page, error_out=False)
        return paginated([desk_ticket_dict(t) for t in pagination.items],
                         page, per_page, pagination.total)


@ns.route('/tickets/<string:ticket_id>')
class DeskTicketDetail(Resource):
    @ns.doc('desk_ticket', security='Bearer')
    @jwt_required()
    @roles_required(*DESK)
    def get(self, ticket_id):
        """A ticket with its full thread, internal notes and audit trail."""
        ticket = _ticket_or_404(ticket_id)
        if not ticket:
            return failure(ErrorCode.NOT_FOUND, 'Ticket not found.', 404)
        return success(desk_ticket_dict(ticket, with_thread=True))


@ns.route('/tickets/<string:ticket_id>/reply')
class DeskTicketReply(Resource):
    @ns.doc('desk_reply', security='Bearer')
    @jwt_required()
    @roles_required(*DESK)
    def post(self, ticket_id):
        """Reply to the customer. The ticket then waits on them."""
        args = message_parser.parse_args()
        agent = current_user()
        ticket = _ticket_or_404(ticket_id)
        if not ticket:
            return failure(ErrorCode.NOT_FOUND, 'Ticket not found.', 404)
        if ticket.status == TicketStatus.CLOSED:
            return failure(ErrorCode.CONFLICT, 'This ticket is closed. Reopen it first.', 409)
        body = sanitize_text(args['message'], 4000)
        if not body:
            return failure(ErrorCode.VALIDATION_ERROR, 'Enter a reply.', 400)

        db.session.add(SupportMessages(
            ticket_id=ticket.ticket_id, sender_role=SupportSenderRole.AGENT,
            sender_id=str(agent.user_id), sender_name=agent.full_name or 'CashU Support',
            body=body, is_internal=False,
        ))
        before = ticket.status
        ticket.status = TicketStatus.AWAITING_USER
        if not ticket.assigned_agent_id:
            ticket.assigned_agent_id = agent.user_id
        db.session.commit()
        _audit(ticket, 'SUPPORT_REPLY_SENT', agent,
               before={'status': before}, after={'status': ticket.status})

        from portal.helpers import notify
        from portal.models.notifications import NotificationEvent
        customer = Users.query.filter_by(user_id=ticket.user_id).first()
        event = getattr(NotificationEvent, 'SUPPORT_REPLY', None)
        if customer and event:
            notify.dispatch(customer, event, {'ticket_number': ticket.ticket_number})

        return success(desk_ticket_dict(ticket, with_thread=True), 'Reply sent.')


@ns.route('/tickets/<string:ticket_id>/notes')
class DeskTicketNote(Resource):
    @ns.doc('desk_note', security='Bearer')
    @jwt_required()
    @roles_required(*DESK)
    def post(self, ticket_id):
        """Add an internal note. Staff see it; the customer never does."""
        args = message_parser.parse_args()
        agent = current_user()
        ticket = _ticket_or_404(ticket_id)
        if not ticket:
            return failure(ErrorCode.NOT_FOUND, 'Ticket not found.', 404)
        body = sanitize_text(args['message'], 4000)
        if not body:
            return failure(ErrorCode.VALIDATION_ERROR, 'Enter a note.', 400)

        db.session.add(SupportMessages(
            ticket_id=ticket.ticket_id, sender_role=SupportSenderRole.AGENT,
            sender_id=str(agent.user_id), sender_name=agent.full_name or 'Support',
            body=body, is_internal=True,
        ))
        db.session.commit()
        _audit(ticket, 'SUPPORT_NOTE_ADDED', agent)
        return success(desk_ticket_dict(ticket, with_thread=True), 'Note added.')


@ns.route('/tickets/<string:ticket_id>/status')
class DeskTicketStatus(Resource):
    @ns.doc('desk_status', security='Bearer')
    @jwt_required()
    @roles_required(*DESK)
    def post(self, ticket_id):
        """Set Open, In progress, Resolved or Closed."""
        args = status_parser.parse_args()
        agent = current_user()
        ticket = _ticket_or_404(ticket_id)
        if not ticket:
            return failure(ErrorCode.NOT_FOUND, 'Ticket not found.', 404)

        status = (args['status'] or '').upper()
        if status not in TicketStatus.AGENT_SETTABLE:
            return failure(ErrorCode.VALIDATION_ERROR,
                           'Status must be OPEN, IN_PROGRESS, RESOLVED or CLOSED.', 400,
                           details={'field': 'status'})
        notes = sanitize_text(args.get('resolution_notes') or '', 1000) or None
        if status == TicketStatus.RESOLVED and not (notes or ticket.resolution_notes):
            return failure(ErrorCode.VALIDATION_ERROR,
                           'Say how it was resolved - the customer sees this.', 400,
                           details={'field': 'resolution_notes'})

        before = ticket.status
        ticket.status = status
        if status == TicketStatus.RESOLVED:
            ticket.resolved_at = utcnow()
            ticket.resolution_notes = notes or ticket.resolution_notes
        elif status in (TicketStatus.OPEN, TicketStatus.IN_PROGRESS):
            ticket.resolved_at = None
        if status == TicketStatus.IN_PROGRESS and not ticket.assigned_agent_id:
            ticket.assigned_agent_id = agent.user_id
        db.session.commit()
        _audit(ticket, 'SUPPORT_STATUS_CHANGED', agent, notes=notes,
               before={'status': before}, after={'status': status})
        return success(desk_ticket_dict(ticket, with_thread=True),
                       f'Ticket marked {TicketStatus.DISPLAY[status].lower()}.')


@ns.route('/tickets/<string:ticket_id>/assign')
class DeskTicketAssign(Resource):
    @ns.doc('desk_assign', security='Bearer')
    @jwt_required()
    @roles_required(*DESK)
    def post(self, ticket_id):
        """Take the ticket ('me'), or release it (empty)."""
        args = assign_parser.parse_args()
        agent = current_user()
        ticket = _ticket_or_404(ticket_id)
        if not ticket:
            return failure(ErrorCode.NOT_FOUND, 'Ticket not found.', 404)

        before = ticket.assigned_agent_id
        ticket.assigned_agent_id = agent.user_id if args.get('agent') == 'me' else None
        db.session.commit()
        _audit(ticket, 'SUPPORT_ASSIGNED' if ticket.assigned_agent_id else 'SUPPORT_UNASSIGNED',
               agent, before={'agent': before}, after={'agent': ticket.assigned_agent_id})
        return success(desk_ticket_dict(ticket, with_thread=True),
                       'Ticket assigned to you.' if ticket.assigned_agent_id
                       else 'Ticket released.')


@ns.route('/tickets/<string:ticket_id>/escalate')
class DeskTicketEscalate(Resource):
    @ns.doc('desk_escalate', security='Bearer')
    @jwt_required()
    @roles_required(*DESK)
    def post(self, ticket_id):
        """
        Hand the ticket to an administrator: anything about money, limits, KYC
        or an account's status is decided there, not on the desk.
        """
        args = escalate_parser.parse_args()
        agent = current_user()
        ticket = _ticket_or_404(ticket_id)
        if not ticket:
            return failure(ErrorCode.NOT_FOUND, 'Ticket not found.', 404)
        if ticket.escalated:
            return failure(ErrorCode.CONFLICT, 'This ticket is already escalated.', 409)
        reason = sanitize_text(args['reason'] or '', 500)
        if len(reason) < 10:
            return failure(ErrorCode.VALIDATION_ERROR,
                           'Explain what the administrator needs to decide.', 400,
                           details={'field': 'reason'})

        ticket.escalated = True
        ticket.escalated_at = utcnow()
        ticket.escalated_by = agent.user_id
        ticket.escalation_reason = reason
        ticket.priority = 'HIGH'
        if ticket.status in (TicketStatus.OPEN, TicketStatus.RESOLVED):
            ticket.status = TicketStatus.IN_PROGRESS
        db.session.add(SupportMessages(
            ticket_id=ticket.ticket_id, sender_role=SupportSenderRole.SYSTEM,
            sender_name='CashU', is_internal=True,
            body=f'Escalated to administrators by {agent.full_name or "support"}: {reason}',
        ))
        db.session.commit()
        _audit(ticket, 'SUPPORT_ESCALATED', agent, notes=reason)
        return success(desk_ticket_dict(ticket, with_thread=True),
                       'Escalated to the admin team.')


# -- Customers -----------------------------------------------------------

@ns.route('/customers/search')
class DeskCustomerSearch(Resource):
    @ns.doc('desk_customer_search', security='Bearer')
    @jwt_required()
    @roles_required(*DESK)
    def get(self):
        """
        Find a customer by mobile number, email, customer id or ticket number.

        Exact identifiers only (a full number, a full email): the desk looks
        up the person in front of it, it does not browse the customer base.
        """
        args = search_parser.parse_args()
        term = (args.get('q') or '').strip()
        if len(term) < 4:
            return failure(ErrorCode.VALIDATION_ERROR,
                           'Enter a full mobile number, email, customer id or '
                           'ticket number.', 400)

        digits = ''.join(ch for ch in term if ch.isdigit())
        query = Users.query.join(Roles, Roles.role_id == Users.role_id).filter(
            Roles.role_name == RoleTypes.NORMAL_USER)
        if '@' in term:
            users = query.filter(func.lower(Users.email) == term.lower()).all()
        elif len(digits) >= 10 and len(digits) == len(term.replace('+', '').replace(' ', '')):
            users = query.filter(Users.phone == digits[-10:]).all()
        elif term.upper().startswith(('CU', 'TKT')):
            ticket = SupportTickets.query.filter(
                func.upper(SupportTickets.ticket_number) == term.upper()).first()
            users = query.filter(Users.user_id == ticket.user_id).all() if ticket else []
        else:
            users = query.filter(Users.user_id == term).all()

        agent = current_user()
        audit.record(action='SUPPORT_CUSTOMER_SEARCH', entity_type='Users',
                     actor_user_id=str(agent.user_id),
                     actor_role=agent.role.role_name if agent.role else None,
                     notes=f'{len(users)} result(s)')
        return success([_customer_summary(u) for u in users[:10]])


@ns.route('/customers/<string:user_id>')
class DeskCustomerProfile(Resource):
    @ns.doc('desk_customer_profile', security='Bearer')
    @jwt_required()
    @roles_required(*DESK)
    def get(self, user_id):
        """
        A customer's profile and the status of their cards and payments.

        Read-only and masked. Card figures appear with where they came from;
        nothing here identifies a card beyond its bank and last four digits.
        """
        from portal.models.bill_payments import BillPayments
        from portal.models.cards import Cards, CardStatus
        from portal.models.credit_accounts import CreditAccounts
        from portal.models.credit_transactions import CreditTransactions
        from portal.models.emi_payments import EMIPayments
        from portal.models.manual_cards import ManualCards, ManualCardStatus

        customer = Users.query.filter_by(user_id=user_id).first()
        if not customer or (customer.role and customer.role.role_name != RoleTypes.NORMAL_USER):
            return failure(ErrorCode.NOT_FOUND, 'Customer not found.', 404)

        agent = current_user()
        audit.record(action='SUPPORT_PROFILE_VIEWED', entity_type='Users',
                     entity_id=customer.user_id, actor_user_id=str(agent.user_id),
                     actor_role=agent.role.role_name if agent.role else None,
                     on_behalf_of=str(customer.user_id))

        cards = [{
            'source': 'TOKENISED', 'source_label': 'Linked - limit set by CashU',
            'issuer_bank': c.card_issuer_bank, 'last4': c.last4,
            'network': c.card_network, 'status': c.status,
            'linked_at': iso(c.linked_at),
        } for c in Cards.query.filter(Cards.user_id == customer.user_id,
                                      Cards.status != CardStatus.DELETED).all()]
        cards += [{
            'source': 'MANUAL', 'source_label': 'User-entered - Not Bank Verified',
            'issuer_bank': m.issuer_bank, 'last4': m.last4, 'network': m.network,
            'status': m.status, 'linked_at': iso(m.created_on),
        } for m in ManualCards.query.filter_by(user_id=customer.user_id,
                                               status=ManualCardStatus.ACTIVE).all()]

        account = CreditAccounts.query.filter_by(user_id=customer.user_id).order_by(
            CreditAccounts.created_on.desc()).first()

        payments = [{
            'kind': 'Credit line', 'type': t.transaction_type, 'status': t.status,
            'amount': to_float(t.amount), 'reference': t.gateway_reference or t.credit_transaction_id,
            'failure_reason': t.failure_reason, 'at': iso(t.created_on),
        } for t in CreditTransactions.query.filter_by(user_id=customer.user_id)
            .order_by(CreditTransactions.created_on.desc()).limit(10)]
        payments += [{
            'kind': 'EMI payment', 'type': p.payment_mode, 'status': p.status,
            'amount': to_float(p.amount), 'reference': p.bbps_rrn or p.payment_id,
            'failure_reason': None, 'at': iso(p.created_on),
        } for p in EMIPayments.query.filter_by(user_id=customer.user_id)
            .order_by(EMIPayments.created_on.desc()).limit(10)]
        payments += [{
            'kind': 'Pay Bills', 'type': b.category, 'status': b.status,
            'amount': to_float(b.total_amount), 'reference': b.reference,
            'failure_reason': None, 'at': iso(b.created_on),
        } for b in BillPayments.query.filter_by(user_id=customer.user_id)
            .order_by(BillPayments.created_on.desc()).limit(10)]
        payments.sort(key=lambda p: p['at'] or '', reverse=True)

        tickets = SupportTickets.query.filter_by(user_id=customer.user_id).order_by(
            SupportTickets.created_on.desc()).limit(20).all()

        return success({
            'customer': _customer_summary(customer),
            'cards': cards,
            'credit_line': {
                'status': account.status,
                'credit_limit': to_float(account.credit_limit),
                'available_credit': to_float(account.available_credit),
                'outstanding': to_float(account.current_outstanding),
            } if account else None,
            'payments': payments[:15],
            'tickets': [desk_ticket_dict(t) for t in tickets],
            # Told to the screen so it can say why an action is missing.
            'agent_limits': ['No changes to credit limits, payments, refunds, KYC '
                             'or account status - escalate those to an admin.',
                             'No access to MPINs, full phone numbers, PAN, Aadhaar '
                             'or card numbers.'],
        })
