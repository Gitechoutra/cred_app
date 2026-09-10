import logging

from portal.api import api

ns = api.namespace(
    'dashboard',
    description="Home dashboard aggregate telemetry (PRD FR-002)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
