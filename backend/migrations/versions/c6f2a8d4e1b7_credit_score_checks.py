"""Credit score checks: the user's own score look-ups, with their consent

Revision ID: c6f2a8d4e1b7
Revises: b9d4f1a7c3e2
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = 'c6f2a8d4e1b7'
down_revision = 'b9d4f1a7c3e2'
branch_labels = None
depends_on = None


def upgrade():
    # app.py's create_all() may already have made it on a dev server.
    if 'credit_score_checks' in sa.inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        'credit_score_checks',
        sa.Column('check_id', sa.CHAR(36), primary_key=True),
        sa.Column('user_id', sa.CHAR(36), sa.ForeignKey('users.user_id'),
                  nullable=False),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('consent_at', sa.DateTime(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('no_history', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('provider', sa.String(20), nullable=True),
        sa.Column('bureau_reference', sa.String(64), nullable=True),
        sa.Column('is_demo', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('report', sa.JSON(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=True),
        sa.Column('error', sa.String(255), nullable=True),
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('updated_on', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_credit_score_checks_user_id', 'credit_score_checks',
                    ['user_id'])
    op.create_index('ix_credit_score_checks_user_created', 'credit_score_checks',
                    ['user_id', 'created_on'])


def downgrade():
    op.drop_index('ix_credit_score_checks_user_created', 'credit_score_checks')
    op.drop_index('ix_credit_score_checks_user_id', 'credit_score_checks')
    op.drop_table('credit_score_checks')
