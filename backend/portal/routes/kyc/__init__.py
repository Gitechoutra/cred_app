import logging

from portal.api import api

ns = api.namespace(
    'kyc',
    description="KYC submission and verification tiering (PRD FR-012, section 18)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
