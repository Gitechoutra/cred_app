import logging

from portal.api import api

ns = api.namespace(
    'credit',
    description=(
        'The credit line: application, approval, purpose, activation, spending, '
        'statements and bill payment'
    ),
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
