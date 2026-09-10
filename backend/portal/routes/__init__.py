import logging

logger = logging.getLogger("cashu")


def init_app():
    """
    Import every route module so its resources bind to their namespace.

    The namespace objects themselves are created in each package's __init__.py
    and registered by portal.api; this pass is what actually attaches the
    Resource classes to them.
    """
    from .authentication import routes          # noqa: F401
    from .users import routes                   # noqa: F401
    from .kyc import routes                     # noqa: F401
    from .dashboard import routes               # noqa: F401
    from .cards import routes                   # noqa: F401
    from .bank_accounts import routes           # noqa: F401
    from .transfers import routes               # noqa: F401
    from .emi import routes                     # noqa: F401
    from .emi_payments import routes            # noqa: F401
    from .mandates import routes                # noqa: F401
    from .transactions import routes            # noqa: F401
    from .notifications import routes           # noqa: F401
    from .webhooks import routes                # noqa: F401
    from .admin import routes                   # noqa: F401
    from .support import routes                 # noqa: F401

    logger.info('Initialized routes')
