import logging

from portal.api import api

ns = api.namespace(
    'bill-payments',
    description=(
        'Pay Bills: credit drawn for a declared, eligible bill and paid out to '
        "the holder's own verified bank account"
    ),
)

logger = logging.getLogger(__name__)

from .routes import *  # noqa: E402,F401,F403
