from app import app
from portal import db
from portal.models.credit_applications import CreditApplications
from portal.helpers import credit_engine

with app.app_context():
    app_item = CreditApplications.query.filter_by(application_id='2a049fd5-5997-4ef9-bff6-953ad1da61f1').first()
    success = credit_engine._fetch_credit_score(app_item, app_item.user)
    print(f"Fetch Success: {success}")
    print(f"Bureau Error: {app_item.bureau_error}")
    credit_engine._reassess(app_item, app_item.user)
    print(f"Offered Limit: {app_item.offered_limit}")
    db.session.commit()
