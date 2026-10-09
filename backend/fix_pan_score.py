from app import app
from portal import db
from portal.models.credit_applications import CreditApplications
from portal.helpers.encryption import encrypt
from portal.helpers import credit_engine

with app.app_context():
    app_item = CreditApplications.query.filter_by(application_id='2a049fd5-5997-4ef9-bff6-953ad1da61f1').first()
    if app_item:
        user = app_item.user
        # 1. Fix PAN
        good_pan = "ABCDE0750F"
        if user.profile:
            user.profile.pan_number_enc = encrypt(good_pan)
        if user.kyc_verification:
            user.kyc_verification.pan_masked = f"{good_pan[:2]}******{good_pan[-2:]}"
        
        # 2. Fetch score
        print(f"Fetching score for PAN {good_pan}...")
        success = credit_engine._fetch_credit_score(app_item, user)
        print(f"Fetch success: {success}, Score: {app_item.credit_score}")
        
        # 3. Reassess
        credit_engine._reassess(app_item, user)
        print(f"Offered limit: {app_item.offered_limit}")
        
        db.session.commit()
        print("Done!")
