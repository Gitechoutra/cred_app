"""Bureau result on credit applications; drop the affordability "score"

Records who answered a credit bureau enquiry, the bureau's own no-history code
(NH / NA) and why an enquiry produced nothing usable, so an applicant whose
score could not be fetched is shown that rather than "fetching" forever.

Drops eligibility_score. It was the share of income not already going to EMIs,
stored under a name that read as a credit score; the same figure is in the
eligibility breakdown as foir_percent, computed rather than stored.

Every score recorded before this revision came from the sandbox bureau - no
live bureau has ever been connected - so those rows are marked SANDBOX rather
than left looking like real bureau results.

Revision ID: d8a1f3c5b724
Revises: c6f2a8d4e1b7
Create Date: 2026-10-05
"""
import sqlalchemy as sa
from alembic import op

revision = 'd8a1f3c5b724'
down_revision = 'c6f2a8d4e1b7'
branch_labels = None
depends_on = None


def _columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns('credit_applications')}


def upgrade():
    existing = _columns()
    with op.batch_alter_table('credit_applications') as batch:
        if 'bureau_provider' not in existing:
            batch.add_column(sa.Column('bureau_provider', sa.String(20), nullable=True))
        if 'bureau_code' not in existing:
            batch.add_column(sa.Column('bureau_code', sa.String(20), nullable=True))
        if 'bureau_error' not in existing:
            batch.add_column(sa.Column('bureau_error', sa.String(255), nullable=True))
        if 'eligibility_score' in existing:
            batch.drop_column('eligibility_score')

    op.execute(
        "UPDATE credit_applications SET bureau_provider = 'SANDBOX' "
        "WHERE credit_score_fetched_at IS NOT NULL AND bureau_provider IS NULL"
    )


def downgrade():
    with op.batch_alter_table('credit_applications') as batch:
        batch.add_column(sa.Column('eligibility_score', sa.Numeric(5, 2), nullable=True))
        batch.drop_column('bureau_error')
        batch.drop_column('bureau_code')
        batch.drop_column('bureau_provider')
