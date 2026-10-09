"""
portal/schema.py
================
Keep the database schema in step with the models, at every boot.

Why this exists: `db.create_all()` only creates missing *tables*. A pulled
commit that adds a *column* left every other machine's database behind until
someone remembered `flask db upgrade` - and until then any query on that table
failed with MySQL 1054 "Unknown column", which reaches the user as a bare
"Something went wrong on our end". Adding a card hit exactly that: the limit
check reads credit_applications, which had gained bureau columns.

So boot now runs the migrations itself, and then compares every model column
with the live table and logs anything still missing, naming the fix.
"""

import os

import sqlalchemy as sa
from flask import current_app

from portal import db

MIGRATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'migrations'
)


def _has_revision() -> bool:
    inspector = sa.inspect(db.engine)
    if 'alembic_version' not in inspector.get_table_names():
        return False
    with db.engine.connect() as conn:
        return conn.execute(sa.text('SELECT version_num FROM alembic_version')).first() is not None


def sync_schema():
    """
    Bring the schema to the latest migration. Call inside an app context.

    A database that records a revision is upgraded from it; the migrations
    create the tables they introduce, so this runs before create_all(). A
    database with no revision at all is new: create_all() builds every table
    as the models are now, and it is stamped at the head so later upgrades
    start from the right place. Never raises - a failed upgrade is logged with
    the command to run, and boot carries on so the error is visible rather
    than a server that will not start.
    """
    from flask_migrate import stamp, upgrade

    logger = current_app.logger
    versioned = _has_revision()

    if versioned:
        try:
            upgrade(directory=MIGRATIONS_DIR)
            logger.info('[schema] migrations are at the latest revision.')
        except Exception as exc:     # noqa: BLE001 - reported, not fatal
            logger.error(f'[schema] automatic migration failed: {exc}. '
                         'Run `flask db upgrade` in backend/ and fix the error it shows.')

    db.create_all()

    if not versioned:
        try:
            stamp(directory=MIGRATIONS_DIR)
            logger.info('[schema] new database created from the models and '
                        'stamped at the latest migration.')
        except Exception as exc:     # noqa: BLE001
            logger.error(f'[schema] could not stamp the new database: {exc}')

    missing = missing_columns()
    if missing:
        logger.error(
            '[schema] the database is missing columns the code needs - requests '
            'that touch them will fail with HTTP 500: '
            + ', '.join(missing)
            + '. Run `flask db upgrade` in backend/.'
        )
    return missing


def missing_columns() -> list:
    """`table.column` for every model column the live database lacks."""
    inspector = sa.inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    missing = []
    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            missing.append(f'{table.name}.*')
            continue
        live = {c['name'] for c in inspector.get_columns(table.name)}
        missing.extend(f'{table.name}.{c.name}' for c in table.columns
                       if c.name not in live)
    return missing
