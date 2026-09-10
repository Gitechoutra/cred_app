"""
Auto-pay mandate management (PRD FR-009, section 12).

NPCI e-Mandate and UPI AutoPay registration, pause, resume and cancellation.
Every regulatory guarantee in PRD 12.2 - AFA at registration, T-48h pre-debit
notice, user revocation up to 24h before the debit - is enforced in
mandate_engine rather than here.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal.helpers import mandate_engine, settings
from portal.helpers.fee_calculator import mandate_cap
from portal.helpers.helpers import ErrorCode, failure, iso, success, to_float
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.settings import Key
from portal.helpers.validators import (
    ValidationError, sanitize_text, validate_amount, validate_choice,
    validate_date, validate_upi_vpa,
)
from portal.models.auto_pay_mandates import (
    AutoPayMandates, MandateFrequency, MandateStatus, MandateType,
)
from portal.models.bank_accounts import BankAccounts
from portal.models.emi_obligations import EMIObligations
from portal.models.mandate_debit_attempts import MandateDebitAttempts

from . import logger, ns

create_parser = reqparse.RequestParser()
create_parser.add_argument('emi_id', type=str, required=True, location='json')
create_parser.add_argument('max_amount', type=float, required=False, location='json')
create_parser.add_argument('bank_account_id', type=str, required=False, location='json')
create_parser.add_argument('upi_vpa', type=str, required=False, location='json')
create_parser.add_argument('frequency', type=str, required=False, location='json',
                           default=MandateFrequency.MONTHLY)
create_parser.add_argument('end_date', type=str, required=False, location='json')

afa_parser = reqparse.RequestParser()
afa_parser.add_argument('otp', type=str, required=False, location='json')
afa_parser.add_argument('provider_reference', type=str, required=False, location='json')

action_parser = reqparse.RequestParser()
action_parser.add_argument('reason', type=str, required=False, location='json')


def mandate_dict(mandate: AutoPayMandates, detailed: bool = False) -> dict:
    obligation = mandate.obligation

    data = {
        'mandate_id': mandate.mandate_id,
        'emi_id': mandate.emi_id,
        'provider_name': obligation.provider_name if obligation else None,
        'masked_loan_account': (
            obligation.masked_loan_account() if obligation else None
        ),
        'mandate_type': mandate.mandate_type,
        'mandate_umn': mandate.mandate_umn,
        'max_amount': to_float(mandate.max_amount),
        'emi_amount': to_float(obligation.emi_amount) if obligation else None,
        'frequency': mandate.frequency,
        'status': mandate.status,
        'next_debit_date': iso(mandate.next_debit_date),
        'last_debit_date': iso(mandate.last_debit_date),
        'upi_vpa': mandate.upi_vpa,
        'start_date': iso(mandate.start_date),
        'end_date': iso(mandate.end_date),
        'is_active': mandate.status == MandateStatus.ACTIVE,
    }

    if detailed:
        data['consecutive_failures'] = mandate.consecutive_failures
        data['activated_at'] = iso(mandate.activated_at)
        data['predebit_notice_sent_for'] = iso(mandate.predebit_notice_sent_for)

        # Whether the user may still stop the next debit. Inside 24 hours the
        # instruction is with the sponsor bank and CashU cannot recall it.
        can_pause = mandate.status == MandateStatus.ACTIVE
        if can_pause and mandate.next_debit_date:
            from portal.models.base import utcnow
            can_pause = (mandate.next_debit_date - utcnow().date()).days >= 1
        data['can_pause'] = can_pause

        attempts = mandate.debit_attempts.order_by(
            MandateDebitAttempts.scheduled_at.desc()
        ).limit(10).all()
        data['recent_attempts'] = [{
            'attempt_id': a.attempt_id,
            'cycle_date': iso(a.cycle_date),
            'attempt_number': a.attempt_number,
            'scheduled_at': iso(a.scheduled_at),
            'executed_at': iso(a.executed_at),
            'amount': to_float(a.amount),
            'result': a.result,
            'failure_reason': a.failure_reason,
        } for a in attempts]

    return data


@ns.route('')
class MandateList(Resource):
    @ns.doc('list_mandates', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """All mandates for the signed-in user."""
        user = current_user()

        mandates = AutoPayMandates.query.filter_by(
            user_id=user.user_id
        ).order_by(AutoPayMandates.created_on.desc()).all()

        return success({
            'mandates': [mandate_dict(m) for m in mandates],
            'active_count': sum(
                1 for m in mandates if m.status == MandateStatus.ACTIVE
            ),
        })

    @ns.doc('create_mandate', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Register an auto-pay mandate.

        Created in PENDING_AFA. It cannot debit anything until the
        additional-factor challenge completes, which is what RBI requires at
        mandate registration.
        """
        args = create_parser.parse_args()
        user = current_user()

        obligation = EMIObligations.query.filter_by(
            emi_id=args['emi_id'], user_id=user.user_id
        ).first()
        if not obligation:
            return failure(ErrorCode.NOT_FOUND, 'EMI not found.', 404)

        if not obligation.is_active:
            return failure(ErrorCode.CONFLICT, 'This loan is already closed.', 409)

        # A manually entered loan has unverified details; arming a standing
        # debit against them would let a user point one anywhere.
        if obligation.is_manually_created and not obligation.admin_verified:
            return failure(
                ErrorCode.FORBIDDEN,
                'Auto-pay can be enabled once we verify your loan details. '
                'Please upload your loan sanction letter.',
                403,
                recovery='Upload your loan document from the EMI detail screen.',
            )

        if obligation.provider and not obligation.provider.supports_auto_pay:
            return failure(
                ErrorCode.FEATURE_DISABLED,
                f'{obligation.provider_name} does not support auto-pay yet.',
                400,
            )

        bank_account = None
        upi_vpa = None

        try:
            if args.get('upi_vpa'):
                upi_vpa = validate_upi_vpa(args['upi_vpa'])
            if args.get('bank_account_id'):
                bank_account = BankAccounts.query.filter_by(
                    bank_account_id=args['bank_account_id'],
                    user_id=user.user_id,
                    deleted_at=None,
                ).first()
                if not bank_account:
                    return failure(
                        ErrorCode.NOT_FOUND, 'Bank account not found.', 404
                    )
                if not bank_account.is_payout_eligible:
                    return failure(
                        ErrorCode.ACCOUNT_NOT_VERIFIED,
                        'Please verify this bank account before using it for '
                        'auto-pay.',
                        400,
                    )

            if not upi_vpa and not bank_account:
                return failure(
                    ErrorCode.VALIDATION_ERROR,
                    'Choose a UPI ID or a bank account for the mandate.',
                    400,
                )

            max_amount = (
                validate_amount(args['max_amount'], 'max_amount')
                if args.get('max_amount') else None
            )
            frequency = validate_choice(
                args.get('frequency') or MandateFrequency.MONTHLY,
                MandateFrequency.CHOICES, 'frequency',
            )
            end_date = validate_date(args.get('end_date'), 'end_date')
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        try:
            mandate = mandate_engine.register(
                user=user,
                obligation=obligation,
                max_amount=max_amount,
                bank_account_id=bank_account.bank_account_id if bank_account else None,
                upi_vpa=upi_vpa,
                frequency=frequency,
                end_date=end_date,
            )
        except mandate_engine.MandateError as exc:
            return failure(exc.code, exc.message, 400)

        payload = mandate_dict(mandate, detailed=True)
        payload['requires_afa'] = True
        payload['afa_method'] = (
            'UPI PIN' if mandate.mandate_type == MandateType.UPI_AUTOPAY
            else 'Aadhaar OTP or Net Banking'
        )

        return success(
            payload,
            'Mandate created. Complete authentication with your bank to '
            'activate auto-pay.',
            201,
        )


@ns.route('/preview')
class MandatePreview(Resource):
    @ns.doc('preview_mandate', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """
        Mandate parameters for an EMI, before the user commits.

        Shows the rail that will be used and the minimum permissible ceiling, so
        the review screen the PRD requires is populated without a round trip.
        """
        emi_id = sanitize_text(
            __import__('flask').request.args.get('emi_id', ''), 40
        )
        user = current_user()

        obligation = EMIObligations.query.filter_by(
            emi_id=emi_id, user_id=user.user_id
        ).first()
        if not obligation:
            return failure(ErrorCode.NOT_FOUND, 'EMI not found.', 404)

        minimum_cap = mandate_cap(obligation.emi_amount)
        mandate_type = mandate_engine.choose_type(obligation.emi_amount)

        return success({
            'emi_id': obligation.emi_id,
            'provider_name': obligation.provider_name,
            'emi_amount': to_float(obligation.emi_amount),
            'mandate_type': mandate_type,
            'mandate_type_label': (
                'UPI AutoPay' if mandate_type == MandateType.UPI_AUTOPAY
                else 'e-NACH (Net Banking / Debit Card)'
            ),
            'minimum_max_amount': float(minimum_cap),
            'suggested_max_amount': float(minimum_cap),
            'cap_multiplier': float(settings.get_decimal(Key.MANDATE_CAP_MULTIPLIER)),
            'cap_explanation': (
                'The mandate limit is set slightly above your EMI so a small '
                'interest adjustment does not cause a failed debit.'
            ),
            'frequency': MandateFrequency.MONTHLY,
            'next_debit_date': iso(obligation.next_due_date),
            'predebit_notice_hours': settings.get_int(
                Key.MANDATE_PREDEBIT_NOTICE_HOURS
            ),
            'debit_time': '04:00 IST on the due date',
        })


@ns.route('/<string:mandate_id>')
class MandateDetail(Resource):
    @ns.doc('get_mandate', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, mandate_id):
        user = current_user()
        mandate = AutoPayMandates.query.filter_by(
            mandate_id=mandate_id, user_id=user.user_id
        ).first()

        if not mandate:
            return failure(ErrorCode.NOT_FOUND, 'Mandate not found.', 404)

        return success(mandate_dict(mandate, detailed=True))

    @ns.doc('cancel_mandate', security='Bearer')
    @jwt_required()
    @active_user_required
    def delete(self, mandate_id):
        """Cancel a mandate (PRD 12.2 user revocation facility)."""
        args = action_parser.parse_args()
        user = current_user()

        mandate = AutoPayMandates.query.filter_by(
            mandate_id=mandate_id, user_id=user.user_id
        ).first()
        if not mandate:
            return failure(ErrorCode.NOT_FOUND, 'Mandate not found.', 404)

        if mandate.status == MandateStatus.REVOKED:
            return success(mandate_dict(mandate), 'This mandate is already cancelled.')

        mandate_engine.revoke(
            mandate,
            reason=sanitize_text(args.get('reason'), 255) or 'Cancelled by user',
        )

        return success(mandate_dict(mandate), 'Auto-pay cancelled.')


@ns.route('/<string:mandate_id>/activate')
class ActivateMandate(Resource):
    @ns.doc('activate_mandate', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, mandate_id):
        """
        Complete the AFA challenge and activate.

        NPCI issues the Unique Mandate Number here; every later pre-debit notice
        and debit instruction quotes it.
        """
        args = afa_parser.parse_args()
        user = current_user()

        mandate = AutoPayMandates.query.filter_by(
            mandate_id=mandate_id, user_id=user.user_id
        ).first()
        if not mandate:
            return failure(ErrorCode.NOT_FOUND, 'Mandate not found.', 404)

        try:
            mandate = mandate_engine.complete_afa(
                mandate, provider_reference=args.get('provider_reference')
            )
        except mandate_engine.MandateError as exc:
            return failure(exc.code, exc.message, 400)

        return success(
            mandate_dict(mandate, detailed=True),
            'Auto-pay is now active. We will notify you 48 hours before every '
            'debit.',
        )


@ns.route('/<string:mandate_id>/pause')
class PauseMandate(Resource):
    @ns.doc('pause_mandate', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, mandate_id):
        """Pause upcoming debits."""
        args = action_parser.parse_args()
        user = current_user()

        mandate = AutoPayMandates.query.filter_by(
            mandate_id=mandate_id, user_id=user.user_id
        ).first()
        if not mandate:
            return failure(ErrorCode.NOT_FOUND, 'Mandate not found.', 404)

        try:
            mandate = mandate_engine.pause(
                mandate, reason=sanitize_text(args.get('reason'), 255)
            )
        except mandate_engine.MandateError as exc:
            return failure(exc.code, exc.message, 409)

        return success(mandate_dict(mandate), 'Auto-pay paused.')


@ns.route('/<string:mandate_id>/resume')
class ResumeMandate(Resource):
    @ns.doc('resume_mandate', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, mandate_id):
        """Resume a paused mandate."""
        user = current_user()

        mandate = AutoPayMandates.query.filter_by(
            mandate_id=mandate_id, user_id=user.user_id
        ).first()
        if not mandate:
            return failure(ErrorCode.NOT_FOUND, 'Mandate not found.', 404)

        try:
            mandate = mandate_engine.resume(mandate)
        except mandate_engine.MandateError as exc:
            return failure(exc.code, exc.message, 409)

        return success(mandate_dict(mandate), 'Auto-pay resumed.')
