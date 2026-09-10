"""
app.py
======
CashU API entry point.

    python app.py                        development, port 5050
    gunicorn -b 0.0.0.0:5050 app:app     production (see docker-entrypoint.sh)

`bootstrap()` runs only under `__main__`, so importing this module never touches
the database. gunicorn imports rather than executes, so the container calls
bootstrap explicitly in docker-entrypoint.sh before starting workers - that
keeps schema creation to exactly one process instead of racing it across every
worker that happens to import the app.

Schema handling is deliberately split. `db.create_all()` only ever *adds*
missing tables; it will not alter a column that already exists. Flask-Migrate is
wired up in portal/models/__init__.py and remains the mechanism for changing an
existing table:

    flask db migrate -m "describe the change"
    flask db upgrade
"""

import os

from portal import InitApp, db

app = InitApp().app()


def bootstrap():
    """
    Bring the database up to a usable state.

    Seeding runs on every boot because each seeder is idempotent - it inserts
    what is missing and leaves what exists alone. That matters more than it
    sounds: the engines read fee percentages, transfer limits and the chart of
    ledger accounts from these tables at runtime, so a half-seeded database
    would have transfer_engine silently pricing a transfer against a default.
    """
    with app.app_context():
        db.create_all()
        app.logger.info('Database tables verified.')

        from portal.seeders import run_all_seeders
        run_all_seeders()


if __name__ == '__main__':
    bootstrap()

    port = int(os.getenv('PORT', 5050))
    debug = os.getenv('Backend', 'DEV') == 'DEV'

    app.logger.info(f'Starting CashU API on port {port} (debug={debug})')
    app.logger.info(f'  Swagger  http://localhost:{port}/v1/doc/')
    app.logger.info(f'  Health   http://localhost:{port}/health')
    app.logger.info(f'  Webhooks http://localhost:{port}/v1/webhooks/cashfree/health')

    app.run(host='0.0.0.0', port=port, debug=debug)
