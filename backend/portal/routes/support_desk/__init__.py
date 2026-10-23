import logging

from portal.api import api

ns = api.namespace(
    'support-desk',
    description="Customer support desk: ticket handling and masked customer lookup",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
