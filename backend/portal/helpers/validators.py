"""
portal/helpers/validators.py
============================
Input validation. Every value that reaches a money path is checked here first.

Raises ValidationError, which the route layer turns into a 400 with the
PRD-specified user-facing message.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

# PRD FR-001: Indian mobile carrier format.
MOBILE_RE = re.compile(r'^[6-9]\d{9}$')
# PAN: five letters, four digits, one letter.
PAN_RE = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')
# IFSC: four letters, a zero, six alphanumerics.
IFSC_RE = re.compile(r'^[A-Z]{4}0[A-Z0-9]{6}$')
AADHAAR_RE = re.compile(r'^\d{12}$')
UPI_VPA_RE = re.compile(r'^[\w.\-]{2,256}@[a-zA-Z]{2,64}$')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$')
OTP_RE = re.compile(r'^\d{6}$')
MPIN_RE = re.compile(r'^\d{6}$')


class ValidationError(Exception):
    def __init__(self, message: str, field: str = None):
        super().__init__(message)
        self.message = message
        self.field = field


def validate_mobile(value: str, field: str = 'phone') -> str:
    value = (value or '').strip().replace(' ', '')
    # Accept and normalise the common +91 / 91 / 0 prefixes users actually type.
    if value.startswith('+91'):
        value = value[3:]
    elif value.startswith('91') and len(value) == 12:
        value = value[2:]
    elif value.startswith('0') and len(value) == 11:
        value = value[1:]

    if not MOBILE_RE.match(value):
        raise ValidationError('Enter a valid 10-digit Indian mobile number.', field)
    return value


def validate_otp(value: str, field: str = 'otp') -> str:
    value = (value or '').strip()
    if not OTP_RE.match(value):
        raise ValidationError('OTP must be 6 digits.', field)
    return value


def validate_mpin(value: str, field: str = 'mpin') -> str:
    value = (value or '').strip()
    if not MPIN_RE.match(value):
        raise ValidationError('MPIN must be 6 digits.', field)

    # Reject the PINs that a shoulder-surfer or a brute-forcer tries first.
    if len(set(value)) == 1:
        raise ValidationError('MPIN cannot be the same digit repeated.', field)
    ascending = ''.join(str(d) for d in range(10)) * 2
    descending = ascending[::-1]
    if value in ascending or value in descending:
        raise ValidationError('MPIN cannot be a sequence of consecutive digits.', field)
    return value


def validate_pan(value: str, field: str = 'pan_number') -> str:
    value = (value or '').strip().upper()
    if not PAN_RE.match(value):
        raise ValidationError('Enter a valid PAN (e.g. ABCDE1234F).', field)
    return value


def validate_aadhaar(value: str, field: str = 'aadhaar_number') -> str:
    value = (value or '').strip().replace(' ', '').replace('-', '')
    if not AADHAAR_RE.match(value):
        raise ValidationError('Enter a valid 12-digit Aadhaar number.', field)
    return value


def validate_ifsc(value: str, field: str = 'ifsc_code') -> str:
    value = (value or '').strip().upper()
    if not IFSC_RE.match(value):
        raise ValidationError('Enter a valid 11-character IFSC code.', field)
    return value


def validate_account_number(value: str, field: str = 'account_number') -> str:
    value = (value or '').strip().replace(' ', '')
    if not value.isdigit() or not (6 <= len(value) <= 20):
        raise ValidationError('Enter a valid bank account number.', field)
    return value


def validate_upi_vpa(value: str, field: str = 'upi_vpa') -> str:
    value = (value or '').strip().lower()
    if not UPI_VPA_RE.match(value):
        raise ValidationError('Enter a valid UPI ID (e.g. name@bank).', field)
    return value


def validate_email(value: str, field: str = 'email') -> str:
    value = (value or '').strip().lower()
    if not EMAIL_RE.match(value):
        raise ValidationError('Enter a valid email address.', field)
    return value


def validate_amount(
    value,
    field: str = 'amount',
    minimum: Decimal = None,
    maximum: Decimal = None,
) -> Decimal:
    """
    Parse and bound a monetary amount.

    Returns Decimal, never float - binary floats cannot represent 0.01 exactly
    and the rounding error compounds across a fee calculation.
    """
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError('Enter a valid amount.', field)

    if amount <= 0:
        raise ValidationError('Amount must be greater than zero.', field)
    if amount.as_tuple().exponent < -2:
        raise ValidationError('Amount cannot have more than 2 decimal places.', field)
    if minimum is not None and amount < minimum:
        raise ValidationError(
            f'Minimum amount is Rs. {minimum:,.2f}.', field
        )
    if maximum is not None and amount > maximum:
        raise ValidationError(
            f'Maximum amount is Rs. {maximum:,.2f}.', field
        )
    return amount


def validate_choice(value, choices, field: str = 'value'):
    if value not in choices:
        raise ValidationError(
            f"Invalid {field}. Expected one of: {', '.join(map(str, choices))}.", field
        )
    return value


def validate_day_of_month(value, field: str = 'due_day') -> int:
    try:
        day = int(value)
    except (TypeError, ValueError):
        raise ValidationError('Enter a valid day of the month.', field)
    if not (1 <= day <= 31):
        raise ValidationError('Day of month must be between 1 and 31.', field)
    return day


def validate_date(value, field: str = 'date', fmt: str = '%Y-%m-%d'):
    if not value:
        return None
    try:
        return datetime.strptime(value, fmt).date()
    except (TypeError, ValueError):
        raise ValidationError(f'Enter a valid date in {fmt} format.', field)


def validate_pagination(page, per_page, max_per_page: int = 100):
    try:
        page = max(1, int(page or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(per_page or 20)
    except (TypeError, ValueError):
        per_page = 20
    per_page = max(1, min(per_page, max_per_page))
    return page, per_page


def validate_expiry(month: str, year: str):
    """Card expiry, rejecting anything already past (ERR-009)."""
    try:
        m, y = int(month), int(year)
    except (TypeError, ValueError):
        raise ValidationError('Enter a valid card expiry.', 'expiry')

    if not (1 <= m <= 12):
        raise ValidationError('Expiry month must be between 01 and 12.', 'expiry_month')
    if y < 100:
        y += 2000

    now = datetime.utcnow()
    if y < now.year or (y == now.year and m < now.month):
        raise ValidationError('This card has expired.', 'expiry')
    return f"{m:02d}", str(y)


def validate_idempotency_key(value: str) -> str:
    """
    PRD 9.4: a client-generated UUIDv4 in X-Idempotency-Key.

    Required, not optional - without it a double-tapped Confirm button charges
    the card twice, and no amount of frontend debouncing is a guarantee.
    """
    value = (value or '').strip()
    if not value:
        raise ValidationError(
            'X-Idempotency-Key header is required for this request.', 'X-Idempotency-Key'
        )
    if not (8 <= len(value) <= 64):
        raise ValidationError(
            'X-Idempotency-Key must be between 8 and 64 characters.', 'X-Idempotency-Key'
        )
    return value


def sanitize_text(value: str, max_length: int = 500) -> str:
    if not value:
        return ''
    return re.sub(r'[\x00-\x1f\x7f]', '', str(value)).strip()[:max_length]
