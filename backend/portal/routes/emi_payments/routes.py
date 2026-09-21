"""
Manual EMI payment processing (PRD FR-008, section 11).

Permitted instruments are UPI, netbanking and debit card. Credit cards are
prohibited by RBI from servicing loan debt, and that rule is structural here -
CREDIT_CARD is not a member of PaymentMode, so no request can select it.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal.helpers import adapters, emi_engine
from portal.helpers.helpers import (
    ErrorCode, failure, idempotency_key, iso, paginated, success, to_float,
)
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.validators import (
    ValidationError, validate_amount, validate_choice, validate_idempotency_key,
    validate_pagination, validate_upi_vpa,
)
from portal.models.emi_obligations import EMIObligations
from portal.models.emi_payments import EMIPaymentState, EMIPayments, PaymentMode

from . import logger, ns

pay_parser = reqparse.RequestParser()
pay_parser.add_argument('emi_id', type=str, required=True, location='json')
pay_parser.add_argument('amount', type=float, required=False, location='json')
pay_parser.add_argument('payment_mode', type=str, required=True, location='json')
pay_parser.add_argument('upi_vpa', type=str, required=False, location='json')
pay_parser.add_argument('upi_app', type=str, required=False, location='json')

# Razorpay Checkout hands these back in the browser. They are accepted, never
# trusted: the signature is verified server-side and the payment is then re-read
# from the gateway API before anything is marked paid.
verify_parser = reqparse.RequestParser()
verify_parser.add_argument('razorpay_payment_id', type=str, required=False, location='json')
verify_parser.add_argument('razorpay_order_id', type=str, required=False, location='json')
verify_parser.add_argument('razorpay_signature', type=str, required=False, location='json')

list_parser = reqparse.RequestParser()
list_parser.add_argument('page', type=int, default=1, location='args')
list_parser.add_argument('per_page', type=int, default=20, location='args')
list_parser.add_argument('emi_id', type=str, required=False, location='args')
list_parser.add_argument('status', type=str, required=False, location='args')


#: One phrasing per outcome, shared by confirm, verify and cancel. Three
#: endpoints describing the same state in three different ways is how a user
#: ends up believing a payment succeeded on one screen and failed on another.
_OUTCOME_MESSAGES = {
    EMIPaymentState.SETTLED: 'EMI paid successfully.',
    EMIPaymentState.SUCCESSFUL: (
        'Payment received. Awaiting confirmation from your lender.'
    ),
    EMIPaymentState.PENDING: (
        'Your bank has not confirmed this payment yet. Do not pay again - we '
        'will update this automatically.'
    ),
    EMIPaymentState.FAILED: 'The payment could not be completed.',
    EMIPaymentState.CANCELLED: 'Payment cancelled. You can try again.',
}


def payment_dict(payment: EMIPayments, detailed: bool = False) -> dict:
    obligation = payment.obligation

    data = {
        'payment_id': payment.payment_id,
        'emi_id': payment.emi_id,
        'provider_name': obligation.provider_name if obligation else None,
        'masked_loan_account': (
            obligation.masked_loan_account() if obligation else None
        ),
        'amount': to_float(payment.amount),
        'payment_mode': payment.payment_mode,
        'is_auto_pay': payment.is_auto_pay,
        'status': payment.status,
        'bbps_rrn': payment.bbps_rrn,
        'installment_number': payment.installment_number,
        'due_date': iso(payment.due_date),
        'paid_at': iso(payment.paid_at),
        'settled_at': iso(payment.settled_at),
        'created_on': iso(payment.created_on),
        'failure_code': payment.failure_code,
        'failure_reason': payment.failure_reason,
        'is_terminal': payment.status in EMIPaymentState.TERMINAL,
        'upi_app': payment.upi_app,
        'upi_rrn': payment.upi_rrn,
    }

    if detailed:
        data['transaction_id'] = payment.transaction_id
        data['gateway_provider'] = payment.gateway_provider
        data['gateway_order_id'] = payment.gateway_order_id
        data['gateway_payment_id'] = payment.gateway_payment_id
        data['upi_vpa'] = payment.upi_vpa
        data['biller_ack_utr'] = payment.biller_ack_utr
        data['poll_attempts'] = payment.poll_attempts

    return data


@ns.route('/methods')
class PaymentMethods(Resource):
    @ns.doc('list_payment_methods', security='Bearer')
    @jwt_required()
    def get(self):
        """
        Instruments permitted for EMI payment.

        The prohibition is surfaced explicitly rather than by omission, so the
        UI can explain why a credit card is not on the list instead of leaving
        the user to wonder.
        """
        return success({
            'permitted': [
                {'mode': PaymentMode.UPI_INTENT, 'label': 'UPI',
                 'description': 'Pay using any UPI app'},
                {'mode': PaymentMode.UPI_COLLECT, 'label': 'UPI ID',
                 'description': 'Enter your UPI ID to receive a collect request'},
                {'mode': PaymentMode.NETBANKING, 'label': 'Net Banking',
                 'description': '50+ scheduled commercial banks'},
                {'mode': PaymentMode.DEBIT_CARD, 'label': 'Debit Card',
                 'description': 'RuPay, Visa or Mastercard debit'},
            ],
            'prohibited': [{
                'mode': 'CREDIT_CARD',
                'label': 'Credit Card',
                'reason': 'RBI regulations prohibit settling loan EMIs from a '
                          'credit line.',
            }],
            # Everything the client needs to open UPI checkout. The key id is
            # public by design - Checkout runs in the browser and cannot work
            # without it. The secret is not here and never will be.
            'upi': {
                'provider': adapters.upi_provider(),
                'checkout_key': adapters.upi_public_key(),
                'apps': adapters.UPI_APPS,
            },
        })


@ns.route('')
class EMIPaymentList(Resource):
    @ns.doc('list_emi_payments', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """EMI payment history."""
        args = list_parser.parse_args()
        user = current_user()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        query = EMIPayments.query.filter_by(user_id=user.user_id)
        if args.get('emi_id'):
            query = query.filter(EMIPayments.emi_id == args['emi_id'])
        if args.get('status'):
            query = query.filter(EMIPayments.status == args['status'])

        pagination = query.order_by(EMIPayments.created_on.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return paginated(
            [payment_dict(p) for p in pagination.items],
            page, per_page, pagination.total,
        )

    @ns.doc('pay_emi', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Pay an EMI installment now (PRD FR-008).

        Requires X-Idempotency-Key. Defaults to the full installment when no
        amount is given, since a partial EMI payment is not something most
        lenders accept.
        """
        args = pay_parser.parse_args()
        user = current_user()

        try:
            key = validate_idempotency_key(idempotency_key())
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        obligation = EMIObligations.query.filter_by(
            emi_id=args['emi_id'], user_id=user.user_id
        ).first()
        if not obligation:
            return failure(ErrorCode.NOT_FOUND, 'EMI not found.', 404)

        if not obligation.is_active:
            return failure(
                ErrorCode.CONFLICT, 'This loan is already closed.', 409
            )

        try:
            payment_mode = validate_choice(
                args['payment_mode'], PaymentMode.CHOICES, 'payment_mode'
            )
        except ValidationError:
            # The most likely way to land here is an attempt to pay by credit
            # card, so name the actual reason rather than "invalid choice".
            return failure(
                ErrorCode.INSTRUMENT_NOT_PERMITTED,
                'Credit cards cannot be used to pay loan EMIs. Please use UPI, '
                'netbanking or a debit card.',
                400,
                recovery='Choose UPI, Net Banking or Debit Card.',
            )

        try:
            amount = (
                validate_amount(args['amount'], 'amount')
                if args.get('amount') else obligation.emi_amount
            )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        # The VPA was accepted by the parser and then never looked at, so
        # "mahesh 2605@ibl" opened a real gateway order that could only ever
        # fail. A collect request cannot be sent without an address, so it is
        # required for that mode and format-checked whenever it is supplied.
        upi_vpa = (args.get('upi_vpa') or '').strip()
        if payment_mode == PaymentMode.UPI_COLLECT and not upi_vpa:
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'Enter the UPI ID that should receive the collect request.',
                400,
            )
        if upi_vpa:
            try:
                upi_vpa = validate_upi_vpa(upi_vpa)
            except ValidationError as exc:
                return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        try:
            payment = emi_engine.initiate_payment(
                user=user,
                obligation=obligation,
                amount=amount,
                payment_mode=payment_mode,
                idempotency_key=key,
                upi_app=args.get('upi_app'),
                upi_vpa=upi_vpa or None,
            )
        except emi_engine.EMIPaymentError as exc:
            # A refused duplicate is a conflict, not a malformed request. The
            # distinction matters to anything retrying on 4xx by status alone.
            http_status = 409 if exc.code == ErrorCode.CONFLICT else 400
            return failure(exc.code, exc.message, http_status, recovery=exc.recovery)

        payload = payment_dict(payment, detailed=True)
        payload['payment_session_id'] = getattr(payment, 'payment_session_id', None)
        payload['checkout_url'] = payment.checkout_url

        # Checkout parameters, assembled server-side. The client is handed an
        # amount in paise that came back from the gateway's own order, not one
        # it computed - a browser that could choose the amount could pay a
        # rupee against a thirty-thousand-rupee installment.
        payload['checkout'] = {
            'provider': payment.gateway_provider,
            'key': getattr(payment, 'checkout_key', None),
            'order_id': payment.gateway_order_id,
            'amount_paise': getattr(payment, 'checkout_amount_paise', None),
            'currency': 'INR',
            'prefill': {
                'name': user.full_name or '',
                'contact': user.phone or '',
                'email': user.email or '',
            },
        }

        return success(
            payload, 'Payment initiated. Complete it in your UPI app.', 201
        )


@ns.route('/<string:payment_id>')
class EMIPaymentDetail(Resource):
    @ns.doc('get_emi_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, payment_id):
        user = current_user()
        payment = EMIPayments.query.filter_by(
            payment_id=payment_id, user_id=user.user_id
        ).first()

        if not payment:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        return success(payment_dict(payment, detailed=True))


@ns.route('/<string:payment_id>/confirm')
class ConfirmEMIPayment(Resource):
    @ns.doc('confirm_emi_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, payment_id):
        """Confirm after the user returns from their bank."""
        user = current_user()
        payment = EMIPayments.query.filter_by(
            payment_id=payment_id, user_id=user.user_id
        ).first()

        if not payment:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        if payment.status in EMIPaymentState.TERMINAL:
            return success(
                payment_dict(payment, detailed=True),
                'This payment has already completed.',
            )

        try:
            payment = emi_engine.confirm_payment(payment)
        except Exception as exc:
            logger.exception(f'Confirm failed for EMI payment {payment_id}: {exc}')
            return failure(
                ErrorCode.INTERNAL_ERROR,
                'We could not confirm this payment. Our team has been notified.',
                500,
            )

        return success(
            payment_dict(payment, detailed=True),
            (
                payment.failure_reason
                if payment.status == EMIPaymentState.FAILED and payment.failure_reason
                else _OUTCOME_MESSAGES.get(payment.status, 'Payment status updated.')
            ),
        )


@ns.route('/<string:payment_id>/verify')
class VerifyEMIPayment(Resource):
    @ns.doc('verify_emi_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, payment_id):
        """
        Verify a UPI payment after the user returns from their app.

        This is the browser handing back what Razorpay Checkout gave it. None
        of it is believed on its own: the signature is checked against our API
        secret, and then the payment is re-read from Razorpay before the EMI
        moves. A client that POSTs a made-up payment id gets a failed
        verification, not a paid EMI.

        Safe to call twice. A payment that already reached a terminal state is
        returned as-is, which is what a double-submit or a refresh during the
        handler produces.
        """
        args = verify_parser.parse_args()
        user = current_user()

        payment = EMIPayments.query.filter_by(
            payment_id=payment_id, user_id=user.user_id
        ).first()

        if not payment:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        if payment.status in EMIPaymentState.TERMINAL:
            return success(
                payment_dict(payment, detailed=True),
                'This payment has already completed.',
            )

        # A payload for a different order means the client mixed up two
        # in-flight payments, or is probing. Either way, refuse it rather than
        # letting the engine resolve which order it belongs to.
        claimed_order = args.get('razorpay_order_id')
        if (
            claimed_order
            and payment.gateway_order_id
            and claimed_order != payment.gateway_order_id
        ):
            logger.error(
                f'[emi] verify for {payment_id} carried order {claimed_order} '
                f'but the payment is against {payment.gateway_order_id}'
            )
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'That payment belongs to a different order.',
                400,
            )

        try:
            payment = emi_engine.confirm_payment(
                payment,
                gateway_payment_id=args.get('razorpay_payment_id'),
                signature=args.get('razorpay_signature'),
            )
        except Exception as exc:
            logger.exception(f'Verify failed for EMI payment {payment_id}: {exc}')
            return failure(
                ErrorCode.INTERNAL_ERROR,
                'We could not verify this payment. Our team has been notified.',
                500,
            )

        return success(
            payment_dict(payment, detailed=True),
            _OUTCOME_MESSAGES.get(payment.status, 'Payment status updated.'),
        )


@ns.route('/<string:payment_id>/cancel')
class CancelEMIPayment(Resource):
    @ns.doc('cancel_emi_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, payment_id):
        """
        Abandon an attempt the user backed out of.

        Called when checkout is dismissed. It does not take the user's word for
        it - closing the sheet after authorising is common, and the debit still
        lands - so the engine asks the gateway first and only cancels when
        there is genuinely nothing collected.

        Cancelling is what frees the EMI for a fresh attempt, so this is the
        supported retry path.
        """
        user = current_user()

        payment = EMIPayments.query.filter_by(
            payment_id=payment_id, user_id=user.user_id
        ).first()

        if not payment:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        if payment.status in EMIPaymentState.TERMINAL:
            return success(
                payment_dict(payment, detailed=True),
                'This payment has already completed.',
            )

        try:
            payment = emi_engine.cancel_payment(payment)
        except Exception as exc:
            logger.exception(f'Cancel failed for EMI payment {payment_id}: {exc}')
            return failure(
                ErrorCode.INTERNAL_ERROR,
                'We could not cancel this payment. Our team has been notified.',
                500,
            )

        return success(
            payment_dict(payment, detailed=True),
            _OUTCOME_MESSAGES.get(payment.status, 'Payment cancelled.'),
        )


@ns.route('/<string:payment_id>/receipt')
class EMIReceipt(Resource):
    @ns.doc('get_emi_receipt', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, payment_id):
        """Tax-compliant receipt for a settled EMI payment (PRD US-014)."""
        user = current_user()
        payment = EMIPayments.query.filter_by(
            payment_id=payment_id, user_id=user.user_id
        ).first()

        if not payment:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        if payment.status not in (
            EMIPaymentState.SETTLED, EMIPaymentState.SUCCESSFUL
        ):
            return failure(
                ErrorCode.CONFLICT,
                'A receipt is available only for a completed payment.',
                409,
            )

        obligation = payment.obligation

        return success({
            'receipt_number': f'CASHU-EMI-{payment.payment_id[:8].upper()}',
            'payment_id': payment.payment_id,
            'transaction_id': payment.transaction_id,
            'date': iso(payment.settled_at or payment.paid_at),
            'customer_name': user.full_name,
            'customer_phone': user.masked_phone(),
            'biller': obligation.provider_name if obligation else None,
            'loan_account': (
                obligation.masked_loan_account() if obligation else None
            ),
            'installment_number': payment.installment_number,
            'amount': to_float(payment.amount),
            'payment_mode': payment.payment_mode,
            'bbps_rrn': payment.bbps_rrn,
            'status': payment.status,
        })
