"""
A database left behind by a pulled commit must not turn into HTTP 500s.

Builds a throwaway database (cashu_schema_sync_check) as one stuck at revision
c6f2a8d4e1b7 looks - the point where the migration history forked into two
heads and `flask db upgrade` stopped working - and shows:

    1. linking a card on it fails with exactly the 500 users saw
       ("Something went wrong on our end"), from MySQL 1054 Unknown column;
    2. one boot (app.bootstrap) applies the pending migrations, leaves no
       model column missing, and the same request gets a real answer.

The development database is never touched; the scratch one is dropped after.
Needs MySQL (DATABASE_URL in .env), not the API server.

    python tests/schema_sync.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(BACKEND, '.env'))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

SCRATCH = 'cashu_schema_sync_check'
base = make_url(os.getenv('DATABASE_URL',
                          'mysql+pymysql://root:Mahesh2605@localhost:3306/cashu_db'))
os.environ['DATABASE_URL'] = base.set(database=SCRATCH).render_as_string(hide_password=False)
server = sa.create_engine(base.set(database=None))

#: What a database stuck at c6f2a8d4e1b7 lacks.
STALE = {
    'credit_applications': ['bureau_provider', 'bureau_code', 'bureau_error',
                            'bureau_name', 'bureau_is_test'],
    'credit_score_checks': ['bureau'],
    'emi_payments': ['upi_rrn'],
}

PASS, FAIL = [], []


def check(label, condition, detail=''):
    (PASS if condition else FAIL).append(label)
    mark = 'PASS' if condition else 'FAIL'
    print(f'  [{mark}] {label}' + (f' - {detail}' if detail and not condition else ''))
    return bool(condition)


def main():
    with server.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS {SCRATCH}'))
        conn.execute(sa.text(f'CREATE DATABASE {SCRATCH} CHARACTER SET utf8mb4 '
                             'COLLATE utf8mb4_unicode_ci'))

    import logging
    logging.disable(logging.CRITICAL)      # the expected 500 logs a traceback

    from app import app, bootstrap
    from portal import db

    def link_card(user_id):
        from portal.helpers.jwt import issue_tokens
        from portal.models.users import Users
        tokens = issue_tokens(Users.query.get(user_id), device_uuid='schema-sync')
        db.session.commit()
        access = tokens['access_token'] if isinstance(tokens, dict) else tokens[0]
        response = app.test_client().post('/v1/cards', json={
            'bin': '421823', 'last4': '0123', 'expiry_month': '12',
            'expiry_year': '2045', 'issuer_bank': 'HDFC Bank', 'due_day': 10,
        }, headers={'Authorization': f'Bearer {access}', 'X-Device-UUID': 'schema-sync'})
        return response.status_code, (response.get_json() or {}).get('error') or {}

    try:
        with app.app_context():
            if not check('working on the scratch database only',
                         db.engine.url.database == SCRATCH, db.engine.url.database):
                return 1
            print('\n[1] A database stuck at the fork')
            db.create_all()
            with db.engine.begin() as conn:
                for table, columns in STALE.items():
                    for column in columns:
                        conn.execute(sa.text(f'ALTER TABLE {table} DROP COLUMN {column}'))
                conn.execute(sa.text('CREATE TABLE alembic_version '
                                     '(version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
                conn.execute(sa.text("INSERT INTO alembic_version VALUES ('c6f2a8d4e1b7')"))

            from portal.models.roles import Roles
            from portal.models.users import Users
            from portal.schema import missing_columns
            from portal.seeders.seed_roles import seed_roles
            seed_roles()
            role = Roles.query.filter_by(role_name='NORMAL_USER').first()
            user = Users(phone='9000000001', full_name='Schema Sync', kyc_tier='FULL',
                         status='ACTIVE', role_id=role.role_id)
            db.session.add(user)
            db.session.commit()
            user_id = user.user_id

            check('the drift is detected', len(missing_columns()) == 7, missing_columns())
            status, error = link_card(user_id)
            check('adding a card fails with the 500 users saw',
                  status == 500 and 'on our end' in error.get('message', ''), (status, error))

        print('\n[2] After one boot')
        bootstrap()
        with app.app_context():
            from portal.schema import missing_columns
            check('no model column is missing', missing_columns() == [], missing_columns())
            with db.engine.connect() as conn:
                revision = conn.execute(sa.text('SELECT version_num FROM alembic_version')).scalar()
            heads = _heads()
            check('the database is at the single migration head',
                  len(heads) == 1 and revision == heads[0], (revision, heads))
            status, error = link_card(user_id)
            check('the same request now gets a real answer, not a 500',
                  status == 422 and error.get('code') == 'KYC_REQUIRED', (status, error))
    finally:
        logging.disable(logging.NOTSET)
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
        with server.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS {SCRATCH}'))

    print(f'\n{len(PASS)} passed, {len(FAIL)} failed')
    for label in FAIL:
        print(f'  FAILED: {label}')
    return 1 if FAIL else 0


def _heads():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    config = Config()
    config.set_main_option('script_location', os.path.join(BACKEND, 'migrations'))
    return ScriptDirectory.from_config(config).get_heads()


if __name__ == '__main__':
    sys.exit(main())
