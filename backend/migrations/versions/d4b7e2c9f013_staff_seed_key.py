"""Staff seed key on users

users.seed_key is the stable `key` a staff seeder (seed_admin, seed_customer)
lists an account under, so the account is still found after its phone or
email changes. NULL for every account no seeder manages.

Additive only, and checks first, so it is safe on a database that create_all()
already brought up to date.

Revision ID: d4b7e2c9f013
Revises: c1d9e4f2a805
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = 'd4b7e2c9f013'
down_revision = 'c1d9e4f2a805'
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade():
    if 'seed_key' not in {c['name'] for c in _inspector().get_columns('users')}:
        op.add_column('users', sa.Column('seed_key', sa.String(64), nullable=True))
    if 'ix_users_seed_key' not in {i['name'] for i in _inspector().get_indexes('users')}:
        op.create_index('ix_users_seed_key', 'users', ['seed_key'], unique=True)


def downgrade():
    if 'ix_users_seed_key' in {i['name'] for i in _inspector().get_indexes('users')}:
        op.drop_index('ix_users_seed_key', table_name='users')
    if 'seed_key' in {c['name'] for c in _inspector().get_columns('users')}:
        op.drop_column('users', 'seed_key')
