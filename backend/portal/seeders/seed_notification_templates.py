"""
Seed notification copy from the PRD 14.1 matrix.

Each row carries its regulatory basis, so an operator editing the copy can see
which messages are legal obligations rather than product decisions. SMS rows
carry a DLT template id because Indian carriers reject transactional SMS that is
not registered under an approved template.
"""

import logging

from portal import db
from portal.models.notifications import (
    NotificationChannel, NotificationEvent, NotificationPriority,
    NotificationTemplates,
)

logger = logging.getLogger('cashu')

E = NotificationEvent
C = NotificationChannel
P = NotificationPriority

# (event, channel, priority, title, body, dlt id, regulatory note)
TEMPLATES = [
    (E.NEW_CARD_LINKED, C.IN_APP, P.HIGH, 'Card linked',
     'Card ending in {last4} was successfully linked to your CashU account.',
     None, 'RBI Cyber Security Mandate'),
    (E.NEW_CARD_LINKED, C.SMS, P.HIGH, 'Card linked',
     'Card ending {last4} was linked to your CashU account. If this was not '
     'you, lock your account immediately.',
     'CASHU_CARD_LINK', 'RBI Cyber Security Mandate'),

    (E.TRANSFER_INITIATED, C.IN_APP, P.MEDIUM, 'Transfer processing',
     'Transfer of Rs. {amount} to A/c ending {account} is processing.',
     None, 'Standard UX'),

    (E.TRANSFER_SUCCEEDED, C.IN_APP, P.HIGH, 'Transfer successful',
     'Rs. {amount} has been credited to your account ending {account}. '
     'UTR: {utr}.', None, 'Audit trail / consumer protection'),
    (E.TRANSFER_SUCCEEDED, C.SMS, P.HIGH, 'Transfer successful',
     'Transfer of Rs. {amount} to A/c ending {account} successful. '
     'IMPS UTR: {utr}. - CashU',
     'CASHU_TXF_OK', 'Audit trail / consumer protection'),
    (E.TRANSFER_SUCCEEDED, C.EMAIL, P.HIGH, 'Your CashU transfer receipt',
     'Your transfer of Rs. {amount} to the account ending {account} completed '
     'successfully.\n\nIMPS UTR: {utr}\n\nYour receipt is available in the '
     'CashU app under Transactions.',
     None, 'Audit trail / consumer protection'),

    (E.TRANSFER_FAILED, C.IN_APP, P.HIGH, 'Transfer failed',
     'Your transfer of Rs. {amount} could not be completed. The charge has '
     'been reversed to your card.', None, 'Consumer Protection Act'),
    (E.TRANSFER_FAILED, C.SMS, P.HIGH, 'Transfer failed',
     'Transfer of Rs. {amount} failed. Card charge reversed to your issuer '
     'bank. Refund SLA: T+2 days. - CashU',
     'CASHU_TXF_FAIL', 'Consumer Protection Act'),

    (E.EMI_DUE_T7, C.IN_APP, P.LOW, 'EMI due in 7 days',
     'Reminder: your {provider} EMI of Rs. {amount} is due on {due_date}.',
     None, 'Proactive reminder'),

    (E.EMI_DUE_T1, C.SMS, P.HIGH, 'EMI due tomorrow',
     'Urgent: {provider} EMI of Rs. {amount} due tomorrow. Pay now to avoid '
     'late fees. - CashU', 'CASHU_EMI_DUE', 'Proactive reminder'),
    (E.EMI_DUE_T1, C.IN_APP, P.HIGH, 'EMI due tomorrow',
     'Your {provider} EMI of Rs. {amount} is due tomorrow.',
     None, 'Proactive reminder'),

    (E.EMI_PAID, C.IN_APP, P.HIGH, 'EMI paid',
     'Your {provider} EMI of Rs. {amount} has been paid. Reference: {utr}.',
     None, 'Statutory notification'),

    # -- The regulatory one. RBI requires this at least 24h before any
    #    recurring debit; CashU sends at 48h. It cannot be disabled.
    (E.AUTOPAY_PREDEBIT, C.SMS, P.CRITICAL, 'Upcoming auto-debit',
     'Notice: Rs. {amount} will be auto-debited from A/c {account} on '
     '{due_date} for {provider}. Mandate UMN: {umn}. - CashU',
     'CASHU_PREDEBIT', 'MANDATORY - RBI E-Mandate Framework'),
    (E.AUTOPAY_PREDEBIT, C.EMAIL, P.CRITICAL, 'Upcoming auto-debit notice',
     'This is your advance notice of an upcoming automatic debit.\n\n'
     'Amount: Rs. {amount}\nScheduled date: {due_date}\n'
     'Biller: {provider}\nMandate UMN: {umn}\n\n'
     'You can pause or cancel this mandate in the CashU app up to 24 hours '
     'before the debit date.',
     None, 'MANDATORY - RBI E-Mandate Framework'),
    (E.AUTOPAY_PREDEBIT, C.IN_APP, P.CRITICAL, 'Upcoming auto-debit',
     'Rs. {amount} will be debited on {due_date} for your {provider} EMI.',
     None, 'MANDATORY - RBI E-Mandate Framework'),

    (E.AUTOPAY_SUCCEEDED, C.SMS, P.HIGH, 'Auto-pay successful',
     'Auto-pay successful: Rs. {amount} debited for {provider} EMI. '
     'UTR: {utr}. - CashU', 'CASHU_AUTOPAY_OK', 'Statutory notification'),
    (E.AUTOPAY_SUCCEEDED, C.IN_APP, P.HIGH, 'Auto-pay successful',
     'Rs. {amount} was debited for your {provider} EMI.',
     None, 'Statutory notification'),

    (E.AUTOPAY_FAILED, C.SMS, P.CRITICAL, 'Auto-pay failed',
     'Urgent: Auto-pay failed due to insufficient funds. Retry scheduled for '
     '{retry_date}. Please maintain balance. - CashU',
     'CASHU_AUTOPAY_FAIL', 'Immediate alert'),
    (E.AUTOPAY_FAILED, C.IN_APP, P.CRITICAL, 'Auto-pay failed',
     'Your {provider} auto-debit of Rs. {amount} failed. We will retry on '
     '{retry_date}.', None, 'Immediate alert'),

    (E.SUSPICIOUS_LOGIN, C.SMS, P.CRITICAL, 'New sign-in detected',
     'Security alert: New login detected from {device} in {location}. If this '
     'was not you, freeze your account now. - CashU',
     'CASHU_SECURITY', 'RBI Cyber Security Mandate'),
    (E.SUSPICIOUS_LOGIN, C.IN_APP, P.CRITICAL, 'New sign-in detected',
     'A new device signed in to your account from {location}.',
     None, 'RBI Cyber Security Mandate'),

    (E.KYC_APPROVED, C.IN_APP, P.MEDIUM, 'KYC verified',
     'Your KYC has been verified. All CashU features are now available.',
     None, 'Standard UX'),
    (E.KYC_REJECTED, C.IN_APP, P.HIGH, 'KYC needs attention',
     'Your KYC could not be verified: {reason}. Please re-submit your '
     'documents.', None, 'Standard UX'),
    (E.BANK_VERIFIED, C.IN_APP, P.MEDIUM, 'Bank account verified',
     'Your bank account ending {account} is verified and ready for transfers.',
     None, 'Standard UX'),
]


def seed_notification_templates():
    created = 0

    for event, channel, priority, title, body, dlt_id, note in TEMPLATES:
        exists = NotificationTemplates.query.filter_by(
            event=event, channel=channel
        ).first()

        if not exists:
            db.session.add(NotificationTemplates(
                event=event,
                channel=channel,
                priority=priority,
                title_template=title,
                body_template=body,
                dlt_template_id=dlt_id,
                regulatory_note=note,
                is_active=True,
            ))
            created += 1

    if created:
        db.session.commit()
        logger.info(
            f'[Seeders] seed_notification_templates: created {created} template(s).'
        )
