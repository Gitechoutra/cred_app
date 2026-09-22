"""
Credit facility to bank transfers (PRD FR-006, section 9).

The highest-risk feature on the platform. Every endpoint here funnels through
transfer_engine, which owns the state machine, and every money-moving call
requires an X-Idempotency-Key so a double-tapped Confirm cannot charge twice.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal.helpers import adapters, fee_calculator, settings, transfer_engine
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
from portal.models.users import KYCTier

from . import logger, ns

quote_parser = reqparse.RequestParser()
quote_parser.add_argument('amount', type=float, required=True, location='json')

initiate_parser = reqparse.RequestParser()
initiate_parser.add_argument('card_id', type=str, required=True, location='json')
initiate_parser.add_argument('bank_account_id', type=str, required=True, location='json')
initiate_parser.add_argument('amount', type=float, required=True, location='json')
initiate_parser.add_argument('payment_method', type=str, required=False, location='json')

list_parser = reqparse.RequestParser()
list_parser.add_argument('page', type=int, default=1, location='args')
list_parser.add_argument('per_page', type=int, default=20, location='args')
list_parser.add_argument('status', type=str, required=False, location='args')


#: One phrasing per outcome, shared by confirm and verify. Two endpoints
#: describing the same state differently is how a user comes to believe a
#: transfer succeeded on one screen and failed on another.
_OUTCOME_MESSAGES = {
    TransferStatus.SUCCEEDED: 'Transfer completed successfully.',
    TransferStatus.PAYOUT_PROCESSING: (
        'Your card was charged and the transfer to your bank is being processed.'
    ),
    TransferStatus.INBOUND_CHARGED: (
        'Your card was charged. Sending the money to your bank now.'
    ),
    TransferStatus.AUTH_PENDING: (
        'Waiting for your bank to confirm the payment. Do not pay again.'
    ),
    TransferStatus.REVERSED_TO_CARD: (
        'The transfer could not be completed. Your card has been refunded.'
    ),
    TransferStatus.FAILED: 'The transfer could not be completed.',
}

#: Razorpay Checkout hands these back in the browser. Accepted, never trusted -
#: the signature is verified server-side and the charge is re-read from the
#: gateway before the payout is dispatched.
verify_parser = reqparse.RequestParser()
verify_parser.add_argument('razorpay_payment_id', type=str, required=False, location='json')
verify_parser.add_argument('razorpay_order_id', type=str, required=False, location='json')
verify_parser.add_argument('razorpay_signature', type=str, required=False, location='json')


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
            'ifsc_code': transfer.bank_account.ifsc_code if transfer.bank_account else None,
        },
        'source_opening_balance': to_float(transfer.source_opening_balance),
        'source_closing_balance': to_float(transfer.source_closing_balance),
        'destination_opening_balance': to_float(transfer.destination_opening_balance),
        'destination_closing_balance': to_float(transfer.destination_closing_balance),
        'transaction_id': transfer.transaction_id or transfer.transfer_id,
        'utr': transfer.bank_rrn_utr,
        'created_on': iso(transfer.created_on),
        'charged_at': iso(transfer.charged_at),
        'payout_completed_at': iso(transfer.payout_completed_at),
        'failure_code': transfer.failure_code,
        'failure_reason': transfer.failure_reason,
        'is_terminal': transfer.status in TransferStatus.TERMINAL,
        # What actually paid, per the gateway - so the status screen and the
        # receipt name the real instrument rather than assuming the card.
        'source_instrument': transfer.source_instrument,
    }

    if detailed:
        data['source_vpa'] = transfer.source_vpa
        data['fee_percentage_applied'] = to_float(transfer.fee_percentage_applied)
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
            # Bounded at both ends. Without a maximum this happily quoted a
            # fee on a trillion rupees - an amount the risk engine would then
            # refuse at initiate, after the user had been shown a price for it.
            amount = validate_amount(
                args['amount'],
                'amount',
                minimum=settings.get_decimal(Key.TRANSFER_MIN_AMOUNT),
                maximum=(
                    settings.get_decimal(Key.TRANSFER_MAX_SINGLE_FULL_KYC)
                    if user.kyc_tier == KYCTier.FULL
                    else settings.get_decimal(Key.TRANSFER_MAX_SINGLE_STANDARD_KYC)
                ),
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
                payment_method=args.get('payment_method'),
            )
        except transfer_engine.TransferError as exc:
            return failure(
                exc.code, exc.message, 400,
                details=exc.details, recovery=exc.recovery,
            )

        payload = transfer_dict(transfer, detailed=True)
        payload['payment_session_id'] = getattr(transfer, 'payment_session_id', None)
        payload['three_ds_url'] = transfer.three_ds_url

        # Checkout parameters, assembled server-side. The amount in paise comes
        # back from the gateway's own order, never from the client - a browser
        # that could choose the amount could charge one rupee for a fifty
        # thousand rupee transfer.
        payload['checkout'] = {
            'provider': transfer.gateway_provider,
            'key': getattr(transfer, 'checkout_key', None),
            'order_id': transfer.gateway_order_id,
            'amount_paise': getattr(transfer, 'checkout_amount_paise', None),
            'currency': 'INR',
            'prefill': {
                'name': user.full_name or '',
                'contact': user.phone or '',
                'email': user.email or '',
                'vpa': adapters.test_upi_vpa(),
            },
            'upi_enabled': adapters.transfer_upi_funding_allowed(),
        }

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

        return success(
            transfer_dict(transfer, detailed=True),
            (
                transfer.failure_reason
                if transfer.status == TransferStatus.FAILED and transfer.failure_reason
                else _OUTCOME_MESSAGES.get(transfer.status, 'Transfer status updated.')
            ),
        )


@ns.route('/methods')
class TransferPaymentMethods(Resource):
    @ns.doc('list_transfer_payment_methods', security='Bearer')
    @jwt_required()
    def get(self):
        """
        Instruments that can fund a transfer.

        Only a credit card. That is not a gateway limitation - it is what the
        product is: a CashU transfer moves money *from a credit line* to a bank
        account, the convenience fee exists because it is a card advance, and
        the ledger posts against the card. Funding one from UPI would move money
        from a bank to a bank, which is a different product.

        The restriction is returned explicitly, with its reason, so the payment
        screen can say why UPI is absent here but present on an EMI rather than
        leaving the user to wonder.
        """
        upi_allowed = adapters.transfer_upi_funding_allowed()

        permitted = [{
            'mode': 'CREDIT_CARD',
            'label': 'Credit Card',
            'description': 'Charged to your saved credit card',
        }]
        prohibited = []

        if upi_allowed:
            permitted.append({
                'mode': 'UPI',
                'label': 'UPI',
                'description': 'Pay using Google Pay, PhonePe or any UPI app',
            })
        else:
            # Two different reasons, and telling them apart matters: one is a
            # product rule, the other is a gateway account setting somebody can
            # go and change. A single vague message would send an operator
            # looking in the wrong place.
            from portal.helpers import razorpay as _rzp

            gateway_lacks_upi = _rzp.is_configured() and not _rzp.supports('upi')

            prohibited.append({
                'mode': 'UPI',
                'label': 'UPI, Google Pay, PhonePe',
                'reason': (
                    'UPI is not enabled on the connected payment gateway '
                    'account, so it cannot be offered here yet.'
                    if gateway_lacks_upi else
                    'A transfer moves money from your credit card to a bank '
                    'account, so it has to be funded by a card. UPI is '
                    'available for EMI payments.'
                ),
            })

        return success({
            'permitted': permitted,
            'prohibited': prohibited,
            'upi': {
                'enabled': upi_allowed,
                'apps': adapters.UPI_APPS if upi_allowed else [],
                # Prefilled so a tester is not retyping a VPA on every attempt.
                'test_vpa': adapters.test_upi_vpa() if upi_allowed else '',
            },
            'checkout': {
                'provider': adapters.upi_provider(),
                'key': adapters.upi_public_key(),
            },
        })


@ns.route('/<string:transfer_id>/verify')
class VerifyTransfer(Resource):
    @ns.doc('verify_transfer', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, transfer_id):
        """
        Verify a transfer after the user returns from Razorpay Checkout.

        The same contract the EMI path uses, for the same reason: the browser
        hands back a signed payload, the signature is checked against our API
        secret here, and the charge is then re-read from Razorpay before a rupee
        moves or the payout is dispatched. A client POSTing an invented payment
        id gets a failed verification, not a completed transfer.

        Safe to call twice - a terminal transfer is returned untouched, which is
        what a double-submit or a refresh during the handler produces.
        """
        args = verify_parser.parse_args()
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

        claimed_order = args.get('razorpay_order_id')
        if (
            claimed_order
            and transfer.gateway_order_id
            and claimed_order != transfer.gateway_order_id
        ):
            logger.error(
                f'[transfer] verify for {transfer_id} carried order '
                f'{claimed_order} but the transfer is against '
                f'{transfer.gateway_order_id}'
            )
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'That payment belongs to a different order.',
                400,
            )

        try:
            transfer = transfer_engine.confirm_charge(
                transfer,
                gateway_payment_id=args.get('razorpay_payment_id'),
                signature=args.get('razorpay_signature'),
            )
        except transfer_engine.TransferError as exc:
            return failure(exc.code, exc.message, 400, recovery=exc.recovery)
        except Exception as exc:
            logger.exception(f'Verify failed for transfer {transfer_id}: {exc}')
            return failure(
                ErrorCode.INTERNAL_ERROR,
                'We could not verify this transfer. Our team has been notified.',
                500,
            )

        return success(
            transfer_dict(transfer, detailed=True),
            _OUTCOME_MESSAGES.get(transfer.status, 'Transfer status updated.'),
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
