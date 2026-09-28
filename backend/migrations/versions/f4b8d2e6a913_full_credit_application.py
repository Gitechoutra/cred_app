"""The full credit application: employment, income proof and bank account

A credit application now carries what a lender actually reviews, not just a
declared salary: who the applicant works for and for how long, a document that
evidences the income, and the verified bank account the salary lands in.

All nullable, because applications made before this read back unchanged.

Revision ID: f4b8d2e6a913
Revises: e7a3c1b9d256
Create Date: 2026-09-28
"""
import sqlalchemy as sa
from alembic import op

revision = 'f4b8d2e6a913'
down_revision = 'e7a3c1b9d256'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('credit_applications', sa.Column('employer_name', sa.String(150), nullable=True))
    op.add_column('credit_applications', sa.Column('designation', sa.String(100), nullable=True))
    op.add_column('credit_applications', sa.Column('months_in_current_job', sa.Integer(), nullable=True))
    op.add_column('credit_applications', sa.Column('income_proof_type', sa.String(20), nullable=True))
    op.add_column('credit_applications', sa.Column('income_proof_path', sa.String(500), nullable=True))
    op.add_column('credit_applications', sa.Column('bank_account_id', sa.CHAR(36), nullable=True))
    op.create_foreign_key(
        'fk_credit_applications_bank_account', 'credit_applications',
        'bank_accounts', ['bank_account_id'], ['bank_account_id'],
    )


def downgrade():
    op.drop_constraint('fk_credit_applications_bank_account', 'credit_applications',
                       type_='foreignkey')
    for column in ('bank_account_id', 'income_proof_path', 'income_proof_type',
                   'months_in_current_job', 'designation', 'employer_name'):
        op.drop_column('credit_applications', column)
