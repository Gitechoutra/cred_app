from app import app
from portal.models.credit_applications import CreditApplications

with app.app_context():
    apps = CreditApplications.query.all()
    if not apps:
        print("No applications found.")
    for app_item in apps:
        print(f"App ID: {app_item.application_id}, Status: {app_item.status}, KYC Status: {app_item.user.kyc_verification.kyc_status if app_item.user.kyc_verification else None}")
