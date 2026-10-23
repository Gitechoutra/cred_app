"""Add the bureau result columns where a database is missing them

d8a1f3c5b724 already adds bureau_provider, bureau_code and bureau_error and
drops eligibility_score. This revision repairs a database that was stamped
past it without those changes. Every step checks first, so on a database
that is already correct it does nothing.

Revision ID: 3eaa1c6847bf
Revises: a3d7e5c2b918
Create Date: 2026-10-09 11:56:03.766467
"""
import sqlalchemy as sa
from alembic import op

revision = '3eaa1c6847bf'
down_revision = 'a3d7e5c2b918'
branch_labels = None
depends_on = None


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    existing = _columns('credit_applications')
    with op.batch_alter_table('credit_applications', schema=None) as batch:
        if 'bureau_provider' not in existing:
            batch.add_column(sa.Column('bureau_provider', sa.String(20), nullable=True))
        if 'bureau_code' not in existing:
            batch.add_column(sa.Column('bureau_code', sa.String(20), nullable=True))
        if 'bureau_error' not in existing:
            batch.add_column(sa.Column('bureau_error', sa.String(255), nullable=True))
        if 'eligibility_score' in existing:
            batch.drop_column('eligibility_score')


def downgrade():
    # The columns belong to d8a1f3c5b724; undoing this repair leaves them.
    pass
