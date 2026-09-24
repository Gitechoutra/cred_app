"""
portal/helpers/support_bot.py
=============================
The transaction-aware support assistant.

Deliberately scripted rather than generative. This bot talks to people about
money that has just gone missing, and every sentence it says has to be true of
*their* payment - so each reply is assembled from the recorded failure rather
than composed. A language model would occasionally invent a reason, and a
plausible wrong explanation for a failed payment is worse than no explanation.

It never asks for anything the system already knows. The transaction id, the
amount, the method and the reason are attached from the record; the user's
first message is a question, not a form.
"""

from portal.helpers import error_catalog, error_recorder
from portal.models.emi_payments import EMIPayments
from portal.models.qr_payments import QRPayments
from portal.models.transaction_errors import ErrorType


class Intent:
    """What the user can ask. The client sends these, not free text."""

    WHY_FAILED = 'WHY_FAILED'
    CAN_I_RETRY = 'CAN_I_RETRY'
    WAS_I_CHARGED = 'WAS_I_CHARGED'
    HOW_LONG = 'HOW_LONG'
    OTHER_METHOD = 'OTHER_METHOD'
    TALK_TO_HUMAN = 'TALK_TO_HUMAN'

    CHOICES = [
        WHY_FAILED, CAN_I_RETRY, WAS_I_CHARGED, HOW_LONG, OTHER_METHOD,
        TALK_TO_HUMAN,
    ]


#: The follow-up questions offered after the opening message, per error type.
#: "Was I charged?" leads for anything that timed out or could not be verified,
#: because that is the only question the user actually has at that moment.
_FOLLOW_UPS = {
    ErrorType.NETWORK: [Intent.WAS_I_CHARGED, Intent.CAN_I_RETRY, Intent.TALK_TO_HUMAN],
    ErrorType.VERIFICATION: [Intent.WAS_I_CHARGED, Intent.HOW_LONG, Intent.TALK_TO_HUMAN],
    ErrorType.GATEWAY: [Intent.WAS_I_CHARGED, Intent.CAN_I_RETRY, Intent.TALK_TO_HUMAN],
    ErrorType.INSTRUMENT: [Intent.OTHER_METHOD, Intent.CAN_I_RETRY, Intent.TALK_TO_HUMAN],
    ErrorType.INSUFFICIENT: [Intent.OTHER_METHOD, Intent.CAN_I_RETRY, Intent.TALK_TO_HUMAN],
    ErrorType.DUPLICATE: [Intent.WAS_I_CHARGED, Intent.TALK_TO_HUMAN],
    ErrorType.LIMIT: [Intent.HOW_LONG, Intent.OTHER_METHOD, Intent.TALK_TO_HUMAN],
}

_DEFAULT_FOLLOW_UPS = [Intent.WHY_FAILED, Intent.CAN_I_RETRY, Intent.TALK_TO_HUMAN]

_INTENT_LABELS = {
    Intent.WHY_FAILED: 'Why did my payment fail?',
    Intent.CAN_I_RETRY: 'Can I try again?',
    Intent.WAS_I_CHARGED: 'Was I charged?',
    Intent.HOW_LONG: 'How long will this take?',
    Intent.OTHER_METHOD: 'What else can I use?',
    Intent.TALK_TO_HUMAN: 'Talk to support',
}


def load_context(user, reference_type: str, reference_id: str) -> dict:
    """
    Everything the bot is allowed to know about one payment.

    Scoped to the signed-in user: a reference belonging to somebody else
    resolves to nothing rather than to a message about their payment.
    """
    record, amount, status, method, created = None, None, None, None, None

    if reference_type == 'QRPayments':
        record = QRPayments.query.filter_by(
            qr_payment_id=reference_id, user_id=user.user_id
        ).first()
        if record:
            amount = record.amount
            status = record.status
            method = 'UPI_QR'
            created = record.created_on

    elif reference_type == 'EMIPayments':
        record = EMIPayments.query.filter_by(
            payment_id=reference_id, user_id=user.user_id
        ).first()
        if record:
            amount = record.amount
            status = record.status
            method = record.payment_mode
            created = record.created_on

    if not record:
        return None

    error = error_recorder.latest_for(reference_type, reference_id)

    # A payment can fail without a recorded error - an older row, or a failure
    # on a path not yet wired. Fall back to what the payment itself says so the
    # bot still explains rather than shrugging.
    if error:
        verdict = error_catalog.classify(
            code=error.error_code, reason=error.error_reason
        )
        message = error.error_message
    else:
        verdict = error_catalog.classify(
            code=getattr(record, 'failure_code', None),
            reason=getattr(record, 'failure_reason', None),
        )
        message = verdict['message']

    return {
        'reference_type': reference_type,
        'reference_id': reference_id,
        'transaction_id': getattr(record, 'transaction_id', None) or reference_id,
        'amount': float(amount) if amount is not None else None,
        'status': status,
        'payment_method': method,
        'created_at': created.isoformat() if created else None,
        'error_code': verdict['code'],
        'error_type': verdict['type'],
        'error_message': message,
        'is_retryable': verdict['retryable'],
        'actions': verdict['actions'],
        'error_id': error.error_id if error else None,
    }


def opening(context: dict) -> dict:
    """The first thing the bot says, before the user asks anything."""
    if not context:
        return {
            'messages': [{
                'role': 'bot',
                'text': 'I could not find that payment. It may belong to a '
                        'different account.',
            }],
            'options': [],
        }

    amount = _rupees(context['amount'])
    text = (
        f'Your payment of {amount} could not be completed. '
        f'{context["error_message"]}'
        if amount else context['error_message']
    )

    return {
        'messages': [
            {'role': 'bot', 'text': text},
            {'role': 'bot', 'text': _charge_note(context)},
        ],
        'options': _options_for(context),
        'actions': context['actions'],
    }


def reply(context: dict, intent: str) -> dict:
    """Answer one follow-up, always about this specific payment."""
    if not context:
        return opening(context)

    amount = _rupees(context['amount'])
    error_type = context['error_type']

    if intent == Intent.WHY_FAILED:
        text = context['error_message']

    elif intent == Intent.WAS_I_CHARGED:
        text = _charge_note(context)

    elif intent == Intent.CAN_I_RETRY:
        if not context['is_retryable']:
            text = (
                'Not right away. This one will not succeed if you simply try '
                'again — something needs to change first, and the options '
                'below are the ones that will help.'
            )
        elif error_type in (ErrorType.NETWORK, ErrorType.VERIFICATION):
            text = (
                'Please check the status first. This payment may still be in '
                'progress, and trying again now could take the money twice.'
            )
        else:
            text = (
                f'Yes. Nothing was charged, so retrying {amount} is safe.'
                if amount else 'Yes. Nothing was charged, so retrying is safe.'
            )

    elif intent == Intent.HOW_LONG:
        if error_type == ErrorType.LIMIT:
            text = ('This limit resets within the hour. You can also try a '
                    'smaller amount now.')
        elif error_type in (ErrorType.NETWORK, ErrorType.VERIFICATION):
            text = ('We keep checking with the bank for up to 24 hours, and '
                    'this usually resolves within a few minutes. You do not '
                    'need to do anything.')
        else:
            text = 'You can try again straight away.'

    elif intent == Intent.OTHER_METHOD:
        text = _alternatives(context)

    elif intent == Intent.TALK_TO_HUMAN:
        text = (
            'I can pass this to our support team with the payment details '
            'already attached — you will not need to repeat any of it.'
        )

    else:
        text = context['error_message']

    return {
        'messages': [{'role': 'bot', 'text': text}],
        'options': _options_for(context, exclude=intent),
        'actions': context['actions'],
    }


def _charge_note(context: dict) -> str:
    """
    Whether money moved - the question behind almost every support contact.

    Stated plainly and never guessed: if the payment is in a state we cannot
    confirm, the bot says so rather than reassuring the user incorrectly.
    """
    error_type = context['error_type']
    status = (context.get('status') or '').upper()

    if error_type in (ErrorType.NETWORK, ErrorType.VERIFICATION):
        return (
            'We are still confirming whether the bank took the money. If it '
            'did and the payment did not complete, it is returned '
            'automatically — usually within a few minutes.'
        )

    if error_type == ErrorType.DUPLICATE:
        return 'You have not been charged twice. The earlier payment stands.'

    if status in ('FAILED', 'RISK_FAILED', 'CANCELLED'):
        return 'Nothing was charged. The amount is still with your bank.'

    return 'No money has left your account for this attempt.'


def _alternatives(context: dict) -> str:
    method = (context.get('payment_method') or '').upper()

    if 'UPI' in method:
        return ('You could pay by card instead, or try a different UPI app. '
                'A different bank account often works when one is having '
                'trouble.')
    if context['error_type'] == ErrorType.INSUFFICIENT:
        return ('A card with more available limit would work, or a smaller '
                'amount on this one.')
    return ('You could use a different card, or pay by UPI. UPI often '
            'succeeds when a card is being declined.')


def _options_for(context: dict, exclude: str = None) -> list:
    intents = _FOLLOW_UPS.get(context['error_type'], _DEFAULT_FOLLOW_UPS)
    return [
        {'intent': i, 'label': _INTENT_LABELS[i]}
        for i in intents if i != exclude
    ]


def _rupees(amount) -> str:
    if amount is None:
        return ''
    return f'Rs. {amount:,.2f}'
