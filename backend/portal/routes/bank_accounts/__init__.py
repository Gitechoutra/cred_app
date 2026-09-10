import logging

from portal.api import api

ns = api.namespace(
    'bank-accounts',
    description="Bank account linking and penny-drop verification (PRD FR-005)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
