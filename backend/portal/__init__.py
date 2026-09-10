import os

from flask import Flask
from flask_cors import CORS
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

APP = None

db = SQLAlchemy()


def init_cors(app):
    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=True,
        expose_headers=['X-Idempotency-Key'],
    )
    APP.logger.info('Initialized CORS')


class InitApp:
    def app(self):
        global APP
        if APP:
            return APP

        # Load .env file before anything else
        load_dotenv()

        APP = Flask(__name__)

        environment = os.getenv('Backend', 'DEV')

        # -- Logger --------------------------------------------------------
        from portal.logger import init_logger
        logger = init_logger()
        APP.logger = logger

        # -- Config --------------------------------------------------------
        from config.config import config_by_name

        config_name = 'development' if environment == 'DEV' else 'production'
        APP.config.from_object(config_by_name[config_name])

        APP.debug = (environment == 'DEV')
        APP.secret_key = APP.config['SECRET_KEY']

        db.init_app(APP)

        APP.config['SESSION_TYPE'] = 'filesystem'
        os.makedirs(APP.config['UPLOAD_FOLDER'], exist_ok=True)
        Session(APP)

        logger.info(f"Logger initialized - environment: {environment}")

        try:
            from . import api, routes, models
            from portal.helpers.email import init_mail
            from portal.helpers.jwt import Token

            models.init_app(APP)
            api.init_app(APP)
            routes.init_app()
            Token(APP)
            # Bound here rather than in app.py so Flask-Mail is initialised on
            # every entry point - gunicorn imports the factory without ever
            # running app.py's __main__ block.
            init_mail(APP)
            init_cors(APP)

            # -- Scheduler -------------------------------------------------
            # Only the reloader's child process registers jobs, otherwise the
            # dev server runs every scheduled job twice.
            if not APP.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
                try:
                    from portal.scheduler import init_scheduler
                    init_scheduler(APP)
                    logger.info('APScheduler started')
                except Exception as sched_err:
                    logger.warning(f'APScheduler init failed (non-fatal): {sched_err}')

        except Exception as e:
            APP.logger.error('An error occurred while initializing app components: %s', e)
            raise

        APP.logger.info('CashU app initialization completed successfully')
        return APP
