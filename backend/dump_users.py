from app import app
from portal.models.users import Users

with app.app_context():
    for u in Users.query.all():
        print(f"ID: {u.user_id}, Phone: {u.phone}, Role: {u.role.role_name if u.role else None}")
