from app import app
from portal.models.kyc_verifications import KYCVerifications

with app.app_context():
    for k in KYCVerifications.query.all():
        print(f"ID: {k.kyc_id}, PAN: {k.pan_document_path}, Aadhaar: {k.aadhaar_document_path}, Status: {k.kyc_status}")
