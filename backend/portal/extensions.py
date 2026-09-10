"""
portal/extensions.py
====================
Shared Flask extension instances - imported by models and the app factory.
"""

from flask_migrate import Migrate
from flask_jwt_extended import JWTManager

from portal import db

migrate = Migrate()
jwt = JWTManager()
