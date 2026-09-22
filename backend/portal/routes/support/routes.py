"""
Support tickets and dispute threads.

Backs PRD US-015: an agent looks up a transaction by UTR or phone with PII
masked, so a dispute can be resolved without exposing identity data.
"""

import random
import uuid

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal import db
from portal.helpers import audit, support_bot
from portal.helpers.helpers import (
    ErrorCode, failure, iso, paginated, success,
)
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.validators import (
    sanitize_text, validate_choice, validate_pagination,
)
from portal.models.base import utcnow
from portal.models.support_messages import (
    SupportMessages, SupportSenderRole, SupportTickets, TicketCategory,
    TicketStatus,
)
from portal.models.transaction_errors import TransactionErrors

from . import ns

create_parser = reqparse.RequestParser()
create_parser.add_argument('subject', type=str, required=True, location='json')
create_parser.add_argument('message', type=str, required=True, location='json')
create_parser.add_argument('category', type=str, required=False, location='json',
                           default=TicketCategory.OTHER)
create_parser.add_argument('related_entity_type', type=str, required=False, location='json')
create_parser.add_argument('related_entity_id', type=str, required=False, location='json')

reply_parser = reqparse.RequestParser()
reply_parser.add_argument('message', type=str, required=True, location='json')

list_parser = reqparse.RequestParser()
list_parser.add_argument('page', type=int, default=1, location='args')
list_parser.add_argument('per_page', type=int, default=20, location='args')
list_parser.add_argument('status', type=str, required=False, location='args')


def _ticket_number() -> str:
    return f'CU{utcnow().strftime("%y%m%d")}{random.randint(1000, 9999)}'


def ticket_dict(ticket: SupportTickets, with_messages: bool = False) -> dict:
    data = {
        'ticket_id': ticket.ticket_id,
        'ticket_number': ticket.ticket_number,
        'subject': ticket.subject,
        'category': ticket.category,
        'status': ticket.status,
        'priority': ticket.priority,
        'related_entity_type': ticket.related_entity_type,
        'related_entity_id': ticket.related_entity_id,
        'created_on': iso(ticket.created_on),
        'resolved_at': iso(ticket.resolved_at),
        'message_count': ticket.messages.count(),
    }

    if with_messages:
        data['messages'] = [{
            'message_id': m.message_id,
            'sender_role': m.sender_role,
            'sender_name': m.sender_name,
            'body': m.body,
            'attachment_path': m.attachment_path,
            'created_on': iso(m.created_on),
        } for m in ticket.messages.order_by(SupportMessages.created_on.asc()).all()]

    return data


@ns.route('/tickets')
class TicketList(Resource):
    @ns.doc('list_tickets', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Support tickets raised by the signed-in user."""
        args = list_parser.parse_args()
        user = current_user()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = SupportTickets.query.filter_by(user_id=user.user_id)
        if args.get('status'):
            query = query.filter(SupportTickets.status == args['status'])

        pagination = query.order_by(SupportTickets.created_on.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return paginated(
            [ticket_dict(t) for t in pagination.items],
            page, per_page, pagination.total,
        )

    @ns.doc('create_ticket', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """Raise a support ticket."""
        args = create_parser.parse_args()
        user = current_user()

        subject = sanitize_text(args['subject'], 200)
        body = sanitize_text(args['message'], 4000)

        if not subject or not body:
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'Please describe your issue so we can help.',
                400,
            )

        category = args.get('category') or TicketCategory.OTHER
        if category not in TicketCategory.CHOICES:
            category = TicketCategory.OTHER

        ticket = SupportTickets(
            user_id=user.user_id,
            ticket_number=_ticket_number(),
            subject=subject,
            category=category,
            status=TicketStatus.OPEN,
            related_entity_type=sanitize_text(args.get('related_entity_type'), 50),
            related_entity_id=sanitize_text(args.get('related_entity_id'), 36),
        )
        db.session.add(ticket)
        db.session.flush()

        db.session.add(SupportMessages(
            ticket_id=ticket.ticket_id,
            sender_role=SupportSenderRole.USER,
            sender_id=str(user.user_id),
            sender_name=user.full_name,
            body=body,
        ))
        db.session.commit()

        audit.record(
            action='SUPPORT_TICKET_CREATED',
            entity_type='SupportTickets',
            entity_id=ticket.ticket_id,
            actor_user_id=str(user.user_id),
            after={'ticket_number': ticket.ticket_number, 'category': category},
        )

        return success(
            ticket_dict(ticket, with_messages=True),
            f'Ticket {ticket.ticket_number} created. We will respond within '
            '24 hours.',
            201,
        )


@ns.route('/tickets/<string:ticket_id>')
class TicketDetail(Resource):
    @ns.doc('get_ticket', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, ticket_id):
        user = current_user()
        ticket = SupportTickets.query.filter_by(
            ticket_id=ticket_id, user_id=user.user_id
        ).first()

        if not ticket:
            return failure(ErrorCode.NOT_FOUND, 'Ticket not found.', 404)

        return success(ticket_dict(ticket, with_messages=True))


@ns.route('/tickets/<string:ticket_id>/reply')
class TicketReply(Resource):
    @ns.doc('reply_ticket', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, ticket_id):
        """Add a message to a ticket thread."""
        args = reply_parser.parse_args()
        user = current_user()

        ticket = SupportTickets.query.filter_by(
            ticket_id=ticket_id, user_id=user.user_id
        ).first()
        if not ticket:
            return failure(ErrorCode.NOT_FOUND, 'Ticket not found.', 404)

        if ticket.status == TicketStatus.CLOSED:
            return failure(
                ErrorCode.CONFLICT,
                'This ticket is closed. Please raise a new one.',
                409,
            )

        body = sanitize_text(args['message'], 4000)
        if not body:
            return failure(
                ErrorCode.VALIDATION_ERROR, 'Enter a message.', 400
            )

        db.session.add(SupportMessages(
            ticket_id=ticket.ticket_id,
            sender_role=SupportSenderRole.USER,
            sender_id=str(user.user_id),
            sender_name=user.full_name,
            body=body,
        ))

        ticket.status = TicketStatus.AWAITING_AGENT
        db.session.commit()

        return success(ticket_dict(ticket, with_messages=True), 'Reply sent.')


# -- Transaction-aware support -----------------------------------------------

chat_parser = reqparse.RequestParser()
chat_parser.add_argument('reference_type', type=str, required=True, location='json')
chat_parser.add_argument('reference_id', type=str, required=True, location='json')
chat_parser.add_argument('intent', type=str, required=False, location='json')


@ns.route('/chat')
class SupportChat(Resource):
    @ns.doc('support_chat', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        The transaction-aware assistant.

        Opens with an explanation of *this* payment rather than a greeting, and
        the client sends an intent rather than free text - the bot only answers
        questions it can answer truthfully from the record.

        The context is loaded server-side from the reference and scoped to the
        caller, so nothing the client sends can widen what the bot will discuss.
        """
        args = chat_parser.parse_args()
        user = current_user()

        context = support_bot.load_context(
            user, args['reference_type'], args['reference_id']
        )

        if not context:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        intent = (args.get('intent') or '').upper()
        if intent and intent not in support_bot.Intent.CHOICES:
            return failure(
                ErrorCode.VALIDATION_ERROR, 'Unknown request.', 400
            )

        payload = (
            support_bot.reply(context, intent) if intent
            else support_bot.opening(context)
        )
        payload['context'] = context
        return success(payload)


escalate_parser = reqparse.RequestParser()
escalate_parser.add_argument('reference_type', type=str, required=True, location='json')
escalate_parser.add_argument('reference_id', type=str, required=True, location='json')
escalate_parser.add_argument('note', type=str, required=False, location='json')


@ns.route('/escalate')
class EscalateToSupport(Resource):
    @ns.doc('escalate_to_support', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Hand a failed payment to a human, with the details already attached.

        The whole point: the user does not retype the transaction id, the
        amount, the method or the reason. The ticket opens with a system
        message carrying all of it, and the error row is linked back so an
        agent reviewing the failure can see the conversation.
        """
        args = escalate_parser.parse_args()
        user = current_user()

        context = support_bot.load_context(
            user, args['reference_type'], args['reference_id']
        )
        if not context:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        category = (
            TicketCategory.TRANSFER_ISSUE
            if args['reference_type'] == 'Transfers'
            else TicketCategory.EMI_ISSUE
        )

        ticket = SupportTickets(
            user_id=user.user_id,
            ticket_number=f'TKT{uuid.uuid4().hex[:8].upper()}',
            category=category,
            subject=f'Failed payment - {context["error_code"]}',
            status=TicketStatus.OPEN,
            priority='HIGH' if not context['is_retryable'] else 'MEDIUM',
            related_entity_type=args['reference_type'],
            related_entity_id=args['reference_id'],
        )
        db.session.add(ticket)
        db.session.flush()

        amount = (
            f'Rs. {context["amount"]:,.2f}' if context['amount'] is not None
            else 'unknown'
        )
        db.session.add(SupportMessages(
            ticket_id=ticket.ticket_id,
            sender_role=SupportSenderRole.SYSTEM,
            sender_name='CashU',
            body=(
                f'Transaction: {context["transaction_id"]}\n'
                f'Amount: {amount}\n'
                f'Method: {context["payment_method"]}\n'
                f'Status: {context["status"]}\n'
                f'Reason: {context["error_message"]}\n'
                f'Code: {context["error_code"]} ({context["error_type"]})\n'
                f'When: {context["created_at"]}'
            ),
        ))

        if args.get('note'):
            db.session.add(SupportMessages(
                ticket_id=ticket.ticket_id,
                sender_role=SupportSenderRole.USER,
                sender_id=str(user.user_id),
                sender_name=user.full_name,
                body=sanitize_text(args['note'], 1000),
            ))

        # Link the error row back, so the admin error view and the ticket are
        # two doors into the same incident.
        if context.get('error_id'):
            error_row = TransactionErrors.query.filter_by(
                error_id=context['error_id']
            ).first()
            if error_row:
                error_row.support_ticket_id = ticket.ticket_id

        db.session.commit()

        return success({
            'ticket_id': ticket.ticket_id,
            'ticket_number': ticket.ticket_number,
            'status': ticket.status,
        }, 'Our team has your payment details. We will be in touch.', 201)


@ns.route('/transaction-error/<string:reference_type>/<string:reference_id>')
class TransactionErrorDetail(Resource):
    @ns.doc('get_transaction_error', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, reference_type, reference_id):
        """
        Why one payment failed, for the failure screen.

        Returns the user-facing view only: no gateway payload, no provider
        text. Those are for support, not for the person who just lost a
        payment.
        """
        user = current_user()
        context = support_bot.load_context(user, reference_type, reference_id)

        if not context:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        return success(context)

