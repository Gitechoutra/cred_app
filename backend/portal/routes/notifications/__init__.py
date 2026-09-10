import logging

from portal.api import api

ns = api.namespace(
    'notifications',
    description="Notification feed and preferences (PRD FR-011, section 14)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
