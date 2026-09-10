import logging

from portal.api import api

ns = api.namespace(
    'transfers',
    description="Credit facility to bank transfers (PRD FR-006, section 9)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
