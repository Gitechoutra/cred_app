import logging

from portal.api import api

ns = api.namespace(
    'transactions',
    description="Double-entry ledger and transaction history (PRD FR-010)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
