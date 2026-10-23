"""
Manual cards, card themes, refresh, bank linking and card bills.

Manual cards are cards the holder tracks by typing their own figures. They are
labelled "User-entered - Not Bank Verified" in every response, can be edited
and removed by the holder, and live in their own table so nothing that moves
money can read a typed-in figure as a limit CashU granted (see
models/manual_cards.py).

The form never takes a card number, CVV, expiry, PIN, OTP or bank password.
A request that carries one is refused outright rather than having the field
quietly dropped, so a client that starts sending one fails loudly in testing.

Bank linking and card bill payment need licensed providers (an Account
Aggregator or card-data partner, and a BBPS biller operator). Neither is
contracted, so those endpoints report themselves unavailable instead of
pretending: nothing here simulates a bank sign-in or marks data verified.
"""

import re
from decimal import Decimal

from flask import current_app, request
from flask_jwt_extended import jwt_required
from flask_restx import Resource

from portal import db
from portal.helpers import audit
from portal.helpers.helpers import ErrorCode, failure, iso, success, to_float
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.validators import (
    ValidationError, sanitize_text, validate_amount, validate_date,
    validate_day_of_month,
)
from portal.models.base import utcnow
from portal.models.cards import Cards, CardStatus
from portal.models.manual_cards import (
    CardTheme, ManualCardNetwork, ManualCardStatus, ManualCards,
)

from . import ns

MAX_MANUAL_CARDS = 20
MAX_AMOUNT = Decimal('9999999999.99')

USER_ENTERED = 'User-entered - Not Bank Verified'
CASHU_LIMIT = 'Tokenised - limit set by CashU'

#: Keys that must never reach this API. Their presence is refused.
_FORBIDDEN_KEYS = {'card_number', 'cardnumber', 'pan', 'full_number', 'number',
                   'cvv', 'cvc', 'cvv2', 'pin', 'otp', 'password', 'net_banking_password',
                   'expiry', 'expiry_month', 'expiry_year'}
_LONG_DIGITS = re.compile(r'\d{9,}')

_FIGURES = ('credit_limit', 'outstanding_balance', 'available_credit',
            'statement_day', 'payment_due_date', 'minimum_due', 'total_due')


# -- Validation ------------------------------------------------------------

def _money(value, field):
    if value is None or str(value).strip() == '':
        return None
    raw = str(value).strip()
    if re.fullmatch(r'0+(\.0{1,2})?', raw):
        return Decimal('0.00')
    return validate_amount(raw, field, maximum=MAX_AMOUNT)


def _clean(body: dict, existing: ManualCards = None) -> dict:
    """
    Validate a create (existing=None) or a partial update. Returns the fields
    to set. Raises ValidationError naming the field.
    """
    bad = sorted(k for k in body if k.lower() in _FORBIDDEN_KEYS)
    if bad:
        raise ValidationError(
            'Never send a card number, CVV, expiry, PIN, OTP or password. Manual '
            'cards need only the bank, the last four digits and your own figures.',
            bad[0])
    for key, value in body.items():
        if isinstance(value, str) and _LONG_DIGITS.search(value.replace(' ', '')) \
                and key not in _FIGURES:
            raise ValidationError('This looks like a card or account number. Enter '
                                  'only the last four digits.', key)

    creating = existing is None
    out = {}

    if creating or 'issuer_bank' in body:
        bank = sanitize_text(body.get('issuer_bank') or '', 150)
        if len(bank) < 2:
            raise ValidationError('Choose or enter the issuing bank.', 'issuer_bank')
        out['issuer_bank'] = bank
    if 'issuer_id' in body:
        slug = (body.get('issuer_id') or '').strip().lower()
        out['issuer_id'] = slug if re.fullmatch(r'[a-z0-9-]{2,40}', slug) else None
    if creating or 'last4' in body:
        last4 = str(body.get('last4') or '').strip()
        if not re.fullmatch(r'\d{4}', last4):
            raise ValidationError('Enter the last four digits of the card.', 'last4')
        out['last4'] = last4
    if 'nickname' in body:
        out['nickname'] = sanitize_text(body.get('nickname') or '', 100) or None
    if creating or 'network' in body:
        network = (body.get('network') or ManualCardNetwork.OTHER).upper()
        if network not in ManualCardNetwork.CHOICES:
            raise ValidationError('Choose the card network.', 'network')
        out['network'] = network
    if 'theme' in body:
        theme = (body.get('theme') or CardTheme.AUTO).upper()
        if theme not in CardTheme.CHOICES:
            raise ValidationError('Unknown card theme.', 'theme')
        out['theme'] = theme

    for field in ('credit_limit', 'outstanding_balance', 'available_credit',
                  'minimum_due', 'total_due'):
        if field in body:
            out[field] = _money(body.get(field), field)
    if 'statement_day' in body:
        value = body.get('statement_day')
        out['statement_day'] = (validate_day_of_month(value, 'statement_day')
                                if value not in (None, '') else None)
    if 'payment_due_date' in body:
        out['payment_due_date'] = validate_date(body.get('payment_due_date') or None,
                                                'payment_due_date')

    def final(field):
        return out[field] if field in out else (getattr(existing, field) if existing else None)

    limit, available = final('credit_limit'), final('available_credit')
    minimum, total = final('minimum_due'), final('total_due')
    if limit is not None and limit == 0:
        raise ValidationError('A credit limit must be more than zero.', 'credit_limit')
    if limit is not None and available is not None and available > limit:
        raise ValidationError('Available credit cannot be more than the credit limit.',
                              'available_credit')
    if minimum is not None and total is not None and minimum > total:
        raise ValidationError('The minimum due cannot be more than the total due.',
                              'minimum_due')
    return out


# -- Shapes ------------------------------------------------------------------

def _derived_available(card):
    if card.available_credit is not None:
        return card.available_credit, False
    if card.credit_limit is not None and card.outstanding_balance is not None:
        return max(Decimal('0.00'), card.credit_limit - card.outstanding_balance), True
    return None, False


def manual_card_dict(card: ManualCards) -> dict:
    available, derived = _derived_available(card)
    limit = card.credit_limit
    used = card.outstanding_balance
    utilisation = (round(float(used) / float(limit) * 100, 1)
                   if limit and used is not None else None)
    return {
        'kind': 'MANUAL',
        'manual_card_id': card.manual_card_id,
        'issuer_bank': card.issuer_bank,
        'issuer_id': card.issuer_id,
        'nickname': card.nickname,
        'network': card.network,
        'last4': card.last4,
        'masked_pan': f'**** **** **** {card.last4}',
        'credit_limit': to_float(limit),
        'outstanding_balance': to_float(used),
        'available_credit': to_float(available),
        'available_is_derived': derived,
        'utilization_percentage': utilisation,
        'statement_day': card.statement_day,
        'payment_due_date': iso(card.payment_due_date),
        'minimum_due': to_float(card.minimum_due),
        'total_due': to_float(card.total_due),
        'theme': card.theme,
        'status': card.status,
        'data_source': 'USER_ENTERED',
        'data_source_label': USER_ENTERED,
        'bank_verified': False,
        'last_updated': iso(card.figures_updated_at or card.created_on),
        'created_on': iso(card.created_on),
    }


def _own_manual(manual_card_id, user):
    return ManualCards.query.filter_by(
        manual_card_id=manual_card_id, user_id=user.user_id,
        status=ManualCardStatus.ACTIVE).first()


def _validation_failure(exc):
    return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                   details={'field': exc.field})


# -- Manual cards --------------------------------------------------------------

@ns.route('/manual')
class ManualCardList(Resource):
    @ns.doc('list_manual_cards', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        user = current_user()
        cards = ManualCards.query.filter_by(user_id=user.user_id,
                                            status=ManualCardStatus.ACTIVE).order_by(
            ManualCards.created_on.asc()).all()
        return success([manual_card_dict(c) for c in cards])

    @ns.doc('add_manual_card', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """Add a card by hand. Every figure is optional and labelled user-entered."""
        user = current_user()
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return failure(ErrorCode.VALIDATION_ERROR, 'Send the card as a JSON object.', 400)
        try:
            fields = _clean(body)
        except ValidationError as exc:
            return _validation_failure(exc)

        active = ManualCards.query.filter_by(user_id=user.user_id,
                                             status=ManualCardStatus.ACTIVE)
        if active.count() >= MAX_MANUAL_CARDS:
            return failure(ErrorCode.LIMIT_EXCEEDED,
                           f'You can track up to {MAX_MANUAL_CARDS} cards. Remove one first.',
                           422)
        same = active.filter(
            db.func.lower(ManualCards.issuer_bank) == fields['issuer_bank'].lower(),
            ManualCards.last4 == fields['last4']).first()
        tokenised = Cards.query.filter(
            Cards.user_id == user.user_id, Cards.status != CardStatus.DELETED,
            db.func.lower(Cards.card_issuer_bank) == fields['issuer_bank'].lower(),
            Cards.last4 == fields['last4']).first()
        if same or tokenised:
            return failure(ErrorCode.CONFLICT,
                           f'A {fields["issuer_bank"]} card ending {fields["last4"]} is '
                           'already in your cards.', 409,
                           details={'manual_card_id': same.manual_card_id if same else None,
                                    'card_id': tokenised.card_id if tokenised else None})

        card = ManualCards(user_id=user.user_id, status=ManualCardStatus.ACTIVE,
                           theme=CardTheme.AUTO, **fields)
        if any(fields.get(f) is not None for f in _FIGURES):
            card.figures_updated_at = utcnow()
        db.session.add(card)
        db.session.commit()
        audit.record(action='MANUAL_CARD_ADDED', entity_type='ManualCards',
                     entity_id=card.manual_card_id, actor_user_id=str(user.user_id),
                     after={'issuer_bank': card.issuer_bank, 'last4': card.last4})
        return success(manual_card_dict(card),
                       'Card added. Its figures are marked as entered by you.', 201)


@ns.route('/manual/<string:manual_card_id>')
class ManualCardDetail(Resource):
    @ns.doc('get_manual_card', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, manual_card_id):
        card = _own_manual(manual_card_id, current_user())
        if not card:
            return failure(ErrorCode.NOT_FOUND, 'Card not found.', 404)
        return success(manual_card_dict(card))

    @ns.doc('update_manual_card', security='Bearer')
    @jwt_required()
    @active_user_required
    def patch(self, manual_card_id):
        """Update any field. Clearing a figure sends null or an empty string."""
        user = current_user()
        card = _own_manual(manual_card_id, user)
        if not card:
            return failure(ErrorCode.NOT_FOUND, 'Card not found.', 404)
        body = request.get_json(silent=True) or {}
        try:
            fields = _clean(body, existing=card)
        except ValidationError as exc:
            return _validation_failure(exc)

        if 'issuer_bank' in fields or 'last4' in fields:
            bank = fields.get('issuer_bank', card.issuer_bank)
            last4 = fields.get('last4', card.last4)
            clash = ManualCards.query.filter(
                ManualCards.user_id == user.user_id,
                ManualCards.status == ManualCardStatus.ACTIVE,
                ManualCards.manual_card_id != card.manual_card_id,
                db.func.lower(ManualCards.issuer_bank) == bank.lower(),
                ManualCards.last4 == last4).first()
            if clash:
                return failure(ErrorCode.CONFLICT,
                               f'You already have a {bank} card ending {last4}.', 409)

        before = manual_card_dict(card)
        for key, value in fields.items():
            setattr(card, key, value)
        if any(f in fields for f in _FIGURES):
            card.figures_updated_at = utcnow()
        db.session.commit()
        audit.record(action='MANUAL_CARD_UPDATED', entity_type='ManualCards',
                     entity_id=card.manual_card_id, actor_user_id=str(user.user_id),
                     before={k: before.get(k) for k in fields},
                     after={k: manual_card_dict(card).get(k) for k in fields})
        return success(manual_card_dict(card), 'Card updated.')

    @ns.doc('remove_manual_card', security='Bearer')
    @jwt_required()
    @active_user_required
    def delete(self, manual_card_id):
        """Remove a manual card. Kept for the audit trail, hidden everywhere else."""
        user = current_user()
        card = _own_manual(manual_card_id, user)
        if not card:
            return failure(ErrorCode.NOT_FOUND, 'Card not found.', 404)
        card.status = ManualCardStatus.REMOVED
        card.removed_at = utcnow()
        db.session.commit()
        audit.record(action='MANUAL_CARD_REMOVED', entity_type='ManualCards',
                     entity_id=card.manual_card_id, actor_user_id=str(user.user_id))
        return success({'manual_card_id': card.manual_card_id, 'removed': True},
                       'Card removed.')


@ns.route('/manual/<string:manual_card_id>/refresh')
class ManualCardRefresh(Resource):
    @ns.doc('refresh_manual_card', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, manual_card_id):
        """
        There is no bank feed behind a manual card, so a refresh re-reads what
        is stored and says so. It never invents newer figures.
        """
        card = _own_manual(manual_card_id, current_user())
        if not card:
            return failure(ErrorCode.NOT_FOUND, 'Card not found.', 404)
        return success({**manual_card_dict(card), 'refreshed_from': 'STORED',
                        'refresh_note': 'These figures were entered by you and are not '
                                        'linked to your bank. Edit the card to update them.'},
                       'No bank connection for this card - showing your saved figures.')


# -- Tokenised cards: theme and refresh ----------------------------------------

@ns.route('/<string:card_id>/theme')
class CardThemeSetting(Resource):
    @ns.doc('set_card_theme', security='Bearer')
    @jwt_required()
    @active_user_required
    def put(self, card_id):
        """
        Choose how a linked card is drawn. The one thing about a linked card
        its holder may change: it touches no figure and no status.
        """
        user = current_user()
        card = Cards.query.filter_by(card_id=card_id, user_id=user.user_id).first()
        if not card or card.status == CardStatus.DELETED:
            return failure(ErrorCode.NOT_FOUND, 'Card not found.', 404)
        theme = ((request.get_json(silent=True) or {}).get('theme') or '').upper()
        if theme not in CardTheme.CHOICES:
            return failure(ErrorCode.VALIDATION_ERROR, 'Unknown card theme.', 400,
                           details={'field': 'theme'})
        card.card_theme = theme
        db.session.commit()
        from .routes import card_dict
        return success(card_dict(card, detailed=True), 'Card theme updated.')


@ns.route('/<string:card_id>/refresh')
class CardRefresh(Resource):
    @ns.doc('refresh_card', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, card_id):
        """Re-read a linked card from CashU's records - its limit is CashU's own."""
        user = current_user()
        card = Cards.query.filter_by(card_id=card_id, user_id=user.user_id).first()
        if not card or card.status == CardStatus.DELETED:
            return failure(ErrorCode.NOT_FOUND, 'Card not found.', 404)
        from .routes import card_dict
        return success({**card_dict(card, detailed=True), 'refreshed_from': 'CASHU',
                        'refreshed_at': iso(utcnow())},
                       'Card is up to date with CashU\'s records.')


# -- Bank linking (Option B) -----------------------------------------------------

def _link_provider() -> dict:
    """
    The card-linking provider, if one is configured. None is: CashU has no
    Account Aggregator or card-data partner under contract, and linking is not
    something to simulate - a fake bank sign-in would teach users to type bank
    credentials into the wrong place.
    """
    name = (current_app.config.get('CARD_LINK_PROVIDER') or '').upper()
    supported = {}      # provider name -> client, added when one is contracted
    if not name:
        return {'available': False, 'provider': None,
                'reason': 'Secure bank linking is not available yet. You can add '
                          'your card manually in the meantime.'}
    if name not in supported:
        return {'available': False, 'provider': name,
                'reason': f'The configured linking provider ({name}) is not '
                          'supported by this version of CashU.'}
    return {'available': True, 'provider': name, 'reason': None}


@ns.route('/link/providers')
class LinkProviders(Resource):
    @ns.doc('card_link_providers', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Which institutions can be linked, from the provider's own list."""
        provider = _link_provider()
        return success({**provider, 'institutions': []})


@ns.route('/link/sessions')
class LinkSessions(Resource):
    @ns.doc('card_link_session', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """Start a consented linking session with the provider."""
        body = request.get_json(silent=True) or {}
        if body.get('consent') is not True:
            return failure(ErrorCode.VALIDATION_ERROR,
                           'Please give consent to share your card data first.', 400,
                           details={'field': 'consent'})
        provider = _link_provider()
        if not provider['available']:
            return failure('PROVIDER_NOT_CONFIGURED', provider['reason'], 503,
                           details={'provider': provider['provider']})
        return failure('PROVIDER_NOT_CONFIGURED', 'Linking is not available.', 503)


# -- Card bills ------------------------------------------------------------------

def _bill_payment_route() -> dict:
    """
    Paying a bank's credit card bill needs a BBPS biller operator unit or the
    issuer's own collection API. Neither is contracted, so card bills show what
    is due and say plainly that payment is not available here yet.
    """
    if (current_app.config.get('CARD_BILL_PAY_PROVIDER') or '').strip():
        return {'available': False,
                'reason': 'The configured card bill provider is not supported by this '
                          'version of CashU.'}
    return {'available': False,
            'reason': 'Paying bank card bills from CashU is not available yet. Pay '
                      'through your bank\'s app or net banking.'}


@ns.route('/bills')
class CardBills(Resource):
    @ns.doc('card_bills', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """
        What is due on each card, and whether it can be paid here.

        The CashU credit line is payable (gateway-verified, see /credit/pay).
        Bank cards show their bill but are not payable until a card bill
        provider is connected.
        """
        from portal.models.credit_accounts import CreditAccounts, CreditAccountStatus
        from portal.models.credit_statements import CreditStatements, StatementStatus

        user = current_user()
        bank_route = _bill_payment_route()
        bills = []

        account = CreditAccounts.query.filter(
            CreditAccounts.user_id == user.user_id,
            CreditAccounts.status.in_([CreditAccountStatus.ACTIVE,
                                       CreditAccountStatus.BLOCKED])).first()
        if account:
            statement = CreditStatements.query.filter(
                CreditStatements.credit_account_id == account.credit_account_id,
                CreditStatements.status.in_([StatementStatus.UNPAID,
                                             StatementStatus.PARTIALLY_PAID,
                                             StatementStatus.OVERDUE]),
            ).order_by(CreditStatements.due_date.asc()).first()
            bills.append({
                'kind': 'CREDIT_LINE', 'id': account.credit_account_id,
                'issuer_bank': 'CashU credit line', 'last4': None,
                'data_source': 'CASHU', 'data_source_label': 'CashU statement',
                'outstanding': to_float(account.current_outstanding),
                'total_due': to_float(statement.closing_balance - (statement.amount_paid or 0))
                if statement else None,
                'minimum_due': to_float(statement.minimum_due) if statement else None,
                'due_date': iso(statement.due_date) if statement else None,
                'statement_status': statement.status if statement else None,
                'pay': {'available': True, 'route': '/credit/pay'},
            })

        for card in Cards.query.filter(Cards.user_id == user.user_id,
                                       Cards.status != CardStatus.DELETED).all():
            bills.append({
                'kind': 'TOKENISED', 'id': card.card_id,
                'issuer_bank': card.card_issuer_bank, 'last4': card.last4,
                'data_source': 'CASHU', 'data_source_label': CASHU_LIMIT,
                'outstanding': to_float(card.outstanding_amount),
                'total_due': to_float(card.current_due_amount),
                'minimum_due': to_float(card.minimum_due_amount),
                'due_date': iso(card.next_due_date),
                'statement_status': None, 'pay': bank_route,
            })

        for card in ManualCards.query.filter_by(user_id=user.user_id,
                                                status=ManualCardStatus.ACTIVE).all():
            bills.append({
                'kind': 'MANUAL', 'id': card.manual_card_id,
                'issuer_bank': card.issuer_bank, 'last4': card.last4,
                'data_source': 'USER_ENTERED', 'data_source_label': USER_ENTERED,
                'outstanding': to_float(card.outstanding_balance),
                'total_due': to_float(card.total_due),
                'minimum_due': to_float(card.minimum_due),
                'due_date': iso(card.payment_due_date),
                'statement_status': None, 'pay': bank_route,
            })

        return success({'bills': bills, 'bank_card_payment': bank_route})
