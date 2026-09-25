"""
The credit line, end to end.

The journey these endpoints serve, in order:

    apply -> KYC gate -> review -> approval -> limit -> purpose -> activation
    -> purchases -> statement -> bill payment -> credit restored

Every money-moving route here is a thin shell. It validates the request, hands
the decision to credit_engine and renders the result. None of them computes a
limit, a balance or an available amount, and none of them accepts one from the
client: `available_credit` appears in responses and in no request parser
anywhere in this file. That is the whole defence against a client talking itself
into more credit, and it only works if it stays true, so a new endpoint here
that writes a balance directly is a bug however carefully it does the sums.

Idempotency is required on both of the routes that move money - a purchase and a
bill payment - and a replay returns the original transaction with 200 rather
than creating a second one.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal.helpers import adapters, credit_engine, settings, test_cards
from portal.helpers.helpers import (
    ErrorCode, failure, idempotency_key, iso, paginated, success, to_float,
)
from portal.helpers.jwt import active_user_required, current_user, kyc_required
from portal.helpers.settings import Key
from portal.helpers.validators import (
    ValidationError, sanitize_text, validate_amount, validate_choice,
    validate_idempotency_key, validate_pagination,
)
from portal.models.credit_accounts import CreditAccountStatus, CreditPurpose
from portal.models.credit_applications import (
    ApplicationStatus, CreditApplications, EmploymentType,
)
from portal.models.credit_statements import CreditStatements
from portal.models.credit_transactions import (
    BillPaymentMethod, CreditTransactions, CreditTransactionStatus,
    CreditTransactionType, MerchantCategory,
)

from . import logger, ns

# -- Parsers ---------------------------------------------------------------
# Money fields are declared without a type so the raw text reaches
# validate_amount. flask-restx's own coercion would turn '1e9' into a billion
# before the plain-decimal check that exists to reject it ever ran.

apply_parser = reqparse.RequestParser()
apply_parser.add_argument('employment_type', type=str, required=True, location='json')
apply_parser.add_argument('monthly_income', required=True, location='json')
apply_parser.add_argument('existing_emi_outflow', required=False, location='json')
apply_parser.add_argument('requested_limit', required=False, location='json')

purpose_parser = reqparse.RequestParser()
purpose_parser.add_argument('purpose', type=str, required=True, location='json')
purpose_parser.add_argument('purpose_note', type=str, required=False, location='json')

purchase_parser = reqparse.RequestParser()
purchase_parser.add_argument('amount', required=True, location='json')
purchase_parser.add_argument('merchant_name', type=str, required=True, location='json')
purchase_parser.add_argument('merchant_category', type=str, required=False,
                             location='json')
purchase_parser.add_argument('description', type=str, required=False, location='json')
#: Development only, and gated in the engine as well as here.
purchase_parser.add_argument('test_card_last4', type=str, required=False,
                             location='json')

pay_parser = reqparse.RequestParser()
pay_parser.add_argument('amount', required=True, location='json')
pay_parser.add_argument('payment_method', type=str, required=False, location='json')
pay_parser.add_argument('statement_id', type=str, required=False, location='json')
#: Development only: the outcome the simulated gateway should produce, so a
#: decline, an abandoned checkout and a timeout can all be walked through.
#: Ignored in production and whenever the rail is a real gateway.
pay_parser.add_argument('sandbox_outcome', type=str, required=False, location='json')

# Checkout hands these back in the browser. Accepted, never trusted: the
# signature is verified server-side and the payment is then re-read from the
# gateway before any credit is restored.
verify_parser = reqparse.RequestParser()
verify_parser.add_argument('razorpay_payment_id', type=str, required=False, location='json')
verify_parser.add_argument('razorpay_order_id', type=str, required=False, location='json')
verify_parser.add_argument('razorpay_signature', type=str, required=False, location='json')

block_parser = reqparse.RequestParser()
block_parser.add_argument('reason', type=str, required=False, location='json')

list_parser = reqparse.RequestParser()
list_parser.add_argument('page', type=int, default=1, location='args')
list_parser.add_argument('per_page', type=int, default=20, location='args')
list_parser.add_argument('type', type=str, required=False, location='args')
list_parser.add_argument('status', type=str, required=False, location='args')


#: Names older clients send for a bill-payment method. 'UPI' predates the split
#: into app and ID, and meant paying from an app.
_METHOD_ALIASES = {'UPI': BillPaymentMethod.UPI_INTENT}

#: One phrasing per outcome, shared by the pay, verify and cancel responses. The
#: same state described three ways is how somebody ends up believing a payment
#: succeeded on one screen and failed on another.
_PAYMENT_OUTCOME = {
    CreditTransactionStatus.PROCESSING: (
        'Your bank has not confirmed this payment yet. Do not pay again - we '
        'will update it automatically.'
    ),
    CreditTransactionStatus.CANCELLED: 'Payment cancelled. Nothing was charged.',
}


# -- Serialisers -----------------------------------------------------------

def application_dict(application: CreditApplications) -> dict:
    reason = application.decision_reason
    return {
        'application_id': application.application_id,
        'status': application.status,
        'employment_type': application.employment_type,
        'monthly_income': to_float(application.monthly_income),
        'existing_emi_outflow': to_float(application.existing_emi_outflow),
        'requested_limit': to_float(application.requested_limit),
        'offered_limit': to_float(application.offered_limit),
        'approved_limit': to_float(application.approved_limit),
        'eligibility_score': to_float(application.eligibility_score),
        'decision_reason': reason,
        # Derived from the code rather than stored, so one decision always reads
        # the same way however long ago it was made.
        'decision_message': (
            credit_engine.DecisionReason.MESSAGES.get(reason) if reason else None
        ),
        'decision_note': application.decision_note,
        'submitted_at': iso(application.submitted_at),
        'kyc_verified_at': iso(application.kyc_verified_at),
        'decided_at': iso(application.decided_at),
        'is_open': application.is_open,
    }


def account_dict(account, detailed: bool = False) -> dict:
    """
    The account as the client may see it.

    The card number here is the BIN, filler and last four - assembled for
    display. The digits between them are not stored anywhere, so there is
    nothing to accidentally include.
    """
    data = {
        'credit_account_id': account.credit_account_id,
        'status': account.status,
        'card_number_masked': account.masked_number,
        'card_last4': account.card_last4,
        'card_network': account.card_network,
        'name_on_card': account.name_on_card,
        'expiry': f'{account.expiry_month}/{account.expiry_year[-2:]}',
        'credit_limit': to_float(account.credit_limit),
        'available_credit': to_float(account.available_credit),
        'current_outstanding': to_float(account.current_outstanding),
        'utilization_percent': account.utilization_percent,
        'currency': account.currency,
        'purpose': account.purpose,
        'purpose_label': (
            CreditPurpose.LABELS.get(account.purpose) if account.purpose else None
        ),
        'purpose_note': account.purpose_note,
        'can_spend': account.can_spend,
        'activated_at': iso(account.activated_at),
    }

    if detailed:
        data.update({
            'statement_day': account.statement_day,
            'grace_days': account.grace_days,
            'block_reason': account.block_reason,
            'blocked_at': iso(account.blocked_at),
            'purpose_declared_at': iso(account.purpose_declared_at),
            'application_id': account.application_id,
            # What is spent but not yet billed. A distinct number from the
            # outstanding balance, which also includes anything billed and
            # unpaid, and the one people mean by "what have I spent this month".
            'unbilled_spend': to_float(_unbilled_spend(account)),
            'next_step': _next_step(account),
        })

    return data


def transaction_reference(txn: CreditTransactions) -> str:
    """
    The transaction ID a holder quotes to support.

    Derived from the row's UUID rather than stored, so it is unique by
    construction and the same on every screen, receipt and statement. The
    prefix says what it is at a glance when read out over the phone.
    """
    return f'CCT{txn.credit_transaction_id.replace("-", "")[:12].upper()}'


def transaction_dict(txn: CreditTransactions, *, purpose_label: str = None,
                     refunded: float = None) -> dict:
    return {
        'credit_transaction_id': txn.credit_transaction_id,
        'reference': transaction_reference(txn),
        'transaction_id': txn.transaction_id,
        'type': txn.transaction_type,
        'status': txn.status,
        'is_terminal': txn.status in CreditTransactionStatus.TERMINAL,
        'amount': to_float(txn.amount),
        'direction': 'DEBIT' if txn.is_debit else 'CREDIT',
        'balance_after': to_float(txn.balance_after),
        'available_after': to_float(txn.available_after),
        'merchant_name': txn.merchant_name,
        'merchant_category': txn.merchant_category,
        'description': txn.description,
        # The purpose the line was opened for. Per account rather than per row,
        # so it is passed in by a caller that already has the account loaded.
        'credit_purpose': purpose_label,
        'statement_id': txn.statement_id,
        'is_test': txn.is_test,
        'failure_code': txn.failure_code,
        'failure_reason': txn.failure_reason,
        'refunded_amount': refunded or 0.0,
        'payment_method': txn.payment_method,
        'payment_method_label': (
            BillPaymentMethod.LABELS.get(txn.payment_method)
            if txn.payment_method else None
        ),
        'gateway_provider': txn.gateway_provider,
        'gateway_payment_id': txn.gateway_payment_id,
        'gateway_reference': txn.gateway_reference,
        'created_on': iso(txn.created_on),
        'settled_at': iso(txn.settled_at),
    }


def _refunded_totals(rows) -> dict:
    """
    How much of each purchase in `rows` has been refunded, in one query.

    A purchase stays SUCCEEDED after a partial refund and moves to REVERSED only
    when fully refunded, so the amount is what tells "partly refunded" from
    "untouched".
    """
    from portal import db

    ids = [
        r.credit_transaction_id for r in rows
        if r.transaction_type == CreditTransactionType.PURCHASE
    ]
    if not ids:
        return {}

    totals = db.session.query(
        CreditTransactions.reverses_credit_transaction_id,
        db.func.sum(CreditTransactions.amount),
    ).filter(
        CreditTransactions.reverses_credit_transaction_id.in_(ids),
        CreditTransactions.status == CreditTransactionStatus.SUCCEEDED,
    ).group_by(CreditTransactions.reverses_credit_transaction_id).all()

    return {purchase_id: to_float(total) for purchase_id, total in totals}


def transactions_payload(rows, account=None) -> list:
    purpose = (
        CreditPurpose.LABELS.get(account.purpose)
        if account is not None and account.purpose else None
    )
    refunded = _refunded_totals(rows)
    return [
        transaction_dict(
            r, purpose_label=purpose,
            refunded=refunded.get(r.credit_transaction_id),
        )
        for r in rows
    ]


def statement_dict(statement: CreditStatements, detailed: bool = False) -> dict:
    data = {
        'statement_id': statement.statement_id,
        'statement_number': statement.statement_number,
        'period_start': statement.period_start.isoformat(),
        'period_end': statement.period_end.isoformat(),
        'statement_date': statement.statement_date.isoformat(),
        'due_date': statement.due_date.isoformat(),
        'opening_balance': to_float(statement.opening_balance),
        'total_purchases': to_float(statement.total_purchases),
        'total_payments': to_float(statement.total_payments),
        'total_refunds': to_float(statement.total_refunds),
        'total_fees': to_float(statement.total_fees),
        'closing_balance': to_float(statement.closing_balance),
        'minimum_due': to_float(statement.minimum_due),
        # The bill as issued, under the name people use for it. The same figure
        # as closing_balance; both are sent so neither screen has to know that.
        'total_amount_due': to_float(statement.closing_balance),
        'credit_limit': to_float(statement.credit_limit),
        'available_credit': to_float(statement.available_credit),
        'amount_paid': to_float(statement.amount_paid),
        'amount_outstanding': to_float(statement.amount_outstanding),
        'minimum_outstanding': to_float(statement.minimum_outstanding),
        'status': statement.status,
    }
    if detailed:
        data['minimum_due_percent'] = to_float(statement.minimum_due_percent)
        data['late_fee_charged'] = statement.late_fee_charged_at is not None
        data['transactions'] = transactions_payload(
            statement.transactions.order_by(
                CreditTransactions.created_on.asc(),
                CreditTransactions.credit_transaction_id.asc(),
            ).all(),
            statement.account,
        )
    return data


def _unbilled_spend(account):
    from portal import db
    from portal.models.credit_transactions import CreditTransactionStatus

    total = db.session.query(
        db.func.coalesce(db.func.sum(CreditTransactions.amount), 0)
    ).filter(
        CreditTransactions.credit_account_id == account.credit_account_id,
        CreditTransactions.statement_id.is_(None),
        CreditTransactions.status == CreditTransactionStatus.SUCCEEDED,
        CreditTransactions.transaction_type.in_(CreditTransactionType.DEBITS),
    ).scalar()
    return total or 0


def _next_step(account) -> str:
    """
    What the holder has to do next, if anything.

    Returned by the server rather than inferred by the client from the status,
    so the sequence of screens is decided in one place and cannot drift between
    the web app and anything else that talks to this API.
    """
    return {
        CreditAccountStatus.PENDING_PURPOSE: 'DECLARE_PURPOSE',
        CreditAccountStatus.PENDING_ACTIVATION: 'ACTIVATE',
        CreditAccountStatus.BLOCKED: 'UNBLOCK',
        CreditAccountStatus.CLOSED: 'NONE',
    }.get(account.status, 'NONE')


#: HTTP status by refusal code. Derived from the code so the engine does not have
#: to know about HTTP, and so a new refusal cannot be reported as a 400 when it
#: is really a conflict or the gateway's fault.
_HTTP_STATUS = {
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.PROVIDER_ERROR: 502,
    'GATEWAY_ERROR': 502,
    'GATEWAY_TIMEOUT': 504,
}


def _engine_failure(exc: credit_engine.CreditError):
    """
    Render a CreditError.

    When the refusal was recorded - a declined purchase, a failed payment, a
    payment already in flight - the row goes back in `details`, so the client
    can show its reference and status instead of an anonymous error.
    """
    details = (
        {'transaction': transaction_dict(exc.transaction)}
        if exc.transaction is not None else None
    )
    return failure(
        exc.code, exc.message, _HTTP_STATUS.get(exc.code, 400),
        details=details, recovery=exc.recovery,
    )


def _declined(txn: CreditTransactions):
    """A replayed key whose original attempt was declined: decline it again."""
    return failure(
        txn.failure_code or 'DECLINED',
        txn.failure_reason or 'This transaction was declined.',
        _HTTP_STATUS.get(txn.failure_code, 400),
        details={'transaction': transaction_dict(txn)},
    )


# ── Application ────────────────────────────────────────────────────────────

@ns.route('/applications')
class CreditApplicationList(Resource):
    @ns.doc('list_credit_applications', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Every application this user has made, newest first."""
        user = current_user()
        rows = CreditApplications.query.filter_by(
            user_id=user.user_id
        ).order_by(CreditApplications.created_on.desc()).all()
        return success({'applications': [application_dict(r) for r in rows]})

    @ns.doc('apply_for_credit', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Apply for a credit line.

        Deliberately not behind kyc_required. An unverified applicant may apply
        and is parked in KYC_PENDING - being told "apply after verifying" when
        verification takes a day is a worse journey than being told "we have your
        application, now verify". The gate is on approval, which is where it
        matters.
        """
        args = apply_parser.parse_args()
        user = current_user()

        try:
            employment = validate_choice(
                (args['employment_type'] or '').upper(),
                EmploymentType.CHOICES, 'employment_type',
            )
            # Bounded above because a declared income in the billions is a typo
            # or a probe, and either way the offer computed from it would be
            # nonsense. Bounded below at 1 because the floor that actually
            # matters is the resulting limit, checked in the engine.
            income = validate_amount(
                args['monthly_income'], 'monthly_income',
                minimum=1, maximum=100000000,
            )
            # Zero is a real answer here - most applicants have no EMIs - but
            # validate_amount refuses anything not above zero, whatever minimum
            # it is given. So a declared zero is taken as zero before it gets
            # there; without this, "I have no EMIs" could not be submitted.
            raw_outflow = args.get('existing_emi_outflow')
            if raw_outflow in (None, '') or str(raw_outflow).strip() in ('0', '0.0', '0.00'):
                outflow = 0
            else:
                outflow = validate_amount(
                    raw_outflow, 'existing_emi_outflow',
                    minimum=0, maximum=100000000,
                )
            requested = validate_amount(
                args['requested_limit'], 'requested_limit',
                minimum=1, maximum=100000000,
            ) if args.get('requested_limit') not in (None, '') else None
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        try:
            application = credit_engine.apply(
                user=user,
                employment_type=employment,
                monthly_income=income,
                existing_emi_outflow=outflow,
                requested_limit=requested,
            )
        except credit_engine.CreditError as exc:
            return _engine_failure(exc)

        message = (
            'Application received. Complete your KYC so we can decide.'
            if application.status == ApplicationStatus.KYC_PENDING
            else 'Application received and under review.'
        )
        return success(application_dict(application), message, 201)


@ns.route('/applications/<string:application_id>')
class CreditApplicationDetail(Resource):
    @ns.doc('get_credit_application', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, application_id):
        """One application."""
        user = current_user()
        application = CreditApplications.query.filter_by(
            application_id=application_id, user_id=user.user_id,
        ).first()
        if not application:
            return failure(ErrorCode.NOT_FOUND, 'Application not found.', 404)
        return success(application_dict(application))


@ns.route('/applications/<string:application_id>/withdraw')
class WithdrawApplication(Resource):
    @ns.doc('withdraw_credit_application', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, application_id):
        """Withdraw an application before it is decided."""
        user = current_user()
        application = CreditApplications.query.filter_by(
            application_id=application_id, user_id=user.user_id,
        ).first()
        if not application:
            return failure(ErrorCode.NOT_FOUND, 'Application not found.', 404)

        try:
            credit_engine.withdraw(application)
        except credit_engine.CreditError as exc:
            return _engine_failure(exc)

        return success(application_dict(application), 'Application withdrawn.')


@ns.route('/eligibility')
class CreditEligibility(Resource):
    @ns.doc('credit_eligibility', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """
        What this user could be offered, and what stands in the way.

        Read-only and side-effect free, so the apply screen can show a real
        ceiling before anyone fills a form in. The number here is the tier cap,
        not a promise: the offer depends on declared income, which this endpoint
        has not been given.
        """
        user = current_user()
        from portal.models.users import KYCTier

        tier_cap = settings.get_decimal(
            Key.CREDIT_LIMIT_MAX_FULL_KYC if user.kyc_tier == KYCTier.FULL
            else Key.CREDIT_LIMIT_MAX_STANDARD_KYC
        )

        existing = credit_engine.account_for(user.user_id)
        open_application = credit_engine.application_for(user.user_id)

        return success({
            'can_apply': not existing and not open_application,
            'kyc_tier': user.kyc_tier,
            'kyc_required': user.kyc_tier == KYCTier.NONE,
            'max_limit_for_tier': to_float(tier_cap),
            'minimum_limit': to_float(settings.get_decimal(Key.CREDIT_LIMIT_MIN)),
            'full_kyc_required_above': to_float(
                settings.get_decimal(Key.FULL_KYC_REQUIRED_ABOVE)
            ),
            'employment_types': EmploymentType.CHOICES,
            'has_credit_line': bool(existing),
            'open_application_id': (
                open_application.application_id if open_application else None
            ),
        })


# ── The account ────────────────────────────────────────────────────────────

@ns.route('/account')
class CreditAccountDetail(Resource):
    @ns.doc('get_credit_account', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """
        The user's credit line.

        404 with a NO_CREDIT_LINE code rather than an empty 200, so the client
        can tell "you have no card" from "your card failed to load" - those
        need different screens.
        """
        user = current_user()
        account = credit_engine.account_for(user.user_id)
        if not account:
            return failure(
                'NO_CREDIT_LINE', 'You do not have a credit line yet.', 404,
                recovery='Apply for one.',
            )
        return success(account_dict(account, detailed=True))


@ns.route('/account/purpose')
class DeclarePurpose(Resource):
    @ns.doc('declare_credit_purpose', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """The purposes that may be declared, for the selection screen."""
        return success({
            'purposes': [
                {
                    'value': value,
                    'label': CreditPurpose.LABELS[value],
                    'requires_note': value == CreditPurpose.OTHER,
                }
                for value in CreditPurpose.CHOICES
            ],
        })

    @ns.doc('set_credit_purpose', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Declare what the credit is for. Mandatory before activation.
        """
        args = purpose_parser.parse_args()
        user = current_user()

        account = credit_engine.account_for(user.user_id)
        if not account:
            return failure(
                'NO_CREDIT_LINE', 'You do not have a credit line yet.', 404,
            )

        # Sanitised before it reaches the engine: this is free text that ends up
        # on an admin screen, and the one place to strip it is on the way in.
        note = sanitize_text(args.get('purpose_note') or '', max_length=200)

        try:
            credit_engine.declare_purpose(
                account, purpose=(args['purpose'] or '').upper(), note=note,
            )
        except credit_engine.CreditError as exc:
            return _engine_failure(exc)

        return success(
            account_dict(account, detailed=True),
            'Purpose recorded. You can activate your card now.',
        )


@ns.route('/account/activate')
class ActivateAccount(Resource):
    @ns.doc('activate_credit_account', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """Turn the credit line on."""
        user = current_user()
        account = credit_engine.account_for(user.user_id)
        if not account:
            return failure(
                'NO_CREDIT_LINE', 'You do not have a credit line yet.', 404,
            )

        try:
            credit_engine.activate(account)
        except credit_engine.CreditError as exc:
            return _engine_failure(exc)

        return success(
            account_dict(account, detailed=True), 'Your card is active.',
        )


@ns.route('/account/block')
class BlockAccount(Resource):
    @ns.doc('block_credit_account', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Freeze the card.

        Available to the holder without a reason, because someone who thinks
        their card is compromised should not have to explain themselves first.
        """
        args = block_parser.parse_args()
        user = current_user()
        account = credit_engine.account_for(user.user_id)
        if not account:
            return failure(
                'NO_CREDIT_LINE', 'You do not have a credit line yet.', 404,
            )

        try:
            credit_engine.block(
                account,
                reason=sanitize_text(args.get('reason') or 'Blocked by cardholder',
                                     max_length=200),
            )
        except credit_engine.CreditError as exc:
            return _engine_failure(exc)

        return success(account_dict(account, detailed=True), 'Card blocked.')


@ns.route('/account/unblock')
class UnblockAccount(Resource):
    @ns.doc('unblock_credit_account', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """Unfreeze a card the holder froze."""
        user = current_user()
        account = credit_engine.account_for(user.user_id)
        if not account:
            return failure(
                'NO_CREDIT_LINE', 'You do not have a credit line yet.', 404,
            )
        if account.status != CreditAccountStatus.BLOCKED:
            return failure(
                ErrorCode.CONFLICT, 'This card is not blocked.', 409,
            )

        try:
            credit_engine.activate(account)
        except credit_engine.CreditError as exc:
            return _engine_failure(exc)

        return success(account_dict(account, detailed=True), 'Card unblocked.')


# ── Spending ───────────────────────────────────────────────────────────────

@ns.route('/purchases')
class CreditPurchaseList(Resource):
    @ns.doc('make_credit_purchase', security='Bearer')
    @jwt_required()
    @active_user_required
    @kyc_required('MINIMUM')
    def post(self):
        """
        Spend on the credit line.

        Requires X-Idempotency-Key. A replay returns the original purchase with
        200 rather than charging twice, which is the difference between paying a
        merchant once and paying them twice.

        In development a `test_card_last4` naming a test card marks the
        transaction as a test one. That path is gated twice - here and in the
        engine - and the resulting row carries is_test, so a test spend can
        never be counted as revenue.
        """
        args = purchase_parser.parse_args()
        user = current_user()

        account = credit_engine.account_for(user.user_id)
        if not account:
            return failure(
                'NO_CREDIT_LINE', 'You do not have a credit line yet.', 404,
                recovery='Apply for one.',
            )

        try:
            key = validate_idempotency_key(idempotency_key())
            amount = validate_amount(
                args['amount'], 'amount',
                minimum=settings.get_decimal(Key.PAYMENT_MIN_AMOUNT),
            )
            merchant = sanitize_text(args['merchant_name'] or '', max_length=120)
            if len(merchant) < 2:
                raise ValidationError('Enter a merchant name.', 'merchant_name')
            category = (
                validate_choice(
                    (args['merchant_category'] or '').upper(),
                    MerchantCategory.CHOICES, 'merchant_category',
                )
                if args.get('merchant_category') else MerchantCategory.OTHER
            )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        is_test = False
        if args.get('test_card_last4'):
            if not test_cards.enabled():
                return failure(
                    ErrorCode.FORBIDDEN,
                    'Test cards are not available in this environment.', 403,
                )
            is_test = True

        try:
            record = credit_engine.purchase(
                account=account,
                amount=amount,
                merchant_name=merchant,
                merchant_category=category,
                description=sanitize_text(args.get('description') or '',
                                          max_length=200),
                idempotency_key=key,
                is_test=is_test,
            )
        except credit_engine.DuplicateSpend as exc:
            if exc.transaction.status == CreditTransactionStatus.FAILED:
                return _declined(exc.transaction)
            fresh = credit_engine.account_for(user.user_id)
            return success(
                {
                    'transaction': transactions_payload([exc.transaction], fresh)[0],
                    'account': account_dict(fresh),
                },
                'This purchase was already recorded.',
            )
        except credit_engine.CreditError as exc:
            return _engine_failure(exc)

        return success(
            {
                'transaction': transactions_payload([record], record.account)[0],
                'account': account_dict(record.account),
            },
            'Purchase successful.',
            201,
        )


@ns.route('/transactions')
class CreditTransactionList(Resource):
    @ns.doc('list_credit_transactions', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Everything that has happened on the credit line, newest first."""
        args = list_parser.parse_args()
        user = current_user()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        account = credit_engine.account_for(user.user_id)
        if not account:
            return paginated([], page, per_page, 0)

        query = CreditTransactions.query.filter_by(
            credit_account_id=account.credit_account_id,
        )
        if args.get('type'):
            requested = args['type'].upper()
            if requested not in CreditTransactionType.CHOICES:
                return failure(
                    ErrorCode.VALIDATION_ERROR,
                    f'Unknown transaction type: {requested}.', 400,
                )
            query = query.filter(CreditTransactions.transaction_type == requested)
        if args.get('status'):
            wanted = args['status'].upper()
            if wanted not in CreditTransactionStatus.CHOICES:
                return failure(
                    ErrorCode.VALIDATION_ERROR,
                    f'Unknown transaction status: {wanted}.', 400,
                )
            query = query.filter(CreditTransactions.status == wanted)

        # The id is a tiebreaker, not a sort key: a UUID says nothing about
        # time. It is here because pagination needs a *total* order - two rows
        # that compare equal can otherwise swap between the query for page 1 and
        # the query for page 2, showing one row twice and hiding another.
        pagination = query.order_by(
            CreditTransactions.created_on.desc(),
            CreditTransactions.credit_transaction_id.desc(),
        ).paginate(page=page, per_page=per_page, error_out=False)

        return paginated(
            transactions_payload(pagination.items, account),
            page, per_page, pagination.total,
        )


@ns.route('/transactions/<string:credit_transaction_id>')
class CreditTransactionDetail(Resource):
    @ns.doc('get_credit_transaction', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, credit_transaction_id):
        """One movement on the credit line."""
        user = current_user()
        txn = CreditTransactions.query.filter_by(
            credit_transaction_id=credit_transaction_id, user_id=user.user_id,
        ).first()
        if not txn:
            return failure(ErrorCode.NOT_FOUND, 'Transaction not found.', 404)
        return success(transactions_payload([txn], txn.account)[0])


# ── Statements and bill payment ────────────────────────────────────────────

@ns.route('/statements')
class CreditStatementList(Resource):
    @ns.doc('list_credit_statements', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Statement history, newest first."""
        args = list_parser.parse_args()
        user = current_user()
        page, per_page = validate_pagination(args['page'], args['per_page'])

        account = credit_engine.account_for(user.user_id)
        if not account:
            return paginated([], page, per_page, 0)

        pagination = CreditStatements.query.filter_by(
            credit_account_id=account.credit_account_id,
        ).order_by(CreditStatements.period_end.desc()).paginate(
            page=page, per_page=per_page, error_out=False,
        )

        return paginated(
            [statement_dict(s) for s in pagination.items],
            page, per_page, pagination.total,
        )


@ns.route('/statements/current')
class CurrentStatement(Resource):
    @ns.doc('get_current_statement', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """
        What is owed right now, and what is still unbilled.

        Two different numbers, both of which people ask for: the latest issued
        statement is what has to be paid by a date, and the unbilled spend is
        what will land on the next one. Returning them together is what lets one
        screen answer both without guessing.
        """
        user = current_user()
        account = credit_engine.account_for(user.user_id)
        if not account:
            return failure(
                'NO_CREDIT_LINE', 'You do not have a credit line yet.', 404,
            )

        latest = CreditStatements.query.filter_by(
            credit_account_id=account.credit_account_id,
        ).order_by(CreditStatements.period_end.desc()).first()
        pending = CreditTransactions.query.filter_by(
            credit_account_id=account.credit_account_id,
            transaction_type=CreditTransactionType.PAYMENT,
            status=CreditTransactionStatus.PROCESSING,
        ).first()

        return success({
            'account': account_dict(account),
            'latest_statement': (
                statement_dict(latest, detailed=True) if latest else None
            ),
            'unbilled_spend': to_float(_unbilled_spend(account)),
            'total_outstanding': to_float(account.current_outstanding),
            'payment_methods': BillPaymentMethod.CHOICES,
            # A payment still waiting on the gateway, so the pay screen can pick
            # it up again instead of offering a second one.
            'pending_payment': (
                transaction_dict(pending) if pending is not None else None
            ),
        })


@ns.route('/statements/<string:statement_id>')
class CreditStatementDetail(Resource):
    @ns.doc('get_credit_statement', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, statement_id):
        """One statement, with the transactions it billed."""
        user = current_user()
        statement = CreditStatements.query.filter_by(
            statement_id=statement_id, user_id=user.user_id,
        ).first()
        if not statement:
            return failure(ErrorCode.NOT_FOUND, 'Statement not found.', 404)
        return success(statement_dict(statement, detailed=True))


def _payment_for(user, credit_transaction_id):
    return CreditTransactions.query.filter_by(
        credit_transaction_id=credit_transaction_id,
        user_id=user.user_id,
        transaction_type=CreditTransactionType.PAYMENT,
    ).first()


def _payment_response(record, user, status_code=200):
    """
    A bill payment in whatever state it is in, and the account as it now stands.

    `credit_restored` is non-zero only for a SUCCEEDED payment, because that is
    the only state in which any credit was restored.
    """
    fresh = credit_engine.account_for(user.user_id)
    succeeded = record.status == CreditTransactionStatus.SUCCEEDED

    if succeeded:
        message = (
            f'Payment received. Rs. {to_float(record.amount):,.2f} of credit is '
            f'available again.'
        )
    elif record.status == CreditTransactionStatus.FAILED and record.failure_reason:
        message = record.failure_reason
    else:
        message = _PAYMENT_OUTCOME.get(record.status, 'Payment status updated.')

    payload = {
        'transaction': transaction_dict(record),
        'account': account_dict(fresh, detailed=True) if fresh else None,
        'credit_restored': to_float(record.amount) if succeeded else 0.0,
    }
    checkout = getattr(record, 'checkout', None)
    if checkout is not None:
        payload['checkout'] = checkout
    return success(payload, message, status_code)


@ns.route('/payments/methods')
class BillPaymentMethods(Resource):
    @ns.doc('credit_bill_payment_methods', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """
        How a card bill may be paid, and which rail each way would use.

        The prohibition is stated rather than left as an absence, so the screen
        can say why a credit card is not on the list. `sandbox` tells the client
        a payment will be simulated - never true in production.
        """
        user = current_user()
        providers = {
            method: credit_engine.bill_payment_provider(method)
            for method in BillPaymentMethod.CHOICES
        }
        return success({
            'permitted': [
                {'mode': BillPaymentMethod.UPI_INTENT, 'label': 'UPI',
                 'description': 'Google Pay, PhonePe, Paytm or any UPI app',
                 'provider': providers[BillPaymentMethod.UPI_INTENT]},
                {'mode': BillPaymentMethod.UPI_COLLECT, 'label': 'UPI ID',
                 'description': 'Get a collect request on your UPI ID',
                 'provider': providers[BillPaymentMethod.UPI_COLLECT]},
                {'mode': BillPaymentMethod.NETBANKING, 'label': 'Net Banking',
                 'description': 'All major Indian banks',
                 'provider': providers[BillPaymentMethod.NETBANKING]},
                {'mode': BillPaymentMethod.DEBIT_CARD, 'label': 'Debit Card',
                 'description': 'RuPay, Visa or Mastercard debit',
                 'provider': providers[BillPaymentMethod.DEBIT_CARD]},
            ],
            'prohibited': [{
                'mode': 'CREDIT_CARD',
                'label': 'Credit card',
                'reason': 'A credit card bill cannot be paid from another '
                          'credit line.',
            }],
            'minimum_amount': to_float(
                settings.get_decimal(Key.PAYMENT_MIN_AMOUNT)
            ),
            'upi': {
                'provider': adapters.upi_provider(),
                'checkout_key': adapters.upi_public_key(),
                'apps': adapters.UPI_APPS,
            },
            'sandbox': (
                credit_engine.simulator_allowed()
                and 'SANDBOX' in providers.values()
            ),
            'prefill': {
                'name': user.full_name or '',
                'contact': user.phone or '',
                'email': user.email or '',
            },
        })


@ns.route('/payments')
class CreditBillPayment(Resource):
    @ns.doc('pay_credit_bill', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Start paying the card bill.

        Opens a gateway order and returns what the client needs to take the
        payer through checkout. No credit is restored here: the payment stays
        PROCESSING until /verify, the webhook or the poller hears from the
        gateway that the money arrived.

        Requires X-Idempotency-Key. Paying twice by accident is worse than
        spending twice - the money has actually left the payer's account - so a
        replay returns the original payment rather than opening a second order.
        """
        args = pay_parser.parse_args()
        user = current_user()

        account = credit_engine.account_for(user.user_id)
        if not account:
            return failure(
                'NO_CREDIT_LINE', 'You do not have a credit line yet.', 404,
            )

        raw_method = (args.get('payment_method') or 'UPI_INTENT').upper()
        method = _METHOD_ALIASES.get(raw_method, raw_method)
        if method not in BillPaymentMethod.CHOICES:
            return failure(
                ErrorCode.INSTRUMENT_NOT_PERMITTED,
                'A card bill can be paid by UPI, net banking or a debit card.',
                400,
                recovery='Choose UPI, Net Banking or Debit Card.',
            )

        try:
            key = validate_idempotency_key(idempotency_key())
            amount = validate_amount(
                args['amount'], 'amount',
                minimum=settings.get_decimal(Key.PAYMENT_MIN_AMOUNT),
            )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        statement = None
        if args.get('statement_id'):
            statement = CreditStatements.query.filter_by(
                statement_id=args['statement_id'], user_id=user.user_id,
            ).first()
            if not statement:
                return failure(ErrorCode.NOT_FOUND, 'Statement not found.', 404)

        try:
            record = credit_engine.open_bill_payment(
                account=account,
                user=user,
                amount=amount,
                method=method,
                idempotency_key=key,
                statement=statement,
                sandbox_outcome=(
                    args.get('sandbox_outcome')
                    if credit_engine.simulator_allowed() else None
                ),
            )
        except credit_engine.DuplicateSpend as exc:
            return _payment_response(exc.transaction, user)
        except credit_engine.CreditError as exc:
            return _engine_failure(exc)

        return _payment_response(record, user, 201)


@ns.route('/payments/<string:credit_transaction_id>/verify')
class VerifyBillPayment(Resource):
    @ns.doc('verify_credit_bill_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, credit_transaction_id):
        """
        Settle a payment from the gateway's own record of it.

        Called when the payer comes back from checkout, with whatever Checkout
        handed the browser, or with nothing at all simply to ask again. None of
        it is believed: the signature is verified, the payment is re-read from
        the gateway, and only a captured payment restores credit. A client that
        posts a made-up payment id gets an unpaid bill, not a cleared one.
        """
        args = verify_parser.parse_args()
        user = current_user()

        record = _payment_for(user, credit_transaction_id)
        if not record:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        claimed_order = args.get('razorpay_order_id')
        if (
            claimed_order
            and record.gateway_order_id
            and claimed_order != record.gateway_order_id
        ):
            logger.error(
                f'[credit] verify for {credit_transaction_id} carried order '
                f'{claimed_order}, but the payment is against '
                f'{record.gateway_order_id}'
            )
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'That payment belongs to a different order.', 400,
            )

        if record.status == CreditTransactionStatus.PROCESSING:
            try:
                record = credit_engine.settle_bill_payment(
                    record,
                    gateway_payment_id=args.get('razorpay_payment_id'),
                    signature=args.get('razorpay_signature'),
                )
            except Exception as exc:     # noqa: BLE001 - reported, and polled later
                logger.exception(
                    f'[credit] verify failed for {credit_transaction_id}: {exc}'
                )
                return failure(
                    ErrorCode.INTERNAL_ERROR,
                    'We could not confirm this payment yet. If money left your '
                    'account it will be credited automatically - do not pay '
                    'again.',
                    500,
                )

        return _payment_response(record, user)


@ns.route('/payments/<string:credit_transaction_id>/cancel')
class CancelBillPayment(Resource):
    @ns.doc('cancel_credit_bill_payment', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, credit_transaction_id):
        """
        Abandon a payment the payer backed out of.

        Asks the gateway first. A payment that went through anyway - the sheet
        closed after authorising - is settled rather than cancelled, and one
        still live at the bank stays processing.
        """
        user = current_user()
        record = _payment_for(user, credit_transaction_id)
        if not record:
            return failure(ErrorCode.NOT_FOUND, 'Payment not found.', 404)

        if record.status == CreditTransactionStatus.PROCESSING:
            try:
                record = credit_engine.cancel_bill_payment(record)
            except Exception as exc:     # noqa: BLE001
                logger.exception(
                    f'[credit] cancel failed for {credit_transaction_id}: {exc}'
                )
                return failure(
                    ErrorCode.INTERNAL_ERROR,
                    'We could not cancel this payment right now. Please try '
                    'again in a moment.',
                    500,
                )

        return _payment_response(record, user)
