import logging

from portal.api import api

ns = api.namespace(
    'webhooks',
    description="Signed gateway callbacks - Cashfree PG, Payouts, Verification",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
