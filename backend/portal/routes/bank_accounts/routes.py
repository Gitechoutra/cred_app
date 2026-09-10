"""
Bank account linking and penny-drop verification (PRD FR-005).

The compliance control this module exists to enforce: money may only be paid out
to an account the sender is proven to own. CashU sends 1 INR, reads back the
name the bank holds in its core banking system, and compares it to the user's
KYC legal name. Below the confidence threshold the account is held for review
rather than accepted, because a third-party payout is a PMLA violation.
"""

from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse

from portal import db
from portal.helpers import adapters, audit, name_match
from portal.helpers.encryption import blind_index, decrypt, encrypt
from portal.helpers.helpers import ErrorCode, failure, iso, success, to_float
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.validators import (
    ValidationError, sanitize_text, validate_account_number, validate_choice,
    validate_ifsc,
)
from portal.models.bank_accounts import (
    AccountType, BankAccounts, PennyDropStatus,
)
from portal.models.base import utcnow
from portal.models.notifications import NotificationEvent
from portal.models.penny_drop_verifications import PennyDropVerifications

from . import logger, ns

add_parser = reqparse.RequestParser()
add_parser.add_argument('account_number', type=str, required=True, location='json')
add_parser.add_argument('confirm_account_number', type=str, required=True, location='json')
add_parser.add_argument('ifsc_code', type=str, required=True, location='json')
add_parser.add_argument('account_type', type=str, required=False, location='json',
                        default=AccountType.SAVINGS)
add_parser.add_argument('account_holder_name', type=str, required=False, location='json')
add_parser.add_argument('is_primary', type=bool, required=False, location='json',
                        default=False)


def account_dict(account: BankAccounts) -> dict:
    return {
        'bank_account_id': account.bank_account_id,
        'masked_account': account.masked_account(),
        'account_last4': account.account_last4,
        'ifsc_code': account.ifsc_code,
        'bank_name': account.bank_name,
        'branch_name': account.branch_name,
        'account_type': account.account_type,
        'account_holder_name': account.account_holder_name,
        'verified_cbs_name': account.verified_cbs_name,
        'name_match_score': to_float(account.name_match_score),
        'penny_drop_status': account.penny_drop_status,
        'is_payout_eligible': account.is_payout_eligible,
        'is_primary': account.is_primary,
        'verified_at': iso(account.verified_at),
        'created_on': iso(account.created_on),
    }


@ns.route('')
class BankAccountList(Resource):
    @ns.doc('list_bank_accounts', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Bank accounts for the signed-in user."""
        user = current_user()

        accounts = BankAccounts.query.filter(
            BankAccounts.user_id == user.user_id,
            BankAccounts.deleted_at.is_(None),
        ).order_by(
            BankAccounts.is_primary.desc(), BankAccounts.created_on.asc()
        ).all()

        return success({
            'accounts': [account_dict(a) for a in accounts],
            'verified_count': sum(1 for a in accounts if a.is_payout_eligible),
            'count': len(accounts),
        })

    @ns.doc('add_bank_account', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Add a bank account and run penny-drop verification.

        The account number is entered twice (PRD FR-005) because a typo here
        does not fail loudly - it sends money to a real stranger's account.
        """
        args = add_parser.parse_args()
        user = current_user()

        try:
            account_number = validate_account_number(args['account_number'])
            confirm = validate_account_number(args['confirm_account_number'])
            ifsc = validate_ifsc(args['ifsc_code'])
            account_type = validate_choice(
                args.get('account_type') or AccountType.SAVINGS,
                AccountType.CHOICES,
                'account_type',
            )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        if account_number != confirm:
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'The account numbers do not match. Please re-enter them.',
                400,
                details={'field': 'confirm_account_number'},
            )

        # Blind index lets us find a duplicate without decrypting every row.
        fingerprint = blind_index(account_number)
        duplicate = BankAccounts.query.filter_by(
            user_id=user.user_id,
            account_number_hash=fingerprint,
            deleted_at=None,
        ).first()
        if duplicate:
            return failure(
                ErrorCode.CONFLICT, 'This bank account is already linked.', 409
            )

        ifsc_details = adapters.lookup_ifsc(ifsc)
        if not ifsc_details.get('ok'):
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'We could not verify this IFSC code. Please check and try again.',
                400,
                details={'field': 'ifsc_code'},
            )

        account = BankAccounts(
            user_id=user.user_id,
            account_number_enc=encrypt(account_number),
            account_number_hash=fingerprint,
            account_last4=account_number[-4:],
            ifsc_code=ifsc,
            bank_name=ifsc_details.get('bank_name'),
            branch_name=ifsc_details.get('branch'),
            account_type=account_type,
            account_holder_name=sanitize_text(
                args.get('account_holder_name') or user.full_name, 200
            ),
            penny_drop_status=PennyDropStatus.IN_PROGRESS,
        )
        db.session.add(account)
        db.session.flush()

        result = _run_penny_drop(user, account, account_number)

        if args.get('is_primary') and account.is_payout_eligible:
            _set_primary(user, account)

        db.session.commit()

        audit.record(
            action='BANK_ACCOUNT_ADDED',
            entity_type='BankAccounts',
            entity_id=account.bank_account_id,
            actor_user_id=str(user.user_id),
            after={
                'bank': account.bank_name,
                'masked': account.masked_account(),
                'status': account.penny_drop_status,
            },
        )

        payload = account_dict(account)
        payload['verification'] = result

        if account.penny_drop_status == PennyDropStatus.VERIFIED:
            return success(payload, 'Bank account verified successfully.', 201)

        if account.penny_drop_status == PennyDropStatus.NAME_MISMATCH:
            return success(
                payload,
                'The bank account name does not match your registered legal name. '
                'Your account is under review.',
                201,
            )

        if account.penny_drop_status == PennyDropStatus.MANUAL_REVIEW_KYC:
            return success(
                payload,
                'The bank account name does not match your registered legal name. '
                'This account needs manual verification before it can receive '
                'transfers.',
                201,
            )

        return success(payload, 'Bank account added but could not be verified.', 201)


def _run_penny_drop(user, account: BankAccounts, account_number: str) -> dict:
    """
    Dispatch the 1 INR verification and score the returned name.

    The KYC legal name is preferred over the self-entered name: comparing what
    the bank says against what the user typed would prove nothing, since the
    user controls both sides.
    """
    kyc = user.kyc_verification
    kyc_name = (
        (kyc.verified_legal_name if kyc else None)
        or user.full_name
        or account.account_holder_name
        or ''
    )

    outcome = adapters.penny_drop(
        verification_id=f'VRF_{account.bank_account_id.replace("-", "")[:24]}',
        account_number=account_number,
        ifsc=account.ifsc_code,
        expected_name=kyc_name,
        phone=user.phone,
    )

    if not outcome.get('ok'):
        account.penny_drop_status = PennyDropStatus.FAILED
        db.session.add(PennyDropVerifications(
            bank_account_id=account.bank_account_id,
            user_id=user.user_id,
            provider='CASHFREE',
            result=PennyDropStatus.FAILED,
            kyc_name_compared=kyc_name,
            failure_reason=outcome.get('error'),
        ))
        return {
            'status': PennyDropStatus.FAILED,
            'reason': outcome.get('error', 'Verification could not be completed.'),
        }

    if not outcome.get('account_valid'):
        account.penny_drop_status = PennyDropStatus.FAILED
        db.session.add(PennyDropVerifications(
            bank_account_id=account.bank_account_id,
            user_id=user.user_id,
            provider='CASHFREE',
            result=PennyDropStatus.FAILED,
            kyc_name_compared=kyc_name,
            failure_reason='Account number or IFSC is invalid.',
        ))
        return {
            'status': PennyDropStatus.FAILED,
            'reason': 'Invalid account number or IFSC code.',
        }

    cbs_name = outcome.get('name_at_bank') or ''
    evaluation = name_match.evaluate(cbs_name, kyc_name)

    account.verified_cbs_name = cbs_name
    account.name_match_score = evaluation['score']
    account.penny_drop_status = evaluation['status']
    account.penny_drop_reference = outcome.get('provider_reference')

    if evaluation['status'] == PennyDropStatus.VERIFIED:
        account.verified_at = utcnow()
        audit.emit(
            'BankAccountVerifiedEvent',
            aggregate_type='BankAccounts',
            aggregate_id=account.bank_account_id,
            user_id=str(user.user_id),
            payload={
                'event': NotificationEvent.BANK_VERIFIED,
                'account': account.account_last4,
            },
        )

    db.session.add(PennyDropVerifications(
        bank_account_id=account.bank_account_id,
        user_id=user.user_id,
        provider='CASHFREE',
        provider_reference=outcome.get('provider_reference'),
        imps_utr=outcome.get('utr'),
        cbs_name_returned=cbs_name,
        kyc_name_compared=kyc_name,
        similarity_score=evaluation['score'],
        result=evaluation['status'],
        failure_reason=(
            None if evaluation['status'] == PennyDropStatus.VERIFIED
            else evaluation['reason']
        ),
    ))

    return {
        'status': evaluation['status'],
        'score': evaluation['score'],
        'reason': evaluation['reason'],
        'utr': outcome.get('utr'),
    }


def _set_primary(user, account: BankAccounts):
    BankAccounts.query.filter_by(user_id=user.user_id).update({'is_primary': False})
    account.is_primary = True


@ns.route('/<string:bank_account_id>')
class BankAccountDetail(Resource):
    @ns.doc('get_bank_account', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self, bank_account_id):
        user = current_user()
        account = BankAccounts.query.filter_by(
            bank_account_id=bank_account_id, user_id=user.user_id, deleted_at=None
        ).first()

        if not account:
            return failure(ErrorCode.NOT_FOUND, 'Bank account not found.', 404)

        verifications = PennyDropVerifications.query.filter_by(
            bank_account_id=account.bank_account_id
        ).order_by(PennyDropVerifications.created_on.desc()).limit(5).all()

        data = account_dict(account)
        data['verification_history'] = [{
            'verification_id': v.verification_id,
            'result': v.result,
            'score': to_float(v.similarity_score),
            'cbs_name': v.cbs_name_returned,
            'utr': v.imps_utr,
            'created_on': iso(v.created_on),
        } for v in verifications]

        return success(data)

    @ns.doc('remove_bank_account', security='Bearer')
    @jwt_required()
    @active_user_required
    def delete(self, bank_account_id):
        """Soft-delete an account, refusing while a payout depends on it."""
        user = current_user()
        account = BankAccounts.query.filter_by(
            bank_account_id=bank_account_id, user_id=user.user_id, deleted_at=None
        ).first()

        if not account:
            return failure(ErrorCode.NOT_FOUND, 'Bank account not found.', 404)

        from portal.models.transfers import TransferStatus, Transfers

        in_flight = Transfers.query.filter(
            Transfers.bank_account_id == account.bank_account_id,
            Transfers.status.notin_(TransferStatus.TERMINAL),
        ).count()
        if in_flight:
            return failure(
                ErrorCode.CONFLICT,
                'A transfer to this account is in progress. Please wait for it '
                'to complete.',
                409,
            )

        from portal.models.auto_pay_mandates import AutoPayMandates, MandateStatus

        active_mandates = AutoPayMandates.query.filter(
            AutoPayMandates.bank_account_id == account.bank_account_id,
            AutoPayMandates.status.in_(
                [MandateStatus.ACTIVE, MandateStatus.PENDING_AFA]
            ),
        ).count()
        if active_mandates:
            return failure(
                ErrorCode.CONFLICT,
                'An auto-pay mandate uses this account. Please reassign the '
                'mandate before removing it.',
                409,
            )

        account.deleted_at = utcnow()
        account.is_active = False
        account.is_primary = False
        db.session.commit()

        audit.record(
            action='BANK_ACCOUNT_REMOVED',
            entity_type='BankAccounts',
            entity_id=account.bank_account_id,
            actor_user_id=str(user.user_id),
        )

        return success(None, 'Bank account removed.')


@ns.route('/<string:bank_account_id>/verify')
class RetryVerification(Resource):
    @ns.doc('retry_penny_drop', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, bank_account_id):
        """
        Re-run penny-drop verification.

        Useful after a KYC name is corrected - the account itself was fine, the
        name on file was not.
        """
        user = current_user()
        account = BankAccounts.query.filter_by(
            bank_account_id=bank_account_id, user_id=user.user_id, deleted_at=None
        ).first()

        if not account:
            return failure(ErrorCode.NOT_FOUND, 'Bank account not found.', 404)

        if account.penny_drop_status == PennyDropStatus.VERIFIED:
            return success(account_dict(account), 'This account is already verified.')

        try:
            account_number = decrypt(account.account_number_enc)
        except Exception as exc:
            logger.error(f'Cannot decrypt account {account.bank_account_id}: {exc}')
            return failure(
                ErrorCode.INTERNAL_ERROR,
                'We could not read this account. Please remove and re-add it.',
                500,
            )

        result = _run_penny_drop(user, account, account_number)
        db.session.commit()

        payload = account_dict(account)
        payload['verification'] = result
        return success(payload, result.get('reason', 'Verification complete.'))


@ns.route('/<string:bank_account_id>/primary')
class SetPrimary(Resource):
    @ns.doc('set_primary_account', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self, bank_account_id):
        """Make this the default payout destination."""
        user = current_user()
        account = BankAccounts.query.filter_by(
            bank_account_id=bank_account_id, user_id=user.user_id, deleted_at=None
        ).first()

        if not account:
            return failure(ErrorCode.NOT_FOUND, 'Bank account not found.', 404)

        if not account.is_payout_eligible:
            return failure(
                ErrorCode.ACCOUNT_NOT_VERIFIED,
                'Only a verified account can be set as primary.',
                400,
            )

        _set_primary(user, account)
        db.session.commit()

        return success(account_dict(account), 'Primary account updated.')


@ns.route('/ifsc/<string:ifsc_code>')
class IFSCLookup(Resource):
    @ns.doc('lookup_ifsc', security='Bearer')
    @jwt_required()
    def get(self, ifsc_code):
        """Resolve an IFSC to bank and branch as the user types it."""
        try:
            ifsc = validate_ifsc(ifsc_code)
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400)

        result = adapters.lookup_ifsc(ifsc)
        if not result.get('ok'):
            return failure(ErrorCode.NOT_FOUND, 'IFSC code not found.', 404)

        return success({
            'ifsc_code': ifsc,
            'bank_name': result.get('bank_name'),
            'branch': result.get('branch'),
            'city': result.get('city'),
            'state': result.get('state'),
        })
