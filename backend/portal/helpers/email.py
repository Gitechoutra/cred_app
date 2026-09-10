"""
portal/helpers/email.py
=======================
Transactional email (PRD section 14: transfer receipts, pre-debit notices).
"""

from flask import current_app
from flask_mail import Mail, Message

mail = Mail()


def init_mail(app):
    mail.init_app(app)
    app.logger.info('Initialized Mail')


def _configured() -> bool:
    return bool(current_app.config.get('MAIL_USERNAME'))


def send(to: str, subject: str, body: str, html: str = None) -> dict:
    """
    Send one message.

    Never raises, for the same reason as SMS: a mail outage must not fail the
    financial action that triggered the notification.
    """
    if not to:
        return {'ok': False, 'error': 'No recipient address.'}

    if not _configured():
        current_app.logger.info(
            f'[email] (not configured, logging only) to={to} subject={subject}'
        )
        return {'ok': True, 'provider': 'LOG'}

    try:
        message = Message(
            subject=subject,
            recipients=[to],
            body=body,
            html=html,
            sender=current_app.config.get('MAIL_DEFAULT_SENDER'),
        )
        mail.send(message)
        return {'ok': True, 'provider': 'SMTP'}
    except Exception as exc:
        current_app.logger.error(f'[email] send failed to={to}: {exc}')
        return {'ok': False, 'error': str(exc)}
