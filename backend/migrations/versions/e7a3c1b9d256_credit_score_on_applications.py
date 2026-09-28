"""Credit score on credit applications

The credit limit is now decided from salary and the applicant's credit score,
never from a limit the applicant asks for. This records the score, whether the
bureau had any history at all, when it was fetched, the bureau's reference, and
when the applicant consented to the enquiry.

requested_limit stays, unwritten, so older applications read back unchanged.

Revision ID: e7a3c1b9d256
Revises: d5e2a7c9f184
Create Date: 2026-09-28
"""
import sqlalchemy as sa
from alembic import op

revision = 'e7a3c1b9d256'
down_revision = 'd5e2a7c9f184'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('credit_applications', sa.Column('credit_score', sa.Integer(), nullable=True))
    op.add_column('credit_applications', sa.Column(
        'credit_no_history', sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column('credit_applications', sa.Column('credit_score_fetched_at', sa.DateTime(), nullable=True))
    op.add_column('credit_applications', sa.Column('bureau_reference', sa.String(64), nullable=True))
    op.add_column('credit_applications', sa.Column('bureau_consent_at', sa.DateTime(), nullable=True))


def downgrade():
    for column in ('bureau_consent_at', 'bureau_reference', 'credit_score_fetched_at',
                   'credit_no_history', 'credit_score'):
        op.drop_column('credit_applications', column)
