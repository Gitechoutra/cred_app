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

Schema: bootstrap() applies any pending migrations itself (portal/schema.py),
then creates missing tables, then logs any model column the database still
lacks. A schema change is still written as a migration:

    flask db migrate -m "describe the change"
    flask db upgrade        # or just restart the server
"""

import os

from portal import InitApp

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
        # Migrations first, then create_all for anything they do not cover,
        # then a column-by-column check. A database left behind by a pulled
        # commit used to fail at query time with a bare HTTP 500.
        from portal.schema import sync_schema
        sync_schema()
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

    # Watch .env too, so saving it restarts the dev server - and the restart
    # re-runs the seeders, which sync the admin's phone and MPIN from it.
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    app.run(host='0.0.0.0', port=port, debug=debug,
            extra_files=[env_file] if os.path.isfile(env_file) else None)
