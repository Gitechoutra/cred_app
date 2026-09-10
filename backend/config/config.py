"""
config/config.py
================
Configuration classes for development, testing, and production.
Copy .env.example to .env and populate before running.
"""

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


class BaseConfig:
    """Shared settings across all environments."""

    SECRET_KEY = os.getenv('APP_SECRET_KEY', 'CHANGE-ME-IN-PRODUCTION')
    DEBUG = False
    TESTING = False

    # -- Database ----------------------------------------------------------
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False

    # -- JWT ---------------------------------------------------------------
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'JWT-CHANGE-ME')
    # PRD FR-001: access token 15-min lifespan, refresh token 30 days rotated
    # on every use.
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        minutes=int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES_MINUTES', 15))
    )
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(
        days=int(os.getenv('JWT_REFRESH_TOKEN_EXPIRES_DAYS', 30))
    )
    JWT_ALGORITHM = 'HS256'

    # -- CORS --------------------------------------------------------------
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', '*')

    # -- Mail --------------------------------------------------------------
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'False') == 'True'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@cashu.app')

    # -- Cashfree (payment gateway + payouts + verification suite) ---------
    CASHFREE_APP_ID = os.getenv('CASHFREE_APP_ID', '')
    CASHFREE_SECRET_KEY = os.getenv('CASHFREE_SECRET_KEY', '')
    CASHFREE_ENV = os.getenv('CASHFREE_ENV', 'SANDBOX')  # SANDBOX | PRODUCTION
    CASHFREE_WEBHOOK_SECRET = os.getenv('CASHFREE_WEBHOOK_SECRET', '')
    CASHFREE_API_VERSION = os.getenv('CASHFREE_API_VERSION', '2023-08-01')
    CASHFREE_PAYOUT_CLIENT_ID = os.getenv('CASHFREE_PAYOUT_CLIENT_ID', '')
    CASHFREE_PAYOUT_CLIENT_SECRET = os.getenv('CASHFREE_PAYOUT_CLIENT_SECRET', '')

    # When True, every external adapter uses its simulated implementation.
    # PRD section 21 lists all nine vendor integrations as "To Be Confirmed",
    # so sandbox mode is the default until real credentials are present.
    USE_SANDBOX_ADAPTERS = os.getenv('USE_SANDBOX_ADAPTERS', 'True') == 'True'

    # -- Encryption --------------------------------------------------------
    # AES-256-GCM field-level key for PII (PRD 17.1). 32 raw bytes, base64'd.
    FIELD_ENCRYPTION_KEY = os.getenv('FIELD_ENCRYPTION_KEY', '')

    # -- Uploads -----------------------------------------------------------
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'portal', 'uploads')
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB per KYC document

    # -- Frontend ----------------------------------------------------------
    FRONTEND_BASE_URL = os.getenv('FRONTEND_BASE_URL', 'http://localhost:3000')


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'mysql+pymysql://root:Mahesh2605@localhost:3306/cashu_db'
    )
    SQLALCHEMY_ECHO = os.getenv('SQL_ECHO', 'False') == 'True'


class TestingConfig(BaseConfig):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'TEST_DATABASE_URL',
        'mysql+pymysql://root:Mahesh2605@localhost:3306/cashu_test_db'
    )
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(minutes=10)
    USE_SANDBOX_ADAPTERS = True


class ProductionConfig(BaseConfig):
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', '')
    SQLALCHEMY_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', 10))
    SQLALCHEMY_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', 20))
    SQLALCHEMY_POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', 30))
    SQLALCHEMY_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', 1800))
    SQLALCHEMY_ECHO = False


config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}
