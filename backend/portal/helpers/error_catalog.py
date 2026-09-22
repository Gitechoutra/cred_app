"""
portal/helpers/error_catalog.py
===============================
Turns a failure into something a person can act on.

Three jobs, and they are deliberately separate:

1. **Classify.** Map whatever came back - our own ERR-nnn codes, a Razorpay
   reason, a Cashfree code, a raw string - onto one error type and one plain
   sentence. An unmapped code still produces a usable record rather than a
   shrug.

2. **Advise.** Each type carries what to offer next. "Card declined" and
   "gateway timed out" are both failures, but one wants a different card and
   the other wants the same one again in a minute; offering the wrong action
   wastes the user's time and, on a timeout, risks a double payment.

3. **Sanitise.** Provider payloads are kept for diagnosis, so they have to be
   stripped first. This is the only place that decides what may be written
   down, which is why the redaction is here and not at each call site.

The rule the whole module exists to serve: never show "Payment failed" when
something more specific is known.
"""

import json
import re

from portal.models.transaction_errors import ErrorType


class Action:
    """Actions the client can render. The client owns the wording."""

    RETRY = 'RETRY'
    RETRY_LATER = 'RETRY_LATER'
    OTHER_METHOD = 'OTHER_METHOD'
    OTHER_CARD = 'OTHER_CARD'
    TRY_UPI = 'TRY_UPI'
    SMALLER_AMOUNT = 'SMALLER_AMOUNT'
    VIEW_TRANSACTION = 'VIEW_TRANSACTION'
    CONTACT_SUPPORT = 'CONTACT_SUPPORT'
    COMPLETE_KYC = 'COMPLETE_KYC'
    CHECK_STATUS = 'CHECK_STATUS'


#: type -> (retryable, ordered actions)
#
# Order matters: the first is what the primary button does. On a timeout the
# primary action is *check the status*, not retry - a timed-out charge may well
# have gone through, and inviting a retry first is how a user pays twice.
_TYPE_ADVICE = {
    ErrorType.INSTRUMENT: (True, [Action.OTHER_CARD, Action.TRY_UPI,
                                  Action.VIEW_TRANSACTION, Action.CONTACT_SUPPORT]),
    ErrorType.INSUFFICIENT: (True, [Action.SMALLER_AMOUNT, Action.OTHER_CARD,
                                    Action.TRY_UPI, Action.CONTACT_SUPPORT]),
    ErrorType.AUTHENTICATION: (True, [Action.RETRY, Action.OTHER_CARD,
                                      Action.CONTACT_SUPPORT]),
    ErrorType.LIMIT: (False, [Action.SMALLER_AMOUNT, Action.RETRY_LATER,
                              Action.VIEW_TRANSACTION, Action.CONTACT_SUPPORT]),
    ErrorType.GATEWAY: (True, [Action.RETRY_LATER, Action.OTHER_METHOD,
                               Action.CONTACT_SUPPORT]),
    ErrorType.NETWORK: (True, [Action.CHECK_STATUS, Action.RETRY_LATER,
                               Action.CONTACT_SUPPORT]),
    ErrorType.VERIFICATION: (False, [Action.CHECK_STATUS, Action.VIEW_TRANSACTION,
                                     Action.CONTACT_SUPPORT]),
    ErrorType.DUPLICATE: (False, [Action.VIEW_TRANSACTION, Action.CONTACT_SUPPORT]),
    ErrorType.CANCELLED: (True, [Action.RETRY, Action.OTHER_METHOD]),
    ErrorType.COMPLIANCE: (False, [Action.COMPLETE_KYC, Action.CONTACT_SUPPORT]),
    ErrorType.INTERNAL: (True, [Action.RETRY_LATER, Action.CONTACT_SUPPORT]),
    ErrorType.UNKNOWN: (True, [Action.RETRY, Action.OTHER_METHOD,
                               Action.CONTACT_SUPPORT]),
}


#: code -> (type, user-facing sentence)
#
# The sentence is written for the person who just lost a payment: it says what
# happened and, where there is one, what they can do. No codes, no vendor
# names, no blame.
_CATALOG = {
    # -- our own PRD codes ------------------------------------------------
    'ERR-001': (ErrorType.INSTRUMENT,
                'This card cannot be used. Only credit cards are supported.'),
    'ERR-002': (ErrorType.AUTHENTICATION,
                'Your bank could not verify the payment. The authentication '
                'was cancelled or timed out.'),
    'ERR-003': (ErrorType.INSUFFICIENT,
                'Your card does not have enough available limit for this amount.'),
    'ERR-004': (ErrorType.COMPLIANCE,
                'The name on the bank account does not match your verified name.'),
    'ERR-005': (ErrorType.NETWORK,
                'The payment gateway did not respond in time. We are confirming '
                'what happened before anything is charged again.'),
    'ERR-006': (ErrorType.GATEWAY,
                'Your card was charged but the transfer to your bank could not '
                'be completed. The amount is being returned to your card.'),
    'ERR-007': (ErrorType.DUPLICATE,
                'This payment has already been made.'),
    'ERR-008': (ErrorType.INSUFFICIENT,
                'The auto-pay mandate bounced, usually because the account did '
                'not have enough balance on the due date.'),
    'ERR-009': (ErrorType.INSTRUMENT,
                'This card has expired. Please link the renewed card.'),
    'ERR-010': (ErrorType.GATEWAY,
                'Your lender is not accepting payments right now. This is '
                'usually brief.'),
    'ERR-011': (ErrorType.LIMIT,
                'Too many payment attempts in a short time. For your security '
                'this is paused briefly.'),

    # -- internal --------------------------------------------------------
    'LIMIT_EXCEEDED': (ErrorType.LIMIT,
                       'This amount is above your transfer limit.'),
    'VALIDATION_ERROR': (ErrorType.INSTRUMENT,
                         'Some of the payment details were not valid.'),
    'KYC_REQUIRED': (ErrorType.COMPLIANCE,
                     'Complete your KYC verification to make this payment.'),
    'INSTRUMENT_NOT_PERMITTED': (ErrorType.COMPLIANCE,
                                 'This payment method cannot be used for this '
                                 'type of payment.'),
    'FEATURE_DISABLED': (ErrorType.INTERNAL,
                         'This payment method is temporarily unavailable.'),
    'PROVIDER_ERROR': (ErrorType.GATEWAY,
                       'The payment provider could not process this. Nothing '
                       'was charged.'),
    'INTERNAL_ERROR': (ErrorType.INTERNAL,
                       'Something went wrong on our side. Nothing was charged.'),
    'USER_CANCELLED': (ErrorType.CANCELLED,
                       'You cancelled this payment. Nothing was charged.'),
    'AMOUNT_BELOW_MINIMUM': (ErrorType.INSTRUMENT,
                             'This amount is below the minimum we can process.'),
    'ORDER_MISMATCH': (ErrorType.VERIFICATION,
                       'We could not match this payment to your order. Nothing '
                       'was charged.'),
    'CONFLICT': (ErrorType.DUPLICATE,
                 'A payment for this is already in progress.'),

    # -- gateway codes ---------------------------------------------------
    'CARD_DECLINED': (ErrorType.INSTRUMENT,
                      'Your bank declined the payment. They do not always say '
                      'why, so it is worth trying another card.'),
    'GATEWAY_TIMEOUT': (ErrorType.NETWORK,
                        'The payment gateway did not respond in time.'),
    'GATEWAY_ERROR': (ErrorType.GATEWAY,
                      'The payment provider returned an error. Nothing was charged.'),
    'UPI_DECLINED': (ErrorType.INSTRUMENT,
                     'The payment was declined in your UPI app.'),
    'UPI_FAILED': (ErrorType.INSTRUMENT,
                   'The UPI payment could not be completed.'),
    'TOKEN_EXPIRED': (ErrorType.INSTRUMENT,
                      'The saved card has expired. Please link it again.'),
    'BANK_DECLINED': (ErrorType.INSTRUMENT,
                      'Your bank declined the payment.'),
    'PAYMENT_FAILED': (ErrorType.UNKNOWN,
                       'The payment could not be completed.'),
}


#: Substring matches for provider text that carries no usable code. Checked in
#: order, so the specific entries come before the general ones.
_TEXT_HINTS = [
    ('insufficient', ErrorType.INSUFFICIENT,
     'There was not enough balance or available limit for this payment.'),
    ('exceed', ErrorType.LIMIT, 'This payment is above a limit on your account.'),
    ('expired', ErrorType.INSTRUMENT, 'The card has expired.'),
    ('invalid cvv', ErrorType.AUTHENTICATION, 'The security code was not correct.'),
    ('cvv', ErrorType.AUTHENTICATION, 'The security code was not correct.'),
    ('invalid card', ErrorType.INSTRUMENT, 'The card details were not valid.'),
    ('international', ErrorType.INSTRUMENT,
     'This card is not supported for payments here.'),
    ('declin', ErrorType.INSTRUMENT, 'Your bank declined the payment.'),
    ('authenticat', ErrorType.AUTHENTICATION,
     'The payment could not be authenticated with your bank.'),
    ('3ds', ErrorType.AUTHENTICATION,
     'The payment could not be authenticated with your bank.'),
    ('timeout', ErrorType.NETWORK, 'The payment gateway did not respond in time.'),
    ('timed out', ErrorType.NETWORK, 'The payment gateway did not respond in time.'),
    ('network', ErrorType.NETWORK, 'The connection to the payment gateway failed.'),
    ('cancel', ErrorType.CANCELLED, 'The payment was cancelled.'),
    ('duplicate', ErrorType.DUPLICATE, 'This payment has already been made.'),
    ('upi', ErrorType.INSTRUMENT, 'The UPI payment could not be completed.'),
]


def classify(code: str = None, reason: str = None) -> dict:
    """
    Resolve a failure to {code, type, message, retryable, actions}.

    Falls through three levels: an exact code, then a hint in the provider's
    text, then UNKNOWN. The last still produces a usable record - an unmapped
    provider code should not cost the user their explanation.
    """
    key = (code or '').strip().upper()

    if key in _CATALOG:
        error_type, message = _CATALOG[key]
    else:
        error_type, message = _from_text(reason or code or '')
        key = key or 'PAYMENT_FAILED'

    retryable, actions = _TYPE_ADVICE.get(
        error_type, _TYPE_ADVICE[ErrorType.UNKNOWN]
    )

    return {
        'code': key,
        'type': error_type,
        'message': message,
        'retryable': retryable,
        'actions': list(actions),
    }


def _from_text(text: str):
    lowered = (text or '').lower()
    for needle, error_type, message in _TEXT_HINTS:
        if needle in lowered:
            return error_type, message
    return ErrorType.UNKNOWN, 'The payment could not be completed.'


# -- Sanitisation -----------------------------------------------------------

#: Keys whose values are never written down, whatever the provider calls them.
_FORBIDDEN_KEYS = {
    'card_number', 'cardnumber', 'pan', 'number', 'cvv', 'cvc', 'cvv2',
    'csc', 'pin', 'otp', 'password', 'passwd', 'secret', 'key_secret',
    'api_key', 'authorization', 'auth', 'token', 'access_token',
    'refresh_token', 'signature', 'expiry', 'expiry_month', 'expiry_year',
    'exp_month', 'exp_year',
}

#: Thirteen to nineteen digits, optionally spaced or hyphened. Catches a PAN
#: that arrives inside a free-text message under an innocent key.
_PAN_RE = re.compile(r'\b(?:\d[ -]?){13,19}\b')

_MAX_PAYLOAD = 4000


def sanitize_gateway_payload(payload) -> str:
    """
    Reduce a provider response to something safe to store.

    Removes forbidden keys outright, redacts anything card-number shaped
    wherever it appears, and caps the size. Returns JSON text, or None when
    there is nothing worth keeping.

    Errs towards dropping: a diagnostic field lost is an inconvenience, a PAN
    written to a table is an incident.
    """
    if payload is None:
        return None

    cleaned = _scrub(payload)

    try:
        text = json.dumps(cleaned, default=str)
    except (TypeError, ValueError):
        text = str(cleaned)

    text = _PAN_RE.sub('[redacted]', text)

    if len(text) > _MAX_PAYLOAD:
        text = text[:_MAX_PAYLOAD] + '...[truncated]'

    return text


def _scrub(value):
    if isinstance(value, dict):
        return {
            k: ('[redacted]' if str(k).lower() in _FORBIDDEN_KEYS else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    if isinstance(value, str):
        return _PAN_RE.sub('[redacted]', value)
    return value
