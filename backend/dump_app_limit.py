from app import app
from portal.models.credit_applications import CreditApplications

with app.app_context():
    app_item = CreditApplications.query.filter_by(application_id='2a049fd5-5997-4ef9-bff6-953ad1da61f1').first()
    print(f"Offered Limit: {app_item.offered_limit}")
    print(f"Credit Score: {app_item.credit_score}")
