"""Record which bureau answered, and whether the answer was test data

A score is only meaningful next to the bureau that produced it - Experian,
CRIF and Equifax each score the same person differently - and a provider's
test environment answers with test files that must never pass for a real
report. Existing rows all came from the sandbox, and are backfilled as such.

Revision ID: a3d7e5c2b918
Revises: f7c8a9d2e341
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = 'a3d7e5c2b918'
down_revision = 'f7c8a9d2e341'
branch_labels = None
depends_on = None


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    checks = _columns('credit_score_checks')
    if 'bureau' not in checks:
        op.add_column('credit_score_checks',
                      sa.Column('bureau', sa.String(20), nullable=True))

    applications = _columns('credit_applications')
    if 'bureau_name' not in applications:
        op.add_column('credit_applications',
                      sa.Column('bureau_name', sa.String(20), nullable=True))
    if 'bureau_is_test' not in applications:
        op.add_column('credit_applications',
                      sa.Column('bureau_is_test', sa.Boolean(), nullable=False,
                                server_default=sa.false()))

    op.execute("UPDATE credit_score_checks SET bureau = 'SANDBOX' "
               "WHERE provider = 'SANDBOX' AND bureau IS NULL")
    op.execute("UPDATE credit_applications SET bureau_name = 'SANDBOX', "
               "bureau_is_test = 1 WHERE bureau_provider = 'SANDBOX'")


def downgrade():
    if 'bureau_is_test' in _columns('credit_applications'):
        op.drop_column('credit_applications', 'bureau_is_test')
    if 'bureau_name' in _columns('credit_applications'):
        op.drop_column('credit_applications', 'bureau_name')
    if 'bureau' in _columns('credit_score_checks'):
        op.drop_column('credit_score_checks', 'bureau')
