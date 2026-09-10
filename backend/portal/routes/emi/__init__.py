import logging

from portal.api import api

ns = api.namespace(
    'emi',
    description="EMI obligation registry (PRD FR-007, section 10)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
