import logging

from portal.api import api

ns = api.namespace(
    'support',
    description="Support tickets and dispute threads",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
