"""
portal/helpers/upi_qr.py
========================
Parses and validates a scanned UPI QR code.

A QR code is untrusted input that arrives by pointing a camera at a sticker on
a counter. Anyone can print one. So this module treats the payload as hostile:
it parses strictly, validates every field it keeps, discards everything it does
not recognise, and never echoes raw scanned text back to the client.

The format is NPCI's UPI deep link:

    upi://pay?pa=merchant@bank&pn=Merchant%20Name&am=100.00&cu=INR&tn=Note

Only `pa` is required. `am` is frequently absent - a shop sticker is reused for
every customer - which is why the confirmation screen has to let the payer type
an amount.

Deliberately *not* handled: `mode`, `orgid`, `sign` and the other fields used
by verified-merchant QR signing. Accepting a `sign` we cannot verify would be
worse than ignoring it, because it would look like we had checked something.
"""

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, unquote, urlparse


class QRError(Exception):
    """A QR we will not act on, with a reason fit to show the scanner screen."""

    def __init__(self, message, code='INVALID_QR'):
        super().__init__(message)
        self.message = message
        self.code = code


#: A VPA is `handle@psp`. Stricter than the transfer validator on purpose: this
#: address comes off a sticker rather than out of our own database.
_VPA_RE = re.compile(r'^[A-Za-z0-9.\-_]{2,64}@[A-Za-z]{2,32}$')

#: Payee names are display-only, so anything that could be read as markup or a
#: control sequence is stripped rather than escaped downstream.
_NAME_ALLOWED = re.compile(r'[^A-Za-z0-9 .,&\'\-/()]')

_MAX_NAME = 80
_MAX_NOTE = 120

#: The ceiling exists so a tampered QR cannot present a plausible-looking huge
#: amount that a distracted person confirms. The real limits are applied by the
#: payment path; this is a sanity bound on scanned input.
_MAX_SCANNED_AMOUNT = Decimal('200000')


def parse(raw: str) -> dict:
    """
    Turn scanned text into payment details, or raise QRError.

    Returns only fields we understand and have validated. The caller never sees
    the raw payload, so a QR carrying extra parameters cannot smuggle anything
    into the confirmation screen.
    """
    if not raw or not isinstance(raw, str):
        raise QRError('Nothing was scanned. Try again.', 'EMPTY_QR')

    text = raw.strip()

    if len(text) > 2048:
        raise QRError('That QR code is not a payment code.', 'UNSUPPORTED_QR')

    parsed = urlparse(text)

    if parsed.scheme.lower() != 'upi':
        raise QRError(
            'That is not a UPI payment QR code.', 'UNSUPPORTED_QR'
        )

    # upi://pay and upi://collect both appear in the wild. Only pay is a
    # request for the scanner to send money; collect asks *us* to request money
    # from the person scanning, which is not what this screen does.
    if parsed.netloc.lower() not in ('pay', ''):
        raise QRError(
            'This QR code is asking for a payment request, which is not '
            'supported here.',
            'UNSUPPORTED_QR',
        )

    fields = parse_qs(parsed.query, keep_blank_values=False)

    vpa = _single(fields, 'pa')
    if not vpa:
        raise QRError('This QR code has no payment address.', 'INVALID_QR')

    vpa = unquote(vpa).strip()
    if not _VPA_RE.match(vpa):
        raise QRError('The payment address in this QR code is not valid.',
                      'INVALID_VPA')

    currency = (_single(fields, 'cu') or 'INR').upper()
    if currency != 'INR':
        raise QRError('Only rupee payments are supported.', 'UNSUPPORTED_CURRENCY')

    amount = None
    raw_amount = _single(fields, 'am')
    if raw_amount:
        amount = _amount(raw_amount)

    return {
        'vpa': vpa,
        'payee_name': _clean_name(_single(fields, 'pn')) or vpa.split('@')[0],
        'amount': amount,
        'amount_locked': amount is not None,
        'note': _clean_text(_single(fields, 'tn'), _MAX_NOTE),
        # The merchant's own reference, echoed back on the payment so the payee
        # can reconcile. Treated as an opaque token and length-capped.
        'reference': _clean_text(_single(fields, 'tr'), 40),
        'currency': currency,
    }


def _single(fields: dict, key: str):
    values = fields.get(key)
    return values[0] if values else None


def _amount(raw: str) -> Decimal:
    try:
        value = Decimal(unquote(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        raise QRError('The amount in this QR code is not valid.', 'INVALID_AMOUNT')

    if value <= 0:
        raise QRError('The amount in this QR code is not valid.', 'INVALID_AMOUNT')
    if value.as_tuple().exponent < -2:
        raise QRError('The amount in this QR code is not valid.', 'INVALID_AMOUNT')
    if value > _MAX_SCANNED_AMOUNT:
        raise QRError(
            f'This QR code is for Rs. {value:,.2f}, which is above the limit '
            f'for a scanned payment.',
            'AMOUNT_TOO_LARGE',
        )

    return value


def _clean_name(value: str) -> str:
    if not value:
        return None
    cleaned = _NAME_ALLOWED.sub('', unquote(value)).strip()
    return cleaned[:_MAX_NAME] or None


def _clean_text(value: str, limit: int) -> str:
    if not value:
        return None
    cleaned = _NAME_ALLOWED.sub('', unquote(value)).strip()
    return cleaned[:limit] or None


def masked_vpa(vpa: str) -> str:
    """
    A VPA fit for a receipt or a support thread.

    Keeps enough to recognise the payee and drops enough that a screenshot of a
    transaction does not hand over a complete payment address.
    """
    if not vpa or '@' not in vpa:
        return vpa or ''

    handle, psp = vpa.split('@', 1)
    if len(handle) <= 3:
        return f'{handle[0]}***@{psp}'
    return f'{handle[:2]}***{handle[-1]}@{psp}'
