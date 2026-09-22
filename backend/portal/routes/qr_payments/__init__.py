import logging

from portal.api import api

ns = api.namespace(
    'qr-payments',
    description='Scan-and-pay: UPI payments made by scanning a merchant QR',
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
