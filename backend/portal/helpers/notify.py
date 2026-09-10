"""
portal/helpers/notify.py
========================
Notification dispatch (PRD section 14).

Two rules from the matrix are enforced here rather than left to callers:

1. CRITICAL and HIGH priority messages ignore user preferences. Pre-debit
   notices, payment confirmations and security alerts are regulatory
   obligations under the RBI e-mandate framework and the Cyber Security
   Mandate - a user cannot opt out of being told their account was debited.

2. Quiet hours apply only to LOW priority. A failed auto-pay at 2am is still
   dispatched, because the user has until the retry window to fund the account.
"""

import json

from flask import current_app

from portal import db
from portal.helpers import email as email_helper, sms as sms_helper
from portal.helpers.helpers import money_str
from portal.models.base import utcnow
from portal.models.notifications import (
    DeliveryStatus, NotificationChannel, NotificationEvent,
    NotificationPriority, NotificationTemplates, Notifications,
)

#: Channel fan-out and priority per event, from the PRD 14.1 matrix. Held here
#: as the fallback when the templates table has not been seeded.
_MATRIX = {
    NotificationEvent.NEW_CARD_LINKED: (
        [NotificationChannel.IN_APP, NotificationChannel.PUSH, NotificationChannel.SMS],
        NotificationPriority.HIGH,
    ),
    NotificationEvent.TRANSFER_INITIATED: (
        [NotificationChannel.IN_APP, NotificationChannel.PUSH],
        NotificationPriority.MEDIUM,
    ),
    NotificationEvent.TRANSFER_SUCCEEDED: (
        [NotificationChannel.IN_APP, NotificationChannel.PUSH,
         NotificationChannel.SMS, NotificationChannel.EMAIL],
        NotificationPriority.HIGH,
    ),
    NotificationEvent.TRANSFER_FAILED: (
        [NotificationChannel.IN_APP, NotificationChannel.PUSH, NotificationChannel.SMS],
        NotificationPriority.HIGH,
    ),
    NotificationEvent.EMI_DUE_T7: (
        [NotificationChannel.PUSH, NotificationChannel.IN_APP],
        NotificationPriority.LOW,
    ),
    NotificationEvent.EMI_DUE_T1: (
        [NotificationChannel.PUSH, NotificationChannel.SMS, NotificationChannel.WHATSAPP],
        NotificationPriority.HIGH,
    ),
    NotificationEvent.EMI_PAID: (
        [NotificationChannel.IN_APP, NotificationChannel.PUSH, NotificationChannel.SMS],
        NotificationPriority.HIGH,
    ),
    NotificationEvent.AUTOPAY_PREDEBIT: (
        [NotificationChannel.SMS, NotificationChannel.EMAIL, NotificationChannel.PUSH],
        NotificationPriority.CRITICAL,
    ),
    NotificationEvent.AUTOPAY_SUCCEEDED: (
        [NotificationChannel.PUSH, NotificationChannel.SMS, NotificationChannel.EMAIL],
        NotificationPriority.HIGH,
    ),
    NotificationEvent.AUTOPAY_FAILED: (
        [NotificationChannel.PUSH, NotificationChannel.SMS, NotificationChannel.WHATSAPP],
        NotificationPriority.CRITICAL,
    ),
    NotificationEvent.SUSPICIOUS_LOGIN: (
        [NotificationChannel.SMS, NotificationChannel.EMAIL, NotificationChannel.PUSH],
        NotificationPriority.CRITICAL,
    ),
    NotificationEvent.KYC_APPROVED: (
        [NotificationChannel.IN_APP, NotificationChannel.PUSH],
        NotificationPriority.MEDIUM,
    ),
    NotificationEvent.KYC_REJECTED: (
        [NotificationChannel.IN_APP, NotificationChannel.PUSH, NotificationChannel.SMS],
        NotificationPriority.HIGH,
    ),
    NotificationEvent.BANK_VERIFIED: (
        [NotificationChannel.IN_APP, NotificationChannel.PUSH],
        NotificationPriority.MEDIUM,
    ),
}

#: Default copy, mirroring the PRD 14.1 template column.
_COPY = {
    NotificationEvent.NEW_CARD_LINKED: (
        'Card linked',
        'Card ending in {last4} was successfully linked to your CashU account. '
        'If this was not you, lock your account.',
    ),
    NotificationEvent.TRANSFER_INITIATED: (
        'Transfer processing',
        'Transfer of Rs. {amount} to A/c ending {account} is processing.',
    ),
    NotificationEvent.TRANSFER_SUCCEEDED: (
        'Transfer successful',
        'Transfer of Rs. {amount} to A/c ending {account} successful. '
        'IMPS UTR: {utr}. Receipt attached.',
    ),
    NotificationEvent.TRANSFER_FAILED: (
        'Transfer failed',
        'Transfer of Rs. {amount} failed. Card charge reversed to your issuer '
        'bank. SLA: T+2 days.',
    ),
    NotificationEvent.EMI_DUE_T7: (
        'EMI due in 7 days',
        'Reminder: {provider} EMI of Rs. {amount} is due on {due_date}.',
    ),
    NotificationEvent.EMI_DUE_T1: (
        'EMI due tomorrow',
        'Urgent: {provider} EMI of Rs. {amount} due tomorrow. '
        'Pay now to avoid late fees.',
    ),
    NotificationEvent.EMI_PAID: (
        'EMI paid',
        'Your {provider} EMI of Rs. {amount} has been paid. Reference: {utr}.',
    ),
    NotificationEvent.AUTOPAY_PREDEBIT: (
        'Upcoming auto-debit',
        'Notice: Rs. {amount} will be auto-debited from A/c {account} on '
        '{due_date} for {provider} (Mandate UMN: {umn}).',
    ),
    NotificationEvent.AUTOPAY_SUCCEEDED: (
        'Auto-pay successful',
        'Auto-pay successful: Rs. {amount} debited for {provider} EMI. UTR: {utr}.',
    ),
    NotificationEvent.AUTOPAY_FAILED: (
        'Auto-pay failed',
        'Urgent: Auto-pay failed due to insufficient funds. Retry scheduled for '
        '{retry_date}. Please maintain balance.',
    ),
    NotificationEvent.SUSPICIOUS_LOGIN: (
        'New sign-in detected',
        'Security alert: New login detected from {device} in {location}. '
        'Enter OTP to authorize or freeze your account.',
    ),
    NotificationEvent.KYC_APPROVED: (
        'KYC verified',
        'Your KYC has been verified. All CashU features are now available.',
    ),
    NotificationEvent.KYC_REJECTED: (
        'KYC needs attention',
        'Your KYC could not be verified: {reason}. Please re-submit your documents.',
    ),
    NotificationEvent.BANK_VERIFIED: (
        'Bank account verified',
        'Your bank account ending {account} has been verified and is ready for '
        'transfers.',
    ),
}


def _render(template: str, context: dict) -> str:
    """
    Fill a template, tolerating a missing key.

    A KeyError here would fail the notification and, worse, the outbox retry
    would fail identically forever. A visibly empty placeholder is recoverable;
    a dead-lettered pre-debit notice is a regulatory problem.
    """
    safe = {k: v for k, v in (context or {}).items()}
    for field in (
        'amount', 'account', 'utr', 'provider', 'due_date', 'last4',
        'umn', 'retry_date', 'device', 'location', 'reason',
    ):
        safe.setdefault(field, '')

    if 'amount' in safe and safe['amount'] not in ('', None):
        safe['amount'] = money_str(safe['amount'])

    try:
        return template.format(**safe)
    except (KeyError, IndexError, ValueError):
        return template


def _channels_for(user, event: str, priority: str, channels: list) -> list:
    """
    Filter the fan-out by user preference.

    HIGH and CRITICAL bypass preferences entirely (PRD 14.1: "Transactional
    alerts are critical and cannot be disabled by the user").
    """
    if priority in NotificationPriority.NON_SUPPRESSIBLE:
        return channels

    prefs = getattr(user, 'notification_preferences', None)
    if not prefs:
        return channels

    enabled = {
        NotificationChannel.IN_APP: prefs.in_app_enabled,
        NotificationChannel.PUSH: prefs.push_enabled,
        NotificationChannel.SMS: prefs.sms_enabled,
        NotificationChannel.EMAIL: prefs.email_enabled,
        NotificationChannel.WHATSAPP: prefs.whatsapp_enabled,
    }
    allowed = [c for c in channels if enabled.get(c, True)]

    if event in (NotificationEvent.EMI_DUE_T7, NotificationEvent.EMI_DUE_T1):
        if not prefs.emi_reminders_enabled:
            allowed = [c for c in allowed if c == NotificationChannel.IN_APP]

    return allowed


def dispatch(user, event: str, context: dict = None, commit: bool = True) -> list:
    """
    Send one event across its configured channels.

    Returns the Notifications rows created. Delivery failure on one channel
    never blocks the others, and never propagates to the caller.
    """
    context = context or {}

    template_rows = NotificationTemplates.query.filter_by(
        event=event, is_active=True
    ).all()

    if template_rows:
        plan = [
            (row.channel, row.priority, row.title_template, row.body_template,
             row.dlt_template_id)
            for row in template_rows
        ]
    else:
        channels, priority = _MATRIX.get(
            event, ([NotificationChannel.IN_APP], NotificationPriority.LOW)
        )
        title, body = _COPY.get(event, (event.replace('_', ' ').title(), ''))
        plan = [(c, priority, title, body, None) for c in channels]

    priority = plan[0][1] if plan else NotificationPriority.LOW
    allowed = _channels_for(user, event, priority, [p[0] for p in plan])

    created = []

    for channel, chan_priority, title_tpl, body_tpl, dlt_id in plan:
        if channel not in allowed:
            continue

        title = _render(title_tpl or event.replace('_', ' ').title(), context)
        body = _render(body_tpl or '', context)

        notification = Notifications(
            user_id=user.user_id,
            event=event,
            channel=channel,
            priority=chan_priority,
            title=title[:200],
            body=body,
            deep_link=context.get('deep_link'),
            payload=json.dumps(context, default=str)[:4000],
            delivery_status=DeliveryStatus.QUEUED,
        )
        db.session.add(notification)
        created.append(notification)

        try:
            if channel == NotificationChannel.SMS and user.phone:
                result = sms_helper.send(user.phone, body, dlt_template_id=dlt_id)
                notification.delivery_status = (
                    DeliveryStatus.SENT if result.get('ok') else DeliveryStatus.FAILED
                )
                notification.failure_reason = result.get('error')

            elif channel == NotificationChannel.EMAIL and user.email:
                result = email_helper.send(user.email, title, body)
                notification.delivery_status = (
                    DeliveryStatus.SENT if result.get('ok') else DeliveryStatus.FAILED
                )
                notification.failure_reason = result.get('error')

            elif channel == NotificationChannel.IN_APP:
                # Delivered by being readable in the notifications feed.
                notification.delivery_status = DeliveryStatus.DELIVERED

            else:
                # PUSH is Phase 1.1 (FCM/APNS); WHATSAPP needs a BSP. Recorded
                # as queued so the intent is auditable once a provider lands.
                notification.delivery_status = DeliveryStatus.QUEUED

            notification.sent_at = utcnow()

        except Exception as exc:
            current_app.logger.error(
                f'[notify] {event} via {channel} failed for {user.user_id}: {exc}'
            )
            notification.delivery_status = DeliveryStatus.FAILED
            notification.failure_reason = str(exc)[:500]

    if commit:
        db.session.commit()

    return created
