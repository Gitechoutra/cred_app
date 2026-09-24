"""
Scan-and-pay: UPI payments made by scanning a merchant QR code.

A separate product from a transfer, and worth naming the difference. A transfer
moves money from the user's own credit card to their own verified bank account,
and a third-party destination is refused outright. A scanned payment sends money
from the user's bank, over UPI, to somebody else. The penny-drop name match and
the card-limit check do not apply here because neither is relevant.

The scanned payload never reaches the payment path as text. `/decode` validates
it and returns a structured, sanitised summary; `/` takes that summary back and
re-validates the parts that matter. Nothing the camera read is ever trusted
twice.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal.helpers import qr_payment_engine, settings, upi_qr
from portal.helpers.helpers import (
    ErrorCode, failure, idempotency_key, iso, paginated, success, to_float,
)
from portal.helpers.jwt import active_user_required, current_user, kyc_required
from portal.helpers.validators import (
    ValidationError, validate_amount, validate_idempotency_key,
    validate_pagination,
)
from portal.models.qr_payments import QRPaymentState, QRPayments

from . import logger, ns

decode_parser = reqparse.RequestParser()
decode_parser.add_argument('payload', type=str, required=True, location='json')

pay_parser = reqparse.RequestParser()
pay_parser.add_argument('payload', type=str, required=True, location='json')
# Deliberately not type=float. flask-restx would coerce the value before
# validate_amount ever saw it, so '1e9' arrived as 1000000000.0 and passed
# the plain-decimal check that exists to reject exactly that. The raw text
# has to reach the validator intact.
pay_parser.add_argument('amount', required=False, location='json')

verify_parser = reqparse.RequestParser()
verify_parser.add_argument('razorpay_payment_id', type=str, required=False, location='json')
verify_parser.add_argument('razorpay_order_id', type=str, required=False, location='json')
verify_parser.add_argument('razorpay_signature', type=str, required=False, location='json')

list_parser = reqparse.RequestParser()
list_parser.add_argument('page', type=int, default=1, location='args')
list_parser.add_argument('per_page', type=int, default=20, location='args')


_OUTCOME_MESSAGES = {
    QRPaymentState.SUCCESSFUL: 'Payment successful.',
    QRPaymentState.PENDING: (
        'Your bank has not confirmed this payment yet. Do not pay again - we '
        'will update this automatically.'
    ),
    QRPaymentState.FAILED: 'The payment could not be completed.',
    QRPaymentState.CANCELLED: 'Payment cancelled. Nothing was charged.',
}


def payment_dict(payment: QRPayments, detailed: bool = False) -> dict:
    data = {
        'qr_payment_id': payment.qr_payment_id,
        'transaction_id': payment.transaction_id,
        'payee_name': payment.payee_name,
        # Masked on the way out. A full payment address on a receipt is more
        # than the payer needs and more than a screenshot should carry.
        'payee_vpa': upi_qr.masked_vpa(payment.payee_vpa),
        'amount': to_float(payment.amount),
        'amount_from_qr': bool(payment.amount_from_qr),
        'note': payment.note,
        'status': payment.status,
        'payment_method': 'UPI_QR',
        'upi_rrn': payment.upi_rrn,
        'paid_at': iso(payment.paid_at),
        'created_on': iso(payment.created_on),
        'failure_code': payment.failure_code,
        'failure_reason': payment.failure_reason,
        'is_terminal': payment.status in QRPaymentState.TERMINAL,
    }

    if detailed:
        data['gateway_provider'] = payment.gateway_provider
        data['gateway_order_id'] = payment.gateway_order_id
        data['payee_reference'] = payment.payee_reference

    return data


@ns.route('/decode')
class DecodeQR(Resource):
    @ns.doc('decode_upi_qr', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Validate a scanned QR and return what it is asking for.

        Deliberately server-side. A QR is untrusted input printed by anyone, so
        the parsing, the address format, the amount bounds and the stripping of
        the display name all happen where they cannot be skipped - not in the
        scanner component, which a modified client could bypass.

        Returns a structured summary for the confirmation screen. The raw
        payload is never echoed back.
        """
        args = decode_parser.parse_args()

        try:
            details = upi_qr.parse(args['payload'])
        except upi_qr.QRError as exc:
            # Logged without the payload: a scanned string can contain anything.
            logger.info(f'[qr] rejected a scan: {exc.code}')
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'reason': exc.code})

        return success({
            'payee_name': details['payee_name'],
            'payee_vpa': upi_qr.masked_vpa(details['vpa']),
            'amount': to_float(details['amount']) if details['amount'] else None,
            'amount_locked': details['amount_locked'],
            'note': details['note'],
            'currency': details['currency'],
        })


@ns.route('')
class QRPaymentList(Resource):
    @ns.doc('list_qr_payments', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Scanned payment history."""
        args = list_parser.parse_args()
        user = current_user()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        pagination = QRPayments.query.filter_by(
            user_id=user.user_id
        ).order_by(QRPayments.created_on.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

        return paginated(
            [payment_dict(p) for p in pagination.items],
            page, per_page, pagination.total,
        )

    @ns.doc('pay_qr', security='Bearer')
    @jwt_required()
    @active_user_required
    @kyc_required('MINIMUM')
    def post(self):
        """
        Pay a scanned QR.

        Requires X-Idempotency-Key, so a double tap or a retried request
        resolves to one payment rather than two - which on this screen is the
        difference between paying a shop once and paying it twice.

        The payload is re-parsed here rather than trusting the decoded summary
        the client holds: between decoding and confirming, only the amount is
        allowed to change, and only when the QR did not fix one.
        """
        args = pay_parser.parse_args()
        user = current_user()

        try:
            key = validate_idempotency_key(idempotency_key())
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        try:
            details = upi_qr.parse(args['payload'])
        except upi_qr.QRError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'reason': exc.code})

        if details['amount'] is not None:
            amount = details['amount']
        else:
            if args.get('amount') is None:
                return failure(
                    ErrorCode.VALIDATION_ERROR,
                    'Enter the amount you want to pay.',
                    400,
                )
            try:
                amount = validate_amount(
                    args['amount'], 'amount',
                    minimum=settings.get_decimal(settings.Key.PAYMENT_MIN_AMOUNT),
                )
            except ValidationError as exc:
                return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        try:
            payment = qr_payment_engine.initiate(
                user=user, details=details, amount=amount, idempotency_key=key,
            )
        except qr_payment_engine.QRPaymentError as exc:
            return failure(exc.code, exc.message, 400, recovery=exc.recovery)

        payload = payment_dict(payment, detailed=True)
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

        return success(payload, 'Complete the payment in your UPI app.', 201)


@ns.route('/<string:qr_payment_id>')
class QRPaymentDetail(Resource):
    @ns.doc('get_qr_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, qr_payment_id):
        user = current_user()
        payment = QRPayments.query.filter_by(
            qr_payment_id=qr_payment_id, user_id=user.user_id
        ).first()

        if not payment:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        return success(payment_dict(payment, detailed=True))


@ns.route('/<string:qr_payment_id>/verify')
class VerifyQRPayment(Resource):
    @ns.doc('verify_qr_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, qr_payment_id):
        """
        Verify after the user returns from their UPI app.

        Same contract as every other payment here: the signature is checked
        server-side and the payment re-read from the gateway before it counts.
        A client claiming success proves nothing.
        """
        args = verify_parser.parse_args()
        user = current_user()

        payment = QRPayments.query.filter_by(
            qr_payment_id=qr_payment_id, user_id=user.user_id
        ).first()

        if not payment:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        if payment.status in QRPaymentState.TERMINAL:
            return success(payment_dict(payment, detailed=True),
                           'This payment has already completed.')

        claimed = args.get('razorpay_order_id')
        if claimed and payment.gateway_order_id and claimed != payment.gateway_order_id:
            logger.error(
                f'[qr] verify for {qr_payment_id} carried order {claimed} '
                f'but the payment is against {payment.gateway_order_id}'
            )
            return failure(ErrorCode.VALIDATION_ERROR,
                           'That payment belongs to a different order.', 400)

        try:
            payment = qr_payment_engine.confirm(
                payment,
                gateway_payment_id=args.get('razorpay_payment_id'),
                signature=args.get('razorpay_signature'),
            )
        except Exception as exc:
            logger.exception(f'Verify failed for QR payment {qr_payment_id}: {exc}')
            return failure(
                ErrorCode.INTERNAL_ERROR,
                'We could not verify this payment. Our team has been notified.',
                500,
            )

        return success(
            payment_dict(payment, detailed=True),
            _OUTCOME_MESSAGES.get(payment.status, 'Payment status updated.'),
        )


@ns.route('/<string:qr_payment_id>/cancel')
class CancelQRPayment(Resource):
    @ns.doc('cancel_qr_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, qr_payment_id):
        """Abandon a scan the user backed out of."""
        user = current_user()
        payment = QRPayments.query.filter_by(
            qr_payment_id=qr_payment_id, user_id=user.user_id
        ).first()

        if not payment:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        if payment.status in QRPaymentState.TERMINAL:
            return success(payment_dict(payment, detailed=True),
                           'This payment has already completed.')

        try:
            payment = qr_payment_engine.cancel(payment)
        except Exception as exc:
            logger.exception(f'Cancel failed for QR payment {qr_payment_id}: {exc}')
            return failure(ErrorCode.INTERNAL_ERROR,
                           'We could not cancel this payment.', 500)

        return success(
            payment_dict(payment, detailed=True),
            _OUTCOME_MESSAGES.get(payment.status, 'Payment cancelled.'),
        )
