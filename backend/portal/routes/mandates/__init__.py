import logging

from portal.api import api

ns = api.namespace(
    'mandates',
    description="NPCI e-Mandate auto-pay (PRD FR-009, section 12)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
