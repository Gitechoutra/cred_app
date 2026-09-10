"""
portal/helpers/sms.py
=====================
SMS dispatch (PRD section 21: DLT-compliant gateway).

Indian carriers reject transactional SMS that is not registered against an
approved DLT template, so every message here maps to a template id rather than
being composed freely. No vendor is signed yet (PRD open decisions), so the
default sink writes to the log; swapping in Gupshup, Exotel or Karix means
implementing _send_live and nothing else.
"""

from flask import current_app


def _configured() -> bool:
    return bool(current_app.config.get('SMS_PROVIDER_KEY'))


def _send(phone: str, body: str, dlt_template_id: str = None) -> dict:
    """
    Deliver one message.

    Never raises. A failed SMS must not roll back the transfer that triggered
    it - the notification is retried from the outbox instead.
    """
    if not _configured():
        current_app.logger.info(
            f'[sms] (not configured, logging only) to={phone}: {body}'
        )
        return {'ok': True, 'provider': 'LOG', 'reference': None}

    try:
        return _send_live(phone, body, dlt_template_id)
    except Exception as exc:
        current_app.logger.error(f'[sms] send failed to={phone}: {exc}')
        return {'ok': False, 'error': str(exc)}


def _send_live(phone: str, body: str, dlt_template_id: str = None) -> dict:
    """Live gateway call. Implement when a DLT-registered vendor is signed."""
    raise NotImplementedError('No live SMS provider is configured.')


def send_otp(phone: str, code: str, purpose: str = None, ttl_seconds: int = 180) -> dict:
    """
    Send an authentication code.

    The code is passed to the gateway and never persisted or echoed into the
    application log at INFO in a deployed environment.
    """
    minutes = max(1, ttl_seconds // 60)
    body = (
        f'{code} is your CashU verification code. '
        f'Valid for {minutes} minute(s). Do not share it with anyone.'
    )
    return _send(phone, body, dlt_template_id='CASHU_OTP')


def send(phone: str, body: str, dlt_template_id: str = None) -> dict:
    return _send(phone, body, dlt_template_id)
