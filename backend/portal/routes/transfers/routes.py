"""
Credit facility to bank transfers (PRD FR-006, section 9).

The highest-risk feature on the platform. Every endpoint here funnels through
transfer_engine, which owns the state machine, and every money-moving call
requires an X-Idempotency-Key so a double-tapped Confirm cannot charge twice.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal.helpers import fee_calculator, settings, transfer_engine
from portal.helpers.helpers import (
    ErrorCode, client_ip, device_uuid, failure, idempotency_key, iso,
    paginated, success, to_float,
)
from portal.helpers.jwt import active_user_required, current_user, kyc_required
from portal.helpers.settings import Key
from portal.helpers.validators import (
    ValidationError, validate_amount, validate_idempotency_key,
    validate_pagination,
)
from portal.models.bank_accounts import BankAccounts
from portal.models.cards import Cards, CardStatus
from portal.models.transfers import TransferStatus, Transfers

from . import logger, ns

quote_parser = reqparse.RequestParser()
quote_parser.add_argument('amount', type=float, required=True, location='json')

initiate_parser = reqparse.RequestParser()
initiate_parser.add_argument('card_id', type=str, required=True, location='json')
initiate_parser.add_argument('bank_account_id', type=str, required=True, location='json')
initiate_parser.add_argument('amount', type=float, required=True, location='json')

list_parser = reqparse.RequestParser()
list_parser.add_argument('page', type=int, default=1, location='args')
list_parser.add_argument('per_page', type=int, default=20, location='args')
list_parser.add_argument('status', type=str, required=False, location='args')


def transfer_dict(transfer: Transfers, detailed: bool = False) -> dict:
    data = {
        'transfer_id': transfer.transfer_id,
        'principal_amount': to_float(transfer.principal_amount),
        'convenience_fee': to_float(transfer.convenience_fee),
        'gst_on_fee': to_float(transfer.gst_on_fee),
        'total_charged_to_card': to_float(transfer.total_charged_to_card),
        'net_payout_amount': to_float(transfer.net_payout_amount),
        'status': transfer.status,
        'card': {
            'card_id': transfer.card_id,
            'masked_pan': transfer.card.masked_pan if transfer.card else None,
            'issuer_bank': transfer.card.card_issuer_bank if transfer.card else None,
        },
        'destination': {
            'bank_account_id': transfer.bank_account_id,
            'masked_account': (
                transfer.bank_account.masked_account() if transfer.bank_account else None
            ),
            'bank_name': transfer.bank_account.bank_name if transfer.bank_account else None,
        },
        'utr': transfer.bank_rrn_utr,
        'created_on': iso(transfer.created_on),
        'charged_at': iso(transfer.charged_at),
        'payout_completed_at': iso(transfer.payout_completed_at),
        'failure_code': transfer.failure_code,
        'failure_reason': transfer.failure_reason,
        'is_terminal': transfer.status in TransferStatus.TERMINAL,
    }

    if detailed:
        data['fee_percentage_applied'] = to_float(transfer.fee_percentage_applied)
        data['transaction_id'] = transfer.transaction_id
        data['gateway_order_id'] = transfer.gateway_order_id
        data['payout_reference'] = transfer.payout_reference
        data['payout_retry_count'] = transfer.payout_retry_count
        data['reversed_at'] = iso(transfer.reversed_at)
        data['reversal_reference'] = transfer.reversal_reference
        data['timeline'] = _timeline(transfer)

    return data


def _timeline(transfer: Transfers) -> list:
    """
    Render the state machine as something a user can follow.

    A raw status string means nothing to someone whose money is in flight; this
    turns it into the sequence of things that have happened and what is next.
    """
    steps = [
        {'key': 'INITIATED', 'label': 'Transfer requested',
         'at': iso(transfer.created_on), 'done': True},
        {'key': 'RISK_CHECKED', 'label': 'Security checks passed',
         'at': iso(transfer.created_on),
         'done': transfer.status not in (
             TransferStatus.INITIATED, TransferStatus.RISK_FAILED
         )},
        {'key': 'CHARGED', 'label': 'Card charged',
         'at': iso(transfer.charged_at), 'done': bool(transfer.charged_at)},
        {'key': 'PAYOUT', 'label': 'Sent to your bank',
         'at': iso(transfer.payout_dispatched_at),
         'done': bool(transfer.payout_dispatched_at)},
        {'key': 'SETTLED', 'label': 'Money credited',
         'at': iso(transfer.payout_completed_at),
         'done': transfer.status == TransferStatus.SUCCEEDED},
    ]

    if transfer.status == TransferStatus.RISK_FAILED:
        steps[1].update({'label': 'Security check failed', 'failed': True})
    if transfer.status == TransferStatus.FAILED:
        steps[2].update({'label': 'Card charge failed', 'failed': True})
    if transfer.status in (
        TransferStatus.REVERSAL_INIT, TransferStatus.REVERSED_TO_CARD
    ):
        steps[3].update({'label': 'Payout failed', 'failed': True})
        steps[4] = {
            'key': 'REVERSED', 'label': 'Refunded to your card',
            'at': iso(transfer.reversed_at),
            'done': transfer.status == TransferStatus.REVERSED_TO_CARD,
        }

    return steps


@ns.route('/quote')
class TransferQuote(Resource):
    @ns.doc('quote_transfer', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Fee breakdown and remaining headroom for an amount.

        Reserves nothing. Powers the live disclosure the PRD requires before the
        3DS challenge, so the user sees the exact card charge while typing.
        """
        args = quote_parser.parse_args()
        user = current_user()

        try:
            amount = validate_amount(
                args['amount'],
                'amount',
                minimum=settings.get_decimal(Key.TRANSFER_MIN_AMOUNT),
            )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        return success(transfer_engine.quote(user=user, amount=amount))


@ns.route('/limits')
class TransferLimits(Resource):
    @ns.doc('get_limits', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Current limits and usage, for the amount screen."""
        user = current_user()
        quote = transfer_engine.quote(
            user=user, amount=settings.get_decimal(Key.TRANSFER_MIN_AMOUNT)
        )
        return success({
            'limits': quote['limits'],
            'fee_percentage': float(
                settings.get_decimal(Key.TRANSFER_CONVENIENCE_FEE_PERCENT)
            ),
            'gst_percentage': float(settings.get_decimal(Key.GST_PERCENT)),
            'feature_enabled': settings.flag_enabled(
                settings.Flag.CREDIT_TO_BANK_TRANSFER, str(user.user_id)
            ),
        })


@ns.route('')
class TransferList(Resource):
    @ns.doc('list_transfers', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Transfer history, newest first."""
        args = list_parser.parse_args()
        user = current_user()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = Transfers.query.filter_by(user_id=user.user_id)
        if args.get('status'):
            query = query.filter(Transfers.status == args['status'])

        pagination = query.order_by(Transfers.created_on.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return paginated(
            [transfer_dict(t) for t in pagination.items],
            page, per_page, pagination.total,
        )

    @ns.doc('initiate_transfer', security='Bearer')
    @jwt_required()
    @active_user_required
    @kyc_required('MINIMUM')
    def post(self):
        """
        Open a transfer and return the payment session for the 3DS challenge.

        Requires X-Idempotency-Key. Nothing is charged here - the card is only
        debited once the gateway confirms the authenticated payment.
        """
        args = initiate_parser.parse_args()
        user = current_user()

        try:
            key = validate_idempotency_key(idempotency_key())
            amount = validate_amount(
                args['amount'],
                'amount',
                minimum=settings.get_decimal(Key.TRANSFER_MIN_AMOUNT),
            )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        card = Cards.query.filter_by(
            card_id=args['card_id'], user_id=user.user_id
        ).first()
        if not card or card.status == CardStatus.DELETED:
            return failure(ErrorCode.NOT_FOUND, 'Card not found.', 404)

        bank_account = BankAccounts.query.filter_by(
            bank_account_id=args['bank_account_id'],
            user_id=user.user_id,
            deleted_at=None,
        ).first()
        if not bank_account:
            return failure(ErrorCode.NOT_FOUND, 'Bank account not found.', 404)

        try:
            transfer = transfer_engine.initiate(
                user=user,
                card=card,
                bank_account=bank_account,
                amount=amount,
                idempotency_key=key,
                device_uuid=device_uuid(),
                ip=client_ip(),
            )
        except transfer_engine.TransferError as exc:
            return failure(
                exc.code, exc.message, 400,
                details=exc.details, recovery=exc.recovery,
            )

        payload = transfer_dict(transfer, detailed=True)
        payload['payment_session_id'] = getattr(transfer, 'payment_session_id', None)
        payload['three_ds_url'] = transfer.three_ds_url

        return success(
            payload,
            'Transfer initiated. Complete authentication to continue.',
            201,
        )


@ns.route('/<string:transfer_id>')
class TransferDetail(Resource):
    @ns.doc('get_transfer', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, transfer_id):
        user = current_user()
        transfer = Transfers.query.filter_by(
            transfer_id=transfer_id, user_id=user.user_id
        ).first()

        if not transfer:
            return failure(ErrorCode.NOT_FOUND, 'Transfer not found.', 404)

        return success(transfer_dict(transfer, detailed=True))


@ns.route('/<string:transfer_id>/confirm')
class ConfirmTransfer(Resource):
    @ns.doc('confirm_transfer', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, transfer_id):
        """
        Confirm after the 3DS challenge returns.

        Belt and braces alongside the webhook: whichever arrives first resolves
        the transfer, and the second is a no-op. The gateway is always
        re-queried, so a client claiming success proves nothing on its own.
        """
        user = current_user()
        transfer = Transfers.query.filter_by(
            transfer_id=transfer_id, user_id=user.user_id
        ).first()

        if not transfer:
            return failure(ErrorCode.NOT_FOUND, 'Transfer not found.', 404)

        if transfer.status in TransferStatus.TERMINAL:
            return success(
                transfer_dict(transfer, detailed=True),
                'This transfer has already completed.',
            )

        try:
            transfer = transfer_engine.confirm_charge(transfer)
        except transfer_engine.TransferError as exc:
            return failure(exc.code, exc.message, 400, recovery=exc.recovery)
        except Exception as exc:
            logger.exception(f'Confirm failed for transfer {transfer_id}: {exc}')
            return failure(
                ErrorCode.INTERNAL_ERROR,
                'We could not confirm this transfer. Our team has been notified.',
                500,
            )

        messages = {
            TransferStatus.SUCCEEDED: 'Transfer completed successfully.',
            TransferStatus.PAYOUT_PROCESSING: (
                'Your card was charged and the transfer to your bank is being '
                'processed.'
            ),
            TransferStatus.REVERSED_TO_CARD: (
                'The transfer could not be completed. Your card has been '
                'refunded.'
            ),
            TransferStatus.FAILED: (
                transfer.failure_reason or 'The transfer could not be completed.'
            ),
        }

        return success(
            transfer_dict(transfer, detailed=True),
            messages.get(transfer.status, 'Transfer status updated.'),
        )


@ns.route('/<string:transfer_id>/receipt')
class TransferReceipt(Resource):
    @ns.doc('get_receipt', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, transfer_id):
        """Receipt data for a settled transfer (PRD US-014)."""
        user = current_user()
        transfer = Transfers.query.filter_by(
            transfer_id=transfer_id, user_id=user.user_id
        ).first()

        if not transfer:
            return failure(ErrorCode.NOT_FOUND, 'Transfer not found.', 404)

        if transfer.status != TransferStatus.SUCCEEDED:
            return failure(
                ErrorCode.CONFLICT,
                'A receipt is available only for a completed transfer.',
                409,
            )

        breakdown = fee_calculator.calculate_transfer_fee(
            transfer.principal_amount,
            fee_percent=transfer.fee_percentage_applied,
        )

        return success({
            'receipt_number': f'CASHU-TXF-{transfer.transfer_id[:8].upper()}',
            'transfer_id': transfer.transfer_id,
            'transaction_id': transfer.transaction_id,
            'date': iso(transfer.payout_completed_at or transfer.created_on),
            'customer_name': user.full_name,
            'customer_phone': user.masked_phone(),
            'source': transfer.card.masked_pan if transfer.card else None,
            'destination': (
                f'{transfer.bank_account.bank_name} '
                f'{transfer.bank_account.masked_account()}'
                if transfer.bank_account else None
            ),
            'utr': transfer.bank_rrn_utr,
            'breakdown': fee_calculator.as_floats(breakdown)['breakdown'],
            'status': transfer.status,
        })
