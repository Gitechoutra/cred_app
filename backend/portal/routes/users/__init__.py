import logging

from portal.api import api

ns = api.namespace(
    'users',
    description="User profile and account management (PRD FR-012)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
