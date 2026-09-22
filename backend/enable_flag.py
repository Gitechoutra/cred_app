from portal import db, InitApp
from portal.models.admin_settings import FeatureFlags

app = InitApp().app()
with app.app_context():
    flag = FeatureFlags.query.filter_by(flag_key='CARD_LINKING').first()
    if flag:
        flag.is_enabled = True
        db.session.commit()
        print("CARD_LINKING flag enabled successfully!")
    else:
        print("Flag not found.")
