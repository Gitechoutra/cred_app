"""
Pay Bills endpoints.

Thin shells over bill_pay_engine, in the order the screen uses them:

    GET  /eligibility        limits, fees, verified banks, blockers
    POST /quote              price a bill (no side effects)
    POST ''                  record a consented request, send the OTP
    POST /<id>/otp           resend the OTP
    POST /<id>/confirm       verify the OTP, draw credit, dispatch payout
    POST /<id>/cancel        back out before the OTP
    GET  /<id>               status, refreshed from the rail
    GET  ''                  history

No request parser here accepts a fee, a total or a balance. The client sends a
bill amount and what the bill is; everything priced comes back from the engine.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, inputs, reqparse

from portal.helpers import bill_pay_engine, settings
from portal.helpers.bill_pay_engine import BillPayError
from portal.helpers.helpers import (
    ErrorCode, client_ip, device_uuid, failure, idempotency_key, iso, paginated,
    success, to_float,
)
from portal.helpers.jwt import active_user_required, current_user, kyc_required
from portal.helpers.settings import Key
from portal.helpers.validators import (
    ValidationError, sanitize_text, validate_amount, validate_idempotency_key,
    validate_pagination,
)
from portal.models.bill_payments import (
    BillCategory, BillPayments, BillPaymentStatus, BillPurpose,
)

from . import ns

# Money fields carry no type, so the raw text reaches validate_amount - the
# same '1e9' defence as every other money route.
create_parser = reqparse.RequestParser()
create_parser.add_argument('category', type=str, required=True, location='json')
create_parser.add_argument('provider', type=str, required=True, location='json')
create_parser.add_argument('bill_reference', type=str, required=True, location='json')
create_parser.add_argument('purpose', type=str, required=True, location='json')
create_parser.add_argument('purpose_note', type=str, required=False, location='json')
create_parser.add_argument('amount', required=True, location='json')
create_parser.add_argument('bank_account_id', type=str, required=True, location='json')
create_parser.add_argument('consent', type=inputs.boolean, required=False, location='json')

quote_parser = reqparse.RequestParser()
quote_parser.add_argument('amount', required=True, location='json')

confirm_parser = reqparse.RequestParser()
confirm_parser.add_argument('otp', type=str, required=True, location='json')
#: Development only: what the simulated payout rail should do. Ignored in
#: production and whenever the rail is not the simulator.
confirm_parser.add_argument('sandbox_outcome', type=str, required=False, location='json')

list_parser = reqparse.RequestParser()
list_parser.add_argument('page', type=int, default=1, location='args')
list_parser.add_argument('per_page', type=int, default=20, location='args')


# -- Serialisers -----------------------------------------------------------

def _bank_dict(bank) -> dict:
    # The bank-accounts screen's own serialiser, so a bank reads the same here.
    from portal.routes.bank_accounts.routes import account_dict
    data = account_dict(bank)
    return {
        key: data[key] for key in (
            'bank_account_id', 'bank_name', 'masked_account', 'account_last4',
            'ifsc_code', 'is_primary', 'is_payout_eligible', 'verified_at',
        )
    }


def _timeline(record: BillPayments) -> list:
    failed = record.status == BillPaymentStatus.FAILED
    returned = record.status == BillPaymentStatus.REVERSED
    steps = [
        {'label': 'Request submitted', 'at': iso(record.created_on), 'done': True},
        {'label': 'Verified with OTP', 'at': iso(record.otp_verified_at),
         'done': record.otp_verified_at is not None},
        {'label': 'Credit utilised', 'at': iso(record.otp_verified_at),
         'done': record.credit_transaction_id is not None},
        {'label': 'Sent to your bank', 'at': iso(record.payout_dispatched_at),
         'done': record.payout_dispatched_at is not None and not failed},
    ]
    if failed:
        steps.append({'label': 'Payment failed - credit restored', 'at': iso(record.completed_at),
                      'done': True, 'failed': True})
    elif returned:
        steps.append({'label': 'Payment successful', 'done': True})
        steps.append({'label': 'Returned by bank - credit restored',
                      'at': iso(record.completed_at), 'done': True, 'failed': True})
    else:
        steps.append({'label': 'Payment successful', 'at': iso(record.completed_at),
                      'done': record.status == BillPaymentStatus.SUCCEEDED})
    return steps


def bill_payment_dict(record: BillPayments) -> dict:
    return {
        'bill_payment_id': record.bill_payment_id,
        'reference': record.reference,
        'status': record.status,
        'category': record.category,
        'category_label': record.category_label,
        'provider': record.provider,
        'bill_reference': record.bill_reference_number,
        'purpose': record.purpose,
        'purpose_label': record.purpose_label,
        'purpose_note': record.purpose_note,
        'bill_amount': to_float(record.bill_amount),
        'fee_percent': to_float(record.fee_percent),
        'fee_amount': to_float(record.fee_amount),
        'gst_amount': to_float(record.gst_amount),
        'total_amount': to_float(record.total_amount),
        'bank': record.bank_display,
        'available_after': to_float(record.available_after),
        'utr': record.bank_utr,
        'transaction_id': record.transaction_id,
        'failure_code': record.failure_code,
        'failure_reason': record.failure_reason,
        'disclosure_version': record.disclosure_version,
        'consent_at': iso(record.consent_at),
        'otp_verified_at': iso(record.otp_verified_at),
        'created_on': iso(record.created_on),
        'completed_at': iso(record.completed_at),
        'timeline': _timeline(record),
    }


def _otp_dict(info: dict, user) -> dict:
    if not info:
        return None
    data = {
        'masked_mobile': user.masked_phone(),
        'length': info.get('length'),
        'expires_in_seconds': info.get('expires_in_seconds'),
        'resends_remaining': info.get('resends_remaining'),
    }
    # Present only in DEBUG, exactly as the login OTP does.
    if info.get('debug_otp'):
        data['debug_otp'] = info['debug_otp']
    return data


def _error(exc: BillPayError):
    details = {'field': exc.field} if exc.field else None
    return failure(exc.code, exc.message, exc.status, details=details, recovery=exc.recovery)


def _owned(bill_payment_id: str, user):
    return BillPayments.query.filter_by(
        bill_payment_id=bill_payment_id, user_id=user.user_id,
    ).first()


# -- Endpoints -------------------------------------------------------------

@ns.route('/eligibility')
class BillPayEligibility(Resource):
    @ns.doc('bill_pay_eligibility', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Limits, fees, verified accounts and anything stopping a payment."""
        user = current_user()
        state = bill_pay_engine.eligibility(user)

        return success({
            **{k: (to_float(v) if hasattr(v, 'quantize') else v)
               for k, v in state.items() if k != 'banks'},
            'banks': [_bank_dict(bank) for bank in state['banks']],
            'categories': [
                {
                    'value': value,
                    'label': BillCategory.LABELS[value],
                    'providers': BillCategory.PROVIDERS.get(value, []),
                    'purposes': bill_pay_engine.ALLOWED_PURPOSES[value],
                }
                for value in BillCategory.CHOICES
            ],
            'purposes': [
                {'value': value, 'label': BillPurpose.LABELS[value]}
                for value in BillPurpose.CHOICES
            ],
        })


@ns.route('/quote')
class BillPayQuote(Resource):
    @ns.doc('bill_pay_quote', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """Price a bill: fee, GST and the total the credit line is charged."""
        args = quote_parser.parse_args()
        try:
            amount = validate_amount(args['amount'], 'amount')
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        priced = bill_pay_engine.quote(amount)
        return success({key: to_float(value) for key, value in priced.items()})


@ns.route('')
class BillPaymentList(Resource):
    @ns.doc('list_bill_payments', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """The holder's Pay Bills history, newest first."""
        args = list_parser.parse_args()
        user = current_user()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        pagination = BillPayments.query.filter(
            BillPayments.user_id == user.user_id,
            # Requests abandoned before the OTP never moved money; they are not
            # history.
            BillPayments.otp_verified_at.isnot(None),
        ).order_by(BillPayments.created_on.desc()).paginate(
            page=page, per_page=per_page, error_out=False,
        )
        return paginated(
            [bill_payment_dict(r) for r in pagination.items],
            page, per_page, pagination.total,
        )

    @ns.doc('create_bill_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    @kyc_required('MINIMUM')
    def post(self):
        """
        Record a priced, consented Pay Bills request and send its OTP.

        Requires X-Idempotency-Key. A replay returns the original request.
        """
        args = create_parser.parse_args()
        user = current_user()

        try:
            key = validate_idempotency_key(idempotency_key())
            amount = validate_amount(
                args['amount'], 'amount',
                minimum=settings.get_decimal(Key.PAYMENT_MIN_AMOUNT),
            )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        bank_name = None
        from portal.models.bank_accounts import BankAccounts
        bank = BankAccounts.query.filter_by(
            bank_account_id=args['bank_account_id'], user_id=user.user_id,
        ).first()
        if bank is not None:
            bank_name = _bank_dict(bank)['bank_name']

        try:
            record, otp_info = bill_pay_engine.create(
                user=user,
                category=(args['category'] or '').upper(),
                provider=sanitize_text(args['provider'] or '', max_length=120),
                bill_reference=sanitize_text(args['bill_reference'] or '', max_length=50),
                purpose=(args['purpose'] or '').upper(),
                purpose_note=sanitize_text(args.get('purpose_note') or '', max_length=200),
                amount=amount,
                bank_account_id=args['bank_account_id'],
                consent=bool(args.get('consent')),
                idempotency_key=key,
                bank_name=bank_name,
                ip=client_ip(),
                device=device_uuid() or None,
            )
        except BillPayError as exc:
            return _error(exc)

        return success(
            {'bill_payment': bill_payment_dict(record), 'otp': _otp_dict(otp_info, user)},
            'Enter the OTP sent to your registered mobile.',
            201 if otp_info else 200,
        )


@ns.route('/<string:bill_payment_id>')
class BillPaymentDetail(Resource):
    @ns.doc('get_bill_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, bill_payment_id):
        """One request, brought up to date with the payout rail first."""
        user = current_user()
        record = _owned(bill_payment_id, user)
        if record is None:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)
        bill_pay_engine.refresh(record)
        return success(bill_payment_dict(record))


@ns.route('/by-transaction/<string:transaction_id>')
class BillPaymentByTransaction(Resource):
    @ns.doc('get_bill_payment_by_transaction', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, transaction_id):
        """The request behind a History row, so History can open its detail."""
        user = current_user()
        record = BillPayments.query.filter_by(
            transaction_id=transaction_id, user_id=user.user_id,
        ).first()
        if record is None:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)
        bill_pay_engine.refresh(record)
        return success(bill_payment_dict(record))


@ns.route('/<string:bill_payment_id>/otp')
class BillPaymentOtp(Resource):
    @ns.doc('resend_bill_payment_otp', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, bill_payment_id):
        """Send a fresh OTP for a request still awaiting one."""
        user = current_user()
        record = _owned(bill_payment_id, user)
        if record is None:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)
        try:
            info = bill_pay_engine.send_otp(record, user, ip=client_ip(),
                                            device=device_uuid() or None)
        except BillPayError as exc:
            return _error(exc)
        return success({'otp': _otp_dict(info, user)}, 'OTP sent.')


@ns.route('/<string:bill_payment_id>/confirm')
class BillPaymentConfirm(Resource):
    @ns.doc('confirm_bill_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    @kyc_required('MINIMUM')
    def post(self, bill_payment_id):
        """
        Verify the OTP, draw the credit and dispatch the payout.

        The answer is the record's status - PROCESSING, PENDING, SUCCEEDED or
        FAILED - never an assumption: the client polls GET /<id> until the
        status is final.
        """
        args = confirm_parser.parse_args()
        user = current_user()
        record = _owned(bill_payment_id, user)
        if record is None:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        code = (args['otp'] or '').strip()
        if not code.isdigit():
            return failure(ErrorCode.OTP_INVALID, 'Enter the OTP sent to your mobile.', 400)

        try:
            record = bill_pay_engine.confirm(
                record, user, code,
                sandbox_outcome=(args.get('sandbox_outcome') or '').upper() or None,
            )
        except BillPayError as exc:
            return _error(exc)

        return success(bill_payment_dict(record), {
            BillPaymentStatus.SUCCEEDED: 'Payment successful.',
            BillPaymentStatus.PENDING: 'Payment is being processed.',
            BillPaymentStatus.PROCESSING: 'Payment is being processed.',
            BillPaymentStatus.FAILED: 'Payment could not be completed.',
        }.get(record.status, 'Payment updated.'))


@ns.route('/<string:bill_payment_id>/cancel')
class BillPaymentCancel(Resource):
    @ns.doc('cancel_bill_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, bill_payment_id):
        """Back out before the OTP. Nothing has been charged at that point."""
        user = current_user()
        record = _owned(bill_payment_id, user)
        if record is None:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)
        try:
            bill_pay_engine.cancel(record)
        except BillPayError as exc:
            return _error(exc)
        return success(bill_payment_dict(record), 'Cancelled. Nothing was charged.')
