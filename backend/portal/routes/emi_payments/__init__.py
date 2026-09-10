import logging

from portal.api import api

ns = api.namespace(
    'emi-payments',
    description="Manual EMI payment processing (PRD FR-008, section 11)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
