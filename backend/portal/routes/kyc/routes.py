"""
KYC submission and tiering (PRD FR-012, section 18).

Two tiers:
  MINIMUM  mobile + PAN, unlocks the app
  FULL     Aadhaar eKYC, required before transfers above 10,000 INR

No KYC vendor is signed yet (PRD open decision 4), so submissions land in an
admin review queue. The tier is granted on approval, never on submission.
"""

import os
import uuid

from flask import current_app, request
from flask_jwt_extended import jwt_required
from flask_restx import Resource, reqparse
from werkzeug.utils import secure_filename

from portal import db
from portal.helpers import audit, settings
from portal.helpers.encryption import encrypt
from portal.helpers.helpers import ErrorCode, failure, iso, success
from portal.helpers.jwt import active_user_required, current_user
from portal.helpers.settings import Key
from portal.helpers.validators import (
    ValidationError, sanitize_text, validate_aadhaar, validate_pan,
)
from portal.models.base import utcnow
from portal.models.kyc_verifications import KYCStatus, KYCVerifications
from portal.models.user_profiles import UserProfiles
from portal.models.users import KYCTier

from . import logger, ns

submit_parser = reqparse.RequestParser()
submit_parser.add_argument('pan_number', type=str, required=True, location='form')
submit_parser.add_argument('full_name', type=str, required=True, location='form')
submit_parser.add_argument('aadhaar_number', type=str, required=False, location='form')
submit_parser.add_argument('requested_tier', type=str, required=False, location='form',
                           default=KYCTier.MINIMUM)

ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}


def _save_document(upload, user_id: str, label: str) -> str:
    """
    Persist a KYC document under a random filename.

    The uploaded name is attacker-controlled and may carry a path or a
    misleading extension, so only the validated extension is reused.
    """
    if not upload or not upload.filename:
        return None

    extension = os.path.splitext(secure_filename(upload.filename))[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            'Upload a PDF or an image (JPG, PNG).', label
        )

    folder = os.path.join(
        current_app.config['UPLOAD_FOLDER'], 'kyc', str(user_id)
    )
    os.makedirs(folder, exist_ok=True)

    filename = f'{label}_{uuid.uuid4().hex}{extension}'
    upload.save(os.path.join(folder, filename))

    return os.path.join('kyc', str(user_id), filename).replace('\\', '/')


def kyc_dict(kyc: KYCVerifications, user) -> dict:
    return {
        'kyc_id': kyc.kyc_id if kyc else None,
        'kyc_status': kyc.kyc_status if kyc else KYCStatus.NOT_STARTED,
        'kyc_tier': user.kyc_tier,
        'requested_tier': kyc.requested_tier if kyc else None,
        'verified_legal_name': kyc.verified_legal_name if kyc else None,
        'submitted_at': iso(kyc.submitted_at) if kyc else None,
        'reviewed_at': iso(kyc.reviewed_at) if kyc else None,
        'rejection_reason': kyc.rejection_reason if kyc else None,
        'has_pan_document': bool(kyc and kyc.pan_document_path),
        'has_aadhaar_document': bool(kyc and kyc.aadhaar_document_path),
    }


@ns.route('/status')
class KYCStatusResource(Resource):
    @ns.doc('get_kyc_status', security='Bearer')
    @jwt_required()
    @active_user_required
    def get(self):
        """Current KYC state and what it unlocks."""
        user = current_user()
        kyc = user.kyc_verification

        full_kyc_above = settings.get_decimal(Key.FULL_KYC_REQUIRED_ABOVE)
        standard_max = settings.get_decimal(Key.TRANSFER_MAX_SINGLE_STANDARD_KYC)
        full_max = settings.get_decimal(Key.TRANSFER_MAX_SINGLE_FULL_KYC)

        data = kyc_dict(kyc, user)
        data['capabilities'] = {
            'can_link_cards': user.kyc_tier != KYCTier.NONE,
            'can_transfer': user.kyc_tier != KYCTier.NONE,
            'transfer_limit': float(
                full_max if user.kyc_tier == KYCTier.FULL else standard_max
            ),
            'full_kyc_required_above': float(full_kyc_above),
            'can_upgrade': user.kyc_tier != KYCTier.FULL,
        }
        data['tiers'] = [
            {
                'tier': KYCTier.MINIMUM,
                'label': 'Basic KYC',
                'requirements': ['Mobile number', 'PAN card'],
                'transfer_limit': float(standard_max),
                'active': user.kyc_tier == KYCTier.MINIMUM,
            },
            {
                'tier': KYCTier.FULL,
                'label': 'Full KYC',
                'requirements': ['Mobile number', 'PAN card', 'Aadhaar'],
                'transfer_limit': float(full_max),
                'active': user.kyc_tier == KYCTier.FULL,
            },
        ]

        return success(data)


@ns.route('/submit')
class SubmitKYC(Resource):
    @ns.doc('submit_kyc', security='Bearer')
    @jwt_required()
    @active_user_required
    def post(self):
        """
        Submit KYC documents for review.

        Multipart: pan_number, full_name, optional aadhaar_number, plus
        pan_document / aadhaar_document / selfie files.
        """
        args = submit_parser.parse_args()
        user = current_user()

        kyc = user.kyc_verification

        if kyc and kyc.kyc_status == KYCStatus.APPROVED:
            if args.get('requested_tier') != KYCTier.FULL or user.kyc_tier == KYCTier.FULL:
                return failure(
                    ErrorCode.CONFLICT, 'Your KYC is already verified.', 409
                )

        if kyc and kyc.kyc_status in (KYCStatus.PENDING, KYCStatus.UNDER_REVIEW):
            return failure(
                ErrorCode.CONFLICT,
                'Your KYC is already under review. We will notify you once it '
                'is processed.',
                409,
            )

        try:
            pan = validate_pan(args['pan_number'])
            legal_name = sanitize_text(args['full_name'], 200)
            if not legal_name:
                raise ValidationError('Enter your full name as per PAN.', 'full_name')

            requested_tier = (
                KYCTier.FULL if args.get('requested_tier') == KYCTier.FULL
                else KYCTier.MINIMUM
            )

            aadhaar = None
            if args.get('aadhaar_number'):
                aadhaar = validate_aadhaar(args['aadhaar_number'])
            elif requested_tier == KYCTier.FULL:
                raise ValidationError(
                    'Aadhaar is required for full KYC verification.',
                    'aadhaar_number',
                )

            pan_path = _save_document(
                request.files.get('pan_document'), user.user_id, 'pan'
            )
            aadhaar_path = _save_document(
                request.files.get('aadhaar_document'), user.user_id, 'aadhaar'
            )
            selfie_path = _save_document(
                request.files.get('selfie'), user.user_id, 'selfie'
            )
        except ValidationError as exc:
            return failure(ErrorCode.VALIDATION_ERROR, exc.message, 400,
                           details={'field': exc.field})

        if not pan_path and not (kyc and kyc.pan_document_path):
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'Please upload a photo of your PAN card.',
                400,
                details={'field': 'pan_document'},
            )

        if requested_tier == KYCTier.FULL and not aadhaar_path and not (
            kyc and kyc.aadhaar_document_path
        ):
            return failure(
                ErrorCode.VALIDATION_ERROR,
                'Please upload a photo of your Aadhaar card.',
                400,
                details={'field': 'aadhaar_document'},
            )

        if not kyc:
            kyc = KYCVerifications(user_id=user.user_id)
            db.session.add(kyc)

        kyc.kyc_status = KYCStatus.PENDING
        kyc.requested_tier = requested_tier
        kyc.verified_legal_name = legal_name
        kyc.submitted_at = utcnow()
        kyc.rejection_reason = None
        if pan_path:
            kyc.pan_document_path = pan_path
        if aadhaar_path:
            kyc.aadhaar_document_path = aadhaar_path
        if selfie_path:
            kyc.selfie_path = selfie_path

        profile = user.profile
        if not profile:
            profile = UserProfiles(user_id=user.user_id)
            db.session.add(profile)

        # Encrypted at rest; only the last four digits are readable, which is
        # all the UI and a support agent ever need.
        profile.pan_number_enc = encrypt(pan)
        profile.pan_last4 = pan[-4:]
        if aadhaar:
            profile.aadhaar_last4 = aadhaar[-4:]

        if not user.full_name:
            user.full_name = legal_name

        db.session.commit()

        audit.record(
            action='KYC_SUBMITTED',
            entity_type='KYCVerifications',
            entity_id=kyc.kyc_id,
            actor_user_id=str(user.user_id),
            after={'tier': requested_tier, 'pan_last4': profile.pan_last4},
        )

        return success(
            kyc_dict(kyc, user),
            'KYC submitted successfully. Verification usually completes within '
            '24 hours.',
            201,
        )
