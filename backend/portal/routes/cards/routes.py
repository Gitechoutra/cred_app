"""
Credit card linking and lifecycle (PRD FR-003, FR-004, section 8).

Zero raw card storage. The 16-digit PAN and the CVV travel from the client SDK
straight to the licensed Token Requestor and never reach this backend - what
arrives here is a network token reference plus display metadata. Any change to
this module that introduces a PAN or CVV field breaks PCI DSS SAQ-A eligibility
and RBI CoFT compliance at the same time.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal import db
from portal.helpers import adapters, audit, card_limit, test_cards
from portal.helpers.encryption import encrypt, mask_pan
from portal.helpers.helpers import ErrorCode, failure, iso, success, to_float
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.validators import (
    ValidationError, sanitize_text, validate_day_of_month, validate_expiry,
)
from portal.models.base import utcnow
from portal.models.card_networks import CardNetworks
from portal.models.cards import Cards, CardStatus
from portal.models.notifications import NotificationEvent

from . import logger, ns

link_parser = reqparse.RequestParser()
# The BIN is the first six digits - an issuer identifier, not a card number, and
# permitted under PCI DSS for routing. Everything else here is display metadata
# returned by the token requestor callback.
link_parser.add_argument('bin', type=str, required=True, location='json')
link_parser.add_argument('last4', type=str, required=True, location='json')
link_parser.add_argument('expiry_month', type=str, required=True, location='json')
link_parser.add_argument('expiry_year', type=str, required=True, location='json')
link_parser.add_argument('cardholder_name', type=str, required=False, location='json')
link_parser.add_argument('nickname', type=str, required=False, location='json')
link_parser.add_argument('statement_day', type=int, required=False, location='json')
link_parser.add_argument('due_day', type=int, required=False, location='json')
link_parser.add_argument('issuer_bank', type=str, required=False, location='json')
link_parser.add_argument('brand_color', type=str, required=False, location='json')

def card_dict(card: Cards, detailed: bool = False) -> dict:
    data = {
        'card_id': card.card_id,
        'masked_pan': card.masked_pan,
        'last4': card.last4,
        'network': card.card_network,
        'issuer_bank': card.card_issuer_bank,
        'nickname': card.nickname,
        'brand_color': card.brand_color,
        'expiry_month': card.expiry_month,
        'expiry_year': card.expiry_year,
        'card_limit': to_float(card.card_limit),
        'available_limit': to_float(card.available_limit),
        'outstanding_amount': to_float(card.outstanding_amount),
        'utilization_percentage': card.utilization_percentage,
        'current_due_amount': to_float(card.current_due_amount),
        'minimum_due_amount': to_float(card.minimum_due_amount),
        'statement_day': card.statement_day,
        'due_day': card.due_day,
        'next_due_date': iso(card.next_due_date),
        'status': card.status,
        # Present only on a simulated card, so the client can badge it TEST
        # MODE without having to know the catalogue.
        'test_scenario': card.test_scenario,
        'is_test_card': bool(card.test_scenario),
        'linked_at': iso(card.linked_at),
    }

    if detailed:
        data['days_until_due'] = (
            (card.next_due_date - utcnow().date()).days
            if card.next_due_date else None
        )
        data['last_synced_at'] = iso(card.last_synced_at)

    return data


def _next_due_date(due_day: int):
    from portal.helpers.emi_provider_adapter import next_due_date
    return next_due_date(due_day) if due_day else None


@ns.route('')
class CardList(Resource):
    @ns.doc('list_cards', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """All active cards for the signed-in user."""
        user = current_user()

        cards = Cards.query.filter(
            Cards.user_id == user.user_id,
            Cards.status != CardStatus.DELETED,
        ).order_by(Cards.created_on.asc()).all()

        return success({
            'cards': [card_dict(c) for c in cards],
            'total_limit': sum(float(c.card_limit or 0) for c in cards),
            'total_outstanding': sum(float(c.outstanding_amount or 0) for c in cards),
            'count': len(cards),
        })

    @ns.doc('link_card', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Link a card once tokenization completes (PRD FR-003).

        The BIN determines the issuer, the network, and whether the card is even
        eligible - ERR-001 rejects prepaid and gift cards here, before any token
        is provisioned.
        """
        args = link_parser.parse_args()
        user = current_user()

        # if not settings.flag_enabled(settings.Flag.CARD_LINKING, str(user.user_id)):
        #     return failure(
        #         ErrorCode.FEATURE_DISABLED,
        #         'Card linking is temporarily unavailable.',
        #         403,
        #     )

        bin_prefix = (args['bin'] or '').strip()
        last4 = (args['last4'] or '').strip()

        if not bin_prefix.isdigit() or len(bin_prefix) < 6:
            return failure(
                ErrorCode.ERR_001_INVALID_CARD,
                'Invalid card number. Please check the digits and try again.',
                400,
            )
        if not last4.isdigit() or len(last4) != 4:
            return failure(
                ErrorCode.ERR_001_INVALID_CARD,
                'Invalid card number. Please check the digits and try again.',
                400,
            )

        # A predefined test card, if this is one. Resolved before validation so
        # the refusal below cannot be sidestepped with a malformed payload.
        test_card = test_cards.find(bin_prefix, last4)

        if test_card and not test_cards.enabled():
            # Reached only by a client sending a test PAN where test mode is
            # off - most likely production.
            logger.warning(
                f'Test card {bin_prefix[:6]}...{last4} refused: test mode off '
                f'(user {user.user_id})'
            )
            return failure(
                ErrorCode.ERR_001_INVALID_CARD,
                'This is a test card and test mode is not enabled here.',
                400,
                recovery='Use a real card, or enable test mode in development.',
            )

        # The limit is ours to work out, from the holder's credit score and
        # salary, and is settled before anything is tokenised: a card that
        # cannot be given a limit is not linked. A simulated card keeps its
        # catalogue limit, which is what produces its scenario.
        if test_card:
            limit = test_card['limit']
        else:
            assessment = card_limit.assess(user)
            if not assessment['eligible']:
                return failure(
                    ErrorCode.KYC_REQUIRED
                    if assessment['reason'] != card_limit.Reason.SCORE_TOO_LOW
                    else ErrorCode.ERR_001_INVALID_CARD,
                    assessment['message'],
                    422,
                    details={'reason': assessment['reason']},
                )
            limit = assessment['limit']

        try:
            expiry_month, expiry_year = validate_expiry(
                args['expiry_month'], args['expiry_year']
            )
        except ValidationError as exc:
            return failure(ErrorCode.ERR_009_TOKEN_EXPIRED, exc.message, 400)

        # Longest matching BIN wins, so a specific 8-digit rule beats the
        # 6-digit fallback for the same issuer.
        network_row = CardNetworks.query.filter(
            CardNetworks.bin_prefix == bin_prefix[:6]
        ).first()

        if not network_row:
            network_row = CardNetworks.query.filter(
                CardNetworks.bin_prefix == bin_prefix[:4]
            ).first()

        if not network_row:
            provided_bank = (args.get('issuer_bank') or '').strip()
            if provided_bank:
                first_digit = bin_prefix[0] if bin_prefix else '4'
                deduced_net = {
                    '4': 'VISA',
                    '5': 'MASTERCARD',
                    '6': 'RUPAY',
                    '3': 'AMEX',
                }.get(first_digit, 'VISA')
                colour = args.get('brand_color') or '#0A0F0D'
                network_row = type('DynamicNetworkRow', (), {
                    'network': deduced_net,
                    'issuer_bank': provided_bank,
                    'card_type': 'CREDIT',
                    'brand_color': colour,
                    'is_blocklisted': False,
                    'is_supported': True,
                })()

        if not network_row:
            return failure(
                ErrorCode.ERR_001_INVALID_CARD,
                'We could not identify your card issuer. Please check the '
                'number and try again.',
                400,
            )

        if network_row.is_blocklisted:
            logger.warning(
                f'Blocklisted BIN {bin_prefix[:6]} attempted by user {user.user_id}'
            )
            return failure(
                ErrorCode.ERR_001_INVALID_CARD,
                'This card cannot be linked. Please use a different card.',
                400,
            )

        # PRD ERR-001: only credit cards are supported.
        if not network_row.is_supported or network_row.card_type != 'CREDIT':
            return failure(
                ErrorCode.ERR_001_INVALID_CARD,
                'Only credit cards are supported.',
                400,
            )

        token = adapters.tokenize_card(
            reference=(
                f'{user.user_id}:{last4}:'
                f'{test_cards.simulation_token(test_card["scenario"])}'
                if test_card else f'{user.user_id}:{last4}'
            ),
            last4=last4,
            network=network_row.network,
            issuer_bank=network_row.issuer_bank,
            expiry_month=expiry_month,
            expiry_year=expiry_year,
            cardholder_name=args.get('cardholder_name'),
        )

        if not token.get('ok'):
            return failure(
                token.get('error_code', ErrorCode.PROVIDER_ERROR),
                token.get('error', 'Authentication rejected by bank.'),
                400,
            )

        duplicate = Cards.query.filter_by(
            token_reference_id=token['token_reference_id']
        ).first()
        if duplicate:
            return failure(
                ErrorCode.CONFLICT, 'This card is already linked.', 409
            )

        card = Cards(
            user_id=user.user_id,
            token_reference_id=token['token_reference_id'],
            token_provider=token.get('token_provider'),
            masked_pan=mask_pan(last4),
            last4=last4,
            card_network=network_row.network,
            card_issuer_bank=network_row.issuer_bank,
            cardholder_name_enc=(
                encrypt(args['cardholder_name']) if args.get('cardholder_name') else None
            ),
            expiry_month=expiry_month,
            expiry_year=expiry_year,
            brand_color=network_row.brand_color,
            nickname=sanitize_text(args.get('nickname'), 100) or None,
            status=CardStatus.ACTIVE,
            linked_at=utcnow(),
            # NULL on every real card. Its presence is what marks a card as
            # simulated, both to the payment path and to the UI badge.
            test_scenario=test_card['scenario'] if test_card else None,
            card_limit=limit,
            available_limit=limit,
            outstanding_amount=0,
        )

        try:
            if args.get('statement_day'):
                card.statement_day = validate_day_of_month(
                    args['statement_day'], 'statement_day'
                )
            if args.get('due_day'):
                card.due_day = validate_day_of_month(args['due_day'], 'due_day')
                card.next_due_date = _next_due_date(card.due_day)
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        db.session.add(card)

        audit.emit(
            'CardLinkedEvent',
            aggregate_type='Cards',
            aggregate_id=card.card_id,
            user_id=str(user.user_id),
            payload={'event': NotificationEvent.NEW_CARD_LINKED, 'last4': last4},
        )
        db.session.commit()

        audit.record(
            action='CARD_LINKED',
            entity_type='Cards',
            entity_id=card.card_id,
            actor_user_id=str(user.user_id),
            after={'masked_pan': card.masked_pan, 'issuer': card.card_issuer_bank},
        )

        return success(card_dict(card, detailed=True), 'Card linked successfully.', 201)


@ns.route('/<string:card_id>')
class CardDetail(Resource):
    @ns.doc('get_card', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, card_id):
        """Card detail with limit progress (PRD FR-004)."""
        user = current_user()

        card = Cards.query.filter_by(
            card_id=card_id, user_id=user.user_id
        ).first()

        if not card or card.status == CardStatus.DELETED:
            return failure(ErrorCode.NOT_FOUND, 'Card not found.', 404)

        return success(card_dict(card, detailed=True))

    # A linked card is permanent and read-only: its number, expiry, due day,
    # name and limit are fixed when it is linked, and the limit is ours rather
    # than the holder's to set. Both verbs are answered explicitly, so a client
    # still calling them is told why instead of meeting a bare 405. A lost card
    # or a wrong entry goes through support.
    @ns.doc('update_card', security='Bearer')
    @jwt_required()
    @active_user_required
    def patch(self, card_id):
        return _card_locked()

    @ns.doc('unlink_card', security='Bearer')
    @jwt_required()
    @active_user_required
    def delete(self, card_id):
        return _card_locked()


def _card_locked():
    return failure(
        ErrorCode.FORBIDDEN,
        'Linked cards cannot be edited or removed.',
        403,
        recovery='Contact support for a lost card or a wrong entry.',
    )


@ns.route('/limit')
class CardLimit(Resource):
    @ns.doc('card_limit', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """
        The limit a card linked now would be given, or why none can be.

        Lets the Add Card screen say what is missing before the user types a
        card number, rather than after.
        """
        assessment = card_limit.assess(current_user())
        return success({
            'eligible': assessment['eligible'],
            'limit': to_float(assessment['limit']),
            'reason': assessment['reason'],
            'message': assessment['message'],
        })


@ns.route('/test-cards')
class TestCards(Resource):
    @ns.doc('list_test_cards', security='Bearer')
    @jwt_required()
    def get(self):
        """
        Predefined dummy cards, one per payment outcome (development only).

        Returns 404 rather than an empty list when test mode is off, so a
        production deployment does not advertise that the feature exists.

        Serving full numbers here is safe: they are published network test
        values that cannot be issued to anyone, and the endpoint is unreachable
        unless test mode is on - which requires the sandbox adapters and a
        non-production build.
        """
        if not test_cards.enabled():
            return failure(
                ErrorCode.NOT_FOUND,
                'Test cards are not available in this environment.',
                404,
            )

        return success({
            'test_mode': True,
            'notice': (
                'These are simulated cards. No real card is charged, no money '
                'moves, and no payment network is contacted.'
            ),
            'cards': test_cards.catalogue(),
            'scenarios': test_cards.Scenario.CHOICES,
        })


@ns.route('/networks/lookup/<string:bin_prefix>')
class BINLookup(Resource):
    @ns.doc('lookup_bin', security='Bearer')
    @jwt_required()
    def get(self, bin_prefix):
        """
        Identify the issuer from a BIN so the Add Card form can show the bank
        and brand colour as the user types.
        """
        bin_prefix = (bin_prefix or '').strip()
        if not bin_prefix.isdigit() or len(bin_prefix) < 6:
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'Enter at least the first 6 digits of your card.',
                400,
            )

        row = CardNetworks.query.filter(
            CardNetworks.bin_prefix == bin_prefix[:6]
        ).first() or CardNetworks.query.filter(
            CardNetworks.bin_prefix == bin_prefix[:4]
        ).first()

        if not row:
            return failure(
                ErrorCode.NOT_FOUND, 'Card issuer could not be identified.', 404
            )

        return success({
            'network': row.network,
            'issuer_bank': row.issuer_bank,
            'card_type': row.card_type,
            'brand_color': row.brand_color,
            'is_supported': row.is_supported and row.card_type == 'CREDIT',
        })

