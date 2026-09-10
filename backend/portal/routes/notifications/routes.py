"""
Notification feed and preferences (PRD FR-011, section 14).

Preferences gate LOW and MEDIUM priority only. Transactional alerts - OTPs,
payment confirmations, pre-debit notices, security alerts - are regulatory
obligations and cannot be switched off, which the preferences endpoint states
explicitly rather than silently ignoring the toggle.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal import db
from portal.helpers.helpers import (
    ErrorCode, failure, iso, paginated, success,
)
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.validators import validate_pagination
from portal.models.base import utcnow
from portal.models.notifications import (
    NotificationPreferences, Notifications,
)

from . import ns

list_parser = reqparse.RequestParser()
list_parser.add_argument('page', type=int, default=1, location='args')
list_parser.add_argument('per_page', type=int, default=20, location='args')
list_parser.add_argument('unread_only', type=bool, default=False, location='args')

prefs_parser = reqparse.RequestParser()
prefs_parser.add_argument('in_app_enabled', type=bool, required=False, location='json')
prefs_parser.add_argument('push_enabled', type=bool, required=False, location='json')
prefs_parser.add_argument('sms_enabled', type=bool, required=False, location='json')
prefs_parser.add_argument('email_enabled', type=bool, required=False, location='json')
prefs_parser.add_argument('whatsapp_enabled', type=bool, required=False, location='json')
prefs_parser.add_argument('emi_reminders_enabled', type=bool, required=False, location='json')
prefs_parser.add_argument('marketing_enabled', type=bool, required=False, location='json')


@ns.route('')
class NotificationList(Resource):
    @ns.doc('list_notifications', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """In-app notification feed."""
        args = list_parser.parse_args()
        user = current_user()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        from portal.models.notifications import NotificationChannel

        query = Notifications.query.filter_by(
            user_id=user.user_id, channel=NotificationChannel.IN_APP
        )
        if args.get('unread_only'):
            query = query.filter(Notifications.is_read.is_(False))

        pagination = query.order_by(Notifications.created_on.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        unread = Notifications.query.filter_by(
            user_id=user.user_id,
            channel=NotificationChannel.IN_APP,
            is_read=False,
        ).count()

        return paginated(
            [{
                'notification_id': n.notification_id,
                'event': n.event,
                'priority': n.priority,
                'title': n.title,
                'body': n.body,
                'deep_link': n.deep_link,
                'is_read': n.is_read,
                'created_on': iso(n.created_on),
            } for n in pagination.items],
            page, per_page, pagination.total,
            unread_count=unread,
        )


@ns.route('/<string:notification_id>/read')
class MarkRead(Resource):
    @ns.doc('mark_read', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, notification_id):
        """Mark one notification read."""
        user = current_user()

        notification = Notifications.query.filter_by(
            notification_id=notification_id, user_id=user.user_id
        ).first()

        if not notification:
            return failure(ErrorCode.NOT_FOUND, 'Notification not found.', 404)

        if not notification.is_read:
            notification.is_read = True
            notification.read_at = utcnow()
            db.session.commit()

        return success(None, 'Marked as read.')


@ns.route('/read-all')
class MarkAllRead(Resource):
    @ns.doc('mark_all_read', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """Mark every unread notification read."""
        user = current_user()

        updated = Notifications.query.filter_by(
            user_id=user.user_id, is_read=False
        ).update({'is_read': True, 'read_at': utcnow()}, synchronize_session=False)
        db.session.commit()

        return success({'marked': updated}, 'All notifications marked as read.')


@ns.route('/preferences')
class Preferences(Resource):
    @ns.doc('get_preferences', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Notification preferences, with the non-suppressible list."""
        user = current_user()
        prefs = user.notification_preferences

        if not prefs:
            prefs = NotificationPreferences(user_id=user.user_id)
            db.session.add(prefs)
            db.session.commit()

        return success({
            'in_app_enabled': prefs.in_app_enabled,
            'push_enabled': prefs.push_enabled,
            'sms_enabled': prefs.sms_enabled,
            'email_enabled': prefs.email_enabled,
            'whatsapp_enabled': prefs.whatsapp_enabled,
            'emi_reminders_enabled': prefs.emi_reminders_enabled,
            'marketing_enabled': prefs.marketing_enabled,
            # Surfaced so the UI can show these as locked with a reason, rather
            # than offering a toggle that quietly does nothing.
            'always_on': [
                {
                    'event': 'AUTOPAY_PREDEBIT',
                    'label': 'Auto-debit notices',
                    'reason': 'Required by the RBI e-Mandate framework.',
                },
                {
                    'event': 'TRANSFER_SUCCEEDED',
                    'label': 'Payment confirmations',
                    'reason': 'Required for your transaction records.',
                },
                {
                    'event': 'SUSPICIOUS_LOGIN',
                    'label': 'Security alerts',
                    'reason': 'Required by the RBI Cyber Security Mandate.',
                },
            ],
        })

    @ns.doc('update_preferences', security='Bearer')
    @jwt_required()
    @active_user_required
    def patch(self):
        """Update notification preferences."""
        args = prefs_parser.parse_args()
        user = current_user()
        prefs = user.notification_preferences

        if not prefs:
            prefs = NotificationPreferences(user_id=user.user_id)
            db.session.add(prefs)

        for field in (
            'in_app_enabled', 'push_enabled', 'sms_enabled', 'email_enabled',
            'whatsapp_enabled', 'emi_reminders_enabled', 'marketing_enabled',
        ):
            if args.get(field) is not None:
                setattr(prefs, field, args[field])

        db.session.commit()

        return success(None, 'Notification preferences updated.')
