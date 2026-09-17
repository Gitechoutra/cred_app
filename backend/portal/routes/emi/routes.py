"""
EMI obligation registry (PRD FR-007, section 10).

Loans are discovered through the provider adapter where the lender is live on
BBPS, and entered by hand where it is not. A manually entered loan requires an
uploaded sanction letter and admin verification before auto-pay can be armed -
otherwise a user could point a standing debit instruction at arbitrary details.
"""

import os
import uuid

from flask import current_app, request
from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse
from werkzeug.utils import secure_filename

from portal import db
from portal.helpers import audit, emi_provider_adapter
from portal.helpers.encryption import blind_index, encrypt
from portal.helpers.helpers import ErrorCode, failure, iso, success, to_float
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.validators import (
    ValidationError, sanitize_text, validate_amount, validate_choice,
    validate_day_of_month, validate_mobile,
)
from portal.models.base import utcnow
from portal.models.emi_obligations import (
    AutoPayStatus, EMIObligations, EMIPaymentStatus, LoanType,
)
from portal.models.emi_providers import EMIProviders

from . import logger, ns

lookup_parser = reqparse.RequestParser()
lookup_parser.add_argument('provider_id', type=int, required=True, location='json')
lookup_parser.add_argument('loan_account_no', type=str, required=True, location='json')
lookup_parser.add_argument('registered_phone', type=str, required=False, location='json')

add_parser = reqparse.RequestParser()
add_parser.add_argument('provider_id', type=int, required=True, location='json')
add_parser.add_argument('loan_account_no', type=str, required=True, location='json')
add_parser.add_argument('registered_phone', type=str, required=False, location='json')
add_parser.add_argument('nickname', type=str, required=False, location='json')
add_parser.add_argument('loan_type', type=str, required=False, location='json')
add_parser.add_argument('emi_amount', type=float, required=False, location='json')
add_parser.add_argument('due_day_of_month', type=int, required=False, location='json')
add_parser.add_argument('total_tenure', type=int, required=False, location='json')
add_parser.add_argument('tenure_remaining', type=int, required=False, location='json')
add_parser.add_argument('total_loan_amount', type=float, required=False, location='json')
add_parser.add_argument('outstanding_bal', type=float, required=False, location='json')

update_parser = reqparse.RequestParser()
update_parser.add_argument('nickname', type=str, required=False, location='json')
update_parser.add_argument('emi_amount', type=float, required=False, location='json')
update_parser.add_argument('due_day_of_month', type=int, required=False, location='json')
update_parser.add_argument('tenure_remaining', type=int, required=False, location='json')
update_parser.add_argument('outstanding_bal', type=float, required=False, location='json')

ALLOWED_DOC_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}


def obligation_dict(emi: EMIObligations, detailed: bool = False) -> dict:
    today = utcnow().date()

    data = {
        'emi_id': emi.emi_id,
        'provider_id': emi.provider_id,
        'provider_name': emi.provider_name,
        'provider_logo': emi.provider.logo_path if emi.provider else None,
        'brand_color': emi.provider.brand_color if emi.provider else None,
        'masked_loan_account': emi.masked_loan_account(),
        'nickname': emi.nickname,
        'loan_type': emi.loan_type,
        'emi_amount': to_float(emi.emi_amount),
        'due_day_of_month': emi.due_day_of_month,
        'next_due_date': iso(emi.next_due_date),
        'days_until_due': (
            (emi.next_due_date - today).days if emi.next_due_date else None
        ),
        'total_tenure': emi.total_tenure,
        'tenure_remaining': emi.tenure_remaining,
        'tenure_paid': (
            (emi.total_tenure - emi.tenure_remaining)
            if emi.total_tenure and emi.tenure_remaining is not None else None
        ),
        'progress_percentage': (
            round(
                (emi.total_tenure - emi.tenure_remaining) / emi.total_tenure * 100, 1
            )
            if emi.total_tenure and emi.tenure_remaining is not None
            and emi.total_tenure > 0 else None
        ),
        'total_loan_amount': to_float(emi.total_loan_amount),
        'outstanding_bal': to_float(emi.outstanding_bal),
        'interest_rate': to_float(emi.interest_rate),
        'auto_pay_status': emi.auto_pay_status,
        'payment_status': emi.payment_status,
        'is_overdue': emi.payment_status == EMIPaymentStatus.OVERDUE,
        'is_active': emi.is_active,
        'admin_verified': emi.admin_verified,
        'is_manually_created': emi.is_manually_created,
    }

    if detailed:
        data['last_paid_date'] = iso(emi.last_paid_date)
        data['created_on'] = iso(emi.created_on)
        data['can_enable_autopay'] = (
            emi.is_active
            and (emi.admin_verified or not emi.is_manually_created)
            and emi.auto_pay_status == AutoPayStatus.NOT_CONFIGURED
        )
        mandate = emi.mandate
        data['mandate'] = {
            'mandate_id': mandate.mandate_id,
            'umn': mandate.mandate_umn,
            'status': mandate.status,
            'max_amount': to_float(mandate.max_amount),
            'next_debit_date': iso(mandate.next_debit_date),
            'mandate_type': mandate.mandate_type,
        } if mandate else None

    return data


@ns.route('/providers')
class ProviderList(Resource):
    @ns.doc('list_providers', security='Bearer')
    @jwt_required()
    def get(self):
        """Searchable lender directory for the Add EMI screen."""
        providers = EMIProviders.query.order_by(
            EMIProviders.display_order.asc(), EMIProviders.display_name.asc()
        ).all()

        return success([{
            'provider_id': p.provider_id,
            'provider_name': p.provider_name,
            'display_name': p.display_name,
            'logo_path': p.logo_path,
            'brand_color': p.brand_color,
            'supports_auto_fetch': p.supports_auto_fetch,
            'supports_auto_pay': p.supports_auto_pay,
            'integration_mode': p.integration_mode,
        } for p in providers])


@ns.route('/lookup')
class LoanLookup(Resource):
    @ns.doc('lookup_loan', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Fetch loan details from the lender before saving (PRD FR-007).

        A failed lookup is a normal outcome - a mistyped LAN is the most common
        thing that happens on this screen - so it returns a 200 with
        manual_entry_available rather than an error the UI has to special-case.
        """
        args = lookup_parser.parse_args()
        user = current_user()

        provider = EMIProviders.query.filter_by(
            provider_id=args['provider_id'], is_active=True
        ).first()
        if not provider:
            return failure(ErrorCode.NOT_FOUND, 'Provider not found.', 404)

        lan = sanitize_text(args['loan_account_no'], 50)
        if not lan:
            return failure(
                ErrorCode.VALIDATION_ERROR, 'Enter your loan account number.', 400
            )

        phone = None
        if args.get('registered_phone'):
            try:
                phone = validate_mobile(args['registered_phone'], 'registered_phone')
            except ValidationError as exc:
                return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        result = emi_provider_adapter.fetch_loan(
            provider=provider, loan_account_no=lan, registered_phone=phone
        )

        if not result.get('ok'):
            return success({
                'found': False,
                'manual_entry_available': True,
                'reason': result.get('error'),
                'code': result.get('code'),
                'retryable': result.get('retryable', False),
            }, result.get('error', 'Loan account not found. Please enter a valid loan account number.'))

        data = result['data']
        return success({
            'found': True,
            'provider_name': provider.display_name,
            'loan_account_masked': f'LAN-******{lan[-4:]}',
            'emi_amount': float(data['emi_amount']),
            'due_day_of_month': data['due_day_of_month'],
            'total_tenure': data['total_tenure'],
            'tenure_remaining': data['tenure_remaining'],
            'total_loan_amount': float(data['total_loan_amount']),
            'outstanding_bal': float(data['outstanding_bal']),
            'interest_rate': float(data['interest_rate']),
            'next_due_date': data['next_due_date'].isoformat(),
            'loan_type': data['loan_type'],
        }, 'Loan details fetched successfully.')


@ns.route('')
class EMIList(Resource):
    @ns.doc('list_emi', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """All EMI obligations for the signed-in user."""
        user = current_user()

        obligations = EMIObligations.query.filter_by(
            user_id=user.user_id
        ).order_by(
            EMIObligations.is_active.desc(),
            EMIObligations.next_due_date.asc(),
        ).all()

        active = [e for e in obligations if e.is_active]

        return success({
            'obligations': [obligation_dict(e) for e in obligations],
            'active_count': len(active),
            'total_monthly_emi': sum(float(e.emi_amount or 0) for e in active),
            'total_outstanding': sum(float(e.outstanding_bal or 0) for e in active),
            'overdue_count': sum(
                1 for e in active if e.payment_status == EMIPaymentStatus.OVERDUE
            ),
        })

    @ns.doc('add_emi', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Register an EMI obligation.

        Details are taken from the provider where the lookup succeeded, and from
        the request body where the user is entering them by hand.
        """
        args = add_parser.parse_args()
        user = current_user()

        provider = EMIProviders.query.filter_by(
            provider_id=args['provider_id'], is_active=True
        ).first()
        if not provider:
            return failure(ErrorCode.NOT_FOUND, 'Provider not found.', 404)

        lan = sanitize_text(args['loan_account_no'], 50)
        if not lan:
            return failure(
                ErrorCode.VALIDATION_ERROR, 'Enter your loan account number.', 400
            )

        fingerprint = blind_index(lan)
        duplicate = EMIObligations.query.filter_by(
            user_id=user.user_id, provider_id=provider.provider_id, is_active=True
        ).all()
        for row in duplicate:
            if row.loan_account_last4 == lan[-4:]:
                return failure(
                    ErrorCode.CONFLICT,
                    'This loan is already being tracked.',
                    409,
                )

        fetched = emi_provider_adapter.fetch_loan(
            provider=provider, loan_account_no=lan
        )
        auto = fetched.get('data') if fetched.get('ok') else None

        try:
            if auto:
                emi_amount = auto['emi_amount']
                due_day = auto['due_day_of_month']
                total_tenure = auto['total_tenure']
                tenure_remaining = auto['tenure_remaining']
                total_loan = auto['total_loan_amount']
                outstanding = auto['outstanding_bal']
                interest = auto['interest_rate']
                loan_type = auto['loan_type']
                next_due = auto['next_due_date']
            else:
                if not args.get('emi_amount') or not args.get('due_day_of_month'):
                    return failure(
                        ErrorCode.VALIDATION_ERROR,
                        'Enter your monthly EMI amount and due date.',
                        400,
                    )
                emi_amount = validate_amount(args['emi_amount'], 'emi_amount')
                due_day = validate_day_of_month(
                    args['due_day_of_month'], 'due_day_of_month'
                )
                total_tenure = args.get('total_tenure')
                tenure_remaining = args.get('tenure_remaining')
                total_loan = (
                    validate_amount(args['total_loan_amount'], 'total_loan_amount')
                    if args.get('total_loan_amount') else None
                )
                outstanding = (
                    validate_amount(args['outstanding_bal'], 'outstanding_bal')
                    if args.get('outstanding_bal') else None
                )
                interest = None
                loan_type = validate_choice(
                    args.get('loan_type') or LoanType.CONSUMER_DURABLE,
                    LoanType.CHOICES, 'loan_type',
                )
                next_due = emi_provider_adapter.next_due_date(due_day)

            phone = (
                validate_mobile(args['registered_phone'], 'registered_phone')
                if args.get('registered_phone') else None
            )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        obligation = EMIObligations(
            user_id=user.user_id,
            provider_id=provider.provider_id,
            provider_name=provider.display_name,
            loan_account_no_enc=encrypt(lan),
            loan_account_last4=lan[-4:],
            registered_phone=phone,
            loan_type=loan_type,
            nickname=sanitize_text(args.get('nickname'), 100) or None,
            emi_amount=emi_amount,
            due_day_of_month=due_day,
            total_tenure=total_tenure,
            tenure_remaining=tenure_remaining,
            total_loan_amount=total_loan,
            outstanding_bal=outstanding,
            interest_rate=interest,
            next_due_date=next_due,
            payment_status=EMIPaymentStatus.DUE,
            auto_pay_status=AutoPayStatus.NOT_CONFIGURED,
            is_manually_created=auto is None,
            admin_verified=auto is not None,
            last_synced_at=utcnow() if auto else None,
        )
        db.session.add(obligation)
        db.session.commit()

        audit.record(
            action='EMI_OBLIGATION_ADDED',
            entity_type='EMIObligations',
            entity_id=obligation.emi_id,
            actor_user_id=str(user.user_id),
            after={
                'provider': provider.display_name,
                'emi_amount': float(emi_amount),
                'manual': auto is None,
            },
        )

        message = (
            'EMI added successfully.' if auto
            else 'EMI added. Upload your loan sanction letter so we can verify '
                 'these details before enabling auto-pay.'
        )
        return success(obligation_dict(obligation, detailed=True), message, 201)


@ns.route('/<string:emi_id>')
class EMIDetail(Resource):
    @ns.doc('get_emi', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, emi_id):
        """Obligation detail with its payment history."""
        user = current_user()

        obligation = EMIObligations.query.filter_by(
            emi_id=emi_id, user_id=user.user_id
        ).first()
        if not obligation:
            return failure(ErrorCode.NOT_FOUND, 'EMI not found.', 404)

        from portal.models.emi_payments import EMIPayments

        payments = obligation.payments.order_by(
            EMIPayments.created_on.desc()
        ).limit(12).all()

        data = obligation_dict(obligation, detailed=True)
        data['payment_history'] = [{
            'payment_id': p.payment_id,
            'amount': to_float(p.amount),
            'status': p.status,
            'payment_mode': p.payment_mode,
            'is_auto_pay': p.is_auto_pay,
            'bbps_rrn': p.bbps_rrn,
            'installment_number': p.installment_number,
            'paid_at': iso(p.paid_at),
            'created_on': iso(p.created_on),
        } for p in payments]

        return success(data)

    @ns.doc('update_emi', security='Bearer')
    @jwt_required()
    @active_user_required
    def patch(self, emi_id):
        """Correct obligation details the user maintains."""
        args = update_parser.parse_args()
        user = current_user()

        obligation = EMIObligations.query.filter_by(
            emi_id=emi_id, user_id=user.user_id
        ).first()
        if not obligation:
            return failure(ErrorCode.NOT_FOUND, 'EMI not found.', 404)

        before = obligation_dict(obligation)

        try:
            if args.get('nickname') is not None:
                obligation.nickname = sanitize_text(args['nickname'], 100) or None
            if args.get('emi_amount') is not None:
                obligation.emi_amount = validate_amount(
                    args['emi_amount'], 'emi_amount'
                )
            if args.get('due_day_of_month') is not None:
                obligation.due_day_of_month = validate_day_of_month(
                    args['due_day_of_month'], 'due_day_of_month'
                )
                obligation.next_due_date = emi_provider_adapter.next_due_date(
                    obligation.due_day_of_month
                )
            if args.get('tenure_remaining') is not None:
                obligation.tenure_remaining = max(0, int(args['tenure_remaining']))
            if args.get('outstanding_bal') is not None:
                obligation.outstanding_bal = validate_amount(
                    args['outstanding_bal'], 'outstanding_bal'
                )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        # Changing the amount invalidates the mandate ceiling that was approved
        # against the old figure, so the mandate must be re-registered.
        mandate = obligation.mandate
        if mandate and args.get('emi_amount') is not None:
            from portal.helpers.fee_calculator import mandate_cap
            if mandate.max_amount < mandate_cap(obligation.emi_amount):
                from portal.helpers import mandate_engine
                mandate_engine.revoke(
                    mandate, reason='EMI amount changed; mandate limit no longer valid.'
                )

        db.session.commit()

        audit.record(
            action='EMI_OBLIGATION_UPDATED',
            entity_type='EMIObligations',
            entity_id=obligation.emi_id,
            actor_user_id=str(user.user_id),
            before=before,
            after=obligation_dict(obligation),
        )

        return success(obligation_dict(obligation, detailed=True), 'EMI updated.')

    @ns.doc('remove_emi', security='Bearer')
    @jwt_required()
    @active_user_required
    def delete(self, emi_id):
        """Stop tracking a loan, revoking any mandate first."""
        user = current_user()

        obligation = EMIObligations.query.filter_by(
            emi_id=emi_id, user_id=user.user_id
        ).first()
        if not obligation:
            return failure(ErrorCode.NOT_FOUND, 'EMI not found.', 404)

        from portal.models.emi_payments import EMIPaymentState, EMIPayments

        in_flight = obligation.payments.filter(
            EMIPayments.status.notin_(EMIPaymentState.TERMINAL)
        ).count()
        if in_flight:
            return failure(
                ErrorCode.CONFLICT,
                'A payment for this EMI is in progress. Please wait for it to '
                'complete.',
                409,
            )

        mandate = obligation.mandate
        if mandate and mandate.status in ('ACTIVE', 'PENDING_AFA'):
            from portal.helpers import mandate_engine
            mandate_engine.revoke(mandate, reason='Obligation removed by user.')

        obligation.is_active = False
        obligation.closed_at = utcnow()
        obligation.auto_pay_status = AutoPayStatus.NOT_CONFIGURED
        db.session.commit()

        audit.record(
            action='EMI_OBLIGATION_REMOVED',
            entity_type='EMIObligations',
            entity_id=obligation.emi_id,
            actor_user_id=str(user.user_id),
        )

        return success(None, 'EMI removed from tracking.')


@ns.route('/<string:emi_id>/document')
class LoanDocument(Resource):
    @ns.doc('upload_loan_document', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, emi_id):
        """
        Upload the loan sanction letter for a manually entered obligation.

        PRD FR-007 requires this before an admin can verify a manual entry, and
        verification is what unlocks auto-pay for it.
        """
        user = current_user()

        obligation = EMIObligations.query.filter_by(
            emi_id=emi_id, user_id=user.user_id
        ).first()
        if not obligation:
            return failure(ErrorCode.NOT_FOUND, 'EMI not found.', 404)

        upload = request.files.get('document')
        if not upload or not upload.filename:
            return failure(
                ErrorCode.VALIDATION_ERROR, 'Please attach your loan document.', 400
            )

        extension = os.path.splitext(secure_filename(upload.filename))[1].lower()
        if extension not in ALLOWED_DOC_EXTENSIONS:
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'Upload a PDF or an image (JPG, PNG).',
                400,
            )

        folder = os.path.join(
            current_app.config['UPLOAD_FOLDER'], 'loan_docs', str(user.user_id)
        )
        os.makedirs(folder, exist_ok=True)

        # Stored under a random name: the original filename is attacker-supplied
        # and may itself carry a path or a misleading extension.
        filename = f'{uuid.uuid4().hex}{extension}'
        upload.save(os.path.join(folder, filename))

        obligation.loan_document_path = os.path.join(
            'loan_docs', str(user.user_id), filename
        ).replace('\\', '/')
        obligation.admin_verified = False
        db.session.commit()

        audit.record(
            action='EMI_DOCUMENT_UPLOADED',
            entity_type='EMIObligations',
            entity_id=obligation.emi_id,
            actor_user_id=str(user.user_id),
        )

        return success(
            {'uploaded': True},
            'Document uploaded. Our team will verify your loan details shortly.',
        )
