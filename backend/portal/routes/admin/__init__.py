import logging

from portal.api import api

ns = api.namespace(
    'admin',
    description="Admin and operations console (PRD sections 15, 16)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
