from app import app
from portal import db
from portal.models.credit_applications import CreditApplications, ApplicationStatus
from portal.models.kyc_verifications import KYCStatus
from portal.helpers import credit_engine

with app.app_context():
    # Find applications that are stuck in KYC_PENDING but their user's KYC is APPROVED
    apps = CreditApplications.query.filter_by(status=ApplicationStatus.KYC_PENDING).all()
    for application in apps:
        user = application.applicant
        if user and user.kyc_verification and user.kyc_verification.kyc_status == KYCStatus.APPROVED:
            print(f"Fixing application {application.application_id}...")
            # Re-run the KYC completed logic
            application.status = ApplicationStatus.UNDER_REVIEW
            application.kyc_verified_at = user.kyc_verification.reviewed_at
            
            # Fetch credit score and reassess just like credit_engine.kyc_completed does
            credit_engine._fetch_credit_score(application, user)
            credit_engine._reassess(application, user)
            db.session.commit()
            print("Fixed!")
