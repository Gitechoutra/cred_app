import logging

from portal.api import api

ns = api.namespace(
    'authentication',
    description="Authentication - OTP, MPIN, JWT session lifecycle (PRD FR-001)",
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
