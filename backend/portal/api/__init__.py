from flask import Blueprint, jsonify
from flask_restx import Api

authorizations = {
    'Bearer': {
        'type': 'apiKey',
        'in': 'header',
        'name': 'Authorization',
        'description': "JWT access token. Format: Bearer <token>",
    }
}

api = Api(
    version='1.0',
    title='CashU API',
    description=(
        'Unified Credit Card and EMI Management Platform. '
        'Implements the CashU PRD v1.0.0-PROD-SPEC.'
    ),
    doc='/doc/',
    authorizations=authorizations,
    catch_all_404s=True,
)


def init_app(app):
    v1 = Blueprint('api', __name__, url_prefix='/v1')

    api.init_app(v1)

    # -- Import namespaces -------------------------------------------------
    from portal.routes.authentication import ns as authentication_ns
    from portal.routes.users import ns as users_ns
    from portal.routes.kyc import ns as kyc_ns
    from portal.routes.dashboard import ns as dashboard_ns
    from portal.routes.cards import ns as cards_ns
    from portal.routes.bank_accounts import ns as bank_accounts_ns
    from portal.routes.transfers import ns as transfers_ns
    from portal.routes.emi import ns as emi_ns
    from portal.routes.emi_payments import ns as emi_payments_ns
    from portal.routes.mandates import ns as mandates_ns
    from portal.routes.transactions import ns as transactions_ns
    from portal.routes.notifications import ns as notifications_ns
    from portal.routes.webhooks import ns as webhooks_ns
    from portal.routes.admin import ns as admin_ns
    from portal.routes.support import ns as support_ns

    # -- Register namespaces ----------------------------------------------
    api.add_namespace(authentication_ns, path='/authentication')
    api.add_namespace(users_ns, path='/users')
    api.add_namespace(kyc_ns, path='/kyc')
    api.add_namespace(dashboard_ns, path='/dashboard')
    api.add_namespace(cards_ns, path='/cards')
    api.add_namespace(bank_accounts_ns, path='/bank-accounts')
    api.add_namespace(transfers_ns, path='/transfers')
    api.add_namespace(emi_ns, path='/emi')
    api.add_namespace(emi_payments_ns, path='/emi-payments')
    api.add_namespace(mandates_ns, path='/mandates')
    api.add_namespace(transactions_ns, path='/transactions')
    api.add_namespace(notifications_ns, path='/notifications')
    api.add_namespace(webhooks_ns, path='/webhooks')
    api.add_namespace(admin_ns, path='/admin')
    api.add_namespace(support_ns, path='/support')

    app.register_blueprint(v1)

    _register_health(app)
    _register_error_handlers(app)

    app.logger.info('Initialized API namespaces')


def _register_health(app):
    """
    Liveness and readiness.

    Mounted outside /v1 so the Docker HEALTHCHECK does not depend on the API
    version prefix, and unauthenticated so an orchestrator can reach it.
    """

    @app.route('/health')
    def health():
        return jsonify({'status': 'ok', 'service': 'cashu-api'}), 200

    @app.route('/health/ready')
    def readiness():
        from sqlalchemy import text
        from portal import db

        checks = {}
        healthy = True

        try:
            db.session.execute(text('SELECT 1'))
            checks['database'] = 'ok'
        except Exception as exc:
            checks['database'] = f'error: {exc}'
            healthy = False

        from portal.helpers import cashfree
        checks['payment_gateway'] = (
            'configured' if cashfree.is_configured() else 'sandbox'
        )
        checks['adapters'] = (
            'sandbox' if app.config.get('USE_SANDBOX_ADAPTERS') else 'live'
        )

        return jsonify({
            'status': 'ready' if healthy else 'degraded',
            'checks': checks,
        }), (200 if healthy else 503)


def _register_error_handlers(app):
    """
    Uniform error envelopes.

    Without these an unhandled exception returns Flask's HTML error page, which
    the React client cannot parse - it would surface as a JSON parse error and
    hide the real fault.
    """
    from portal.helpers.helpers import ErrorCode, failure

    @app.errorhandler(404)
    def _not_found(_error):
        return jsonify(failure(
            ErrorCode.NOT_FOUND, 'The requested resource was not found.', 404
        )[0]), 404

    @app.errorhandler(405)
    def _method_not_allowed(_error):
        return jsonify(failure(
            ErrorCode.VALIDATION_ERROR, 'Method not allowed for this endpoint.', 405
        )[0]), 405

    @app.errorhandler(413)
    def _too_large(_error):
        return jsonify(failure(
            ErrorCode.VALIDATION_ERROR,
            'The uploaded file is too large. Maximum size is 10 MB.',
            413,
        )[0]), 413

    @app.errorhandler(429)
    def _rate_limited(_error):
        return jsonify(failure(
            ErrorCode.ERR_011_VELOCITY_ABUSE,
            'Too many requests. Please slow down and try again shortly.',
            429,
        )[0]), 429

    @app.errorhandler(Exception)
    def _unhandled(error):
        from werkzeug.exceptions import HTTPException

        if isinstance(error, HTTPException):
            return jsonify(failure(
                ErrorCode.VALIDATION_ERROR, error.description, error.code
            )[0]), error.code

        # Roll back so a poisoned session does not fail every later request in
        # the same worker with an unrelated InvalidRequestError.
        from portal import db
        db.session.rollback()

        app.logger.exception(f'Unhandled exception: {error}')

        # Never leak internals to the client; the trace is in the log.
        return jsonify(failure(
            ErrorCode.INTERNAL_ERROR,
            'Something went wrong on our end. Please try again.',
            500,
        )[0]), 500
