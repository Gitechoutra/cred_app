import logging

from portal.api import api

ns = api.namespace(
    'cards',
    description="Credit card linking via CoFT tokenization (PRD FR-003, FR-004)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
