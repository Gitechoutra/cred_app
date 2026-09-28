"""Remove unused tables, fields and seed data

Cleanup of what nothing in the product uses any more:

- credit_applications.requested_limit. Applicants no longer name a limit; it
  is worked out from salary and credit score. Nothing has written it since.
- reconciliation_runs, and reconciliation_discrepancies.run_id. No code ever
  created a run. Worse, the ledger integrity sweep recorded discrepancies with
  run_id=None into this NOT NULL column, so recording one always failed - the
  table was empty for that reason. Its payout_total belonged to the retired
  credit-to-bank transfer's settlement file.
- platform_statistics. Never read or written.
- The six TRANSFER_* notification templates. Nothing can send those events
  since the transfer product was removed. Notifications already sent keep
  their rows: they are history.

Both dropped tables were verified empty before this was written.

Revision ID: a8c4e2f7b513
Revises: f4b8d2e6a913
Create Date: 2026-09-28
"""
import sqlalchemy as sa
from alembic import op

revision = 'a8c4e2f7b513'
down_revision = 'f4b8d2e6a913'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('credit_applications', 'requested_limit')

    op.drop_constraint('reconciliation_discrepancies_ibfk_1',
                       'reconciliation_discrepancies', type_='foreignkey')
    op.drop_index('ix_reconciliation_discrepancies_run_id',
                  table_name='reconciliation_discrepancies')
    op.drop_column('reconciliation_discrepancies', 'run_id')
    op.drop_table('reconciliation_runs')
    op.drop_table('platform_statistics')

    op.execute("DELETE FROM notification_templates WHERE event LIKE 'TRANSFER\\_%'")


def downgrade():
    # Structure only. The dropped tables held no rows, the transfer templates
    # are reseedable from history, and requested_limit comes back empty.
    op.create_table(
        'platform_statistics',
        sa.Column('stat_id', sa.String(36), primary_key=True),
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('updated_on', sa.DateTime(), nullable=False),
    )
    op.create_table(
        'reconciliation_runs',
        sa.Column('run_id', sa.CHAR(36), primary_key=True),
        sa.Column('window_start', sa.DateTime(), nullable=False),
        sa.Column('window_end', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('transactions_examined', sa.Integer()),
        sa.Column('matched_count', sa.Integer()),
        sa.Column('discrepancy_count', sa.Integer()),
        sa.Column('ledger_total', sa.Numeric(16, 2)),
        sa.Column('gateway_total', sa.Numeric(16, 2)),
        sa.Column('payout_total', sa.Numeric(16, 2)),
        sa.Column('started_at', sa.DateTime()),
        sa.Column('completed_at', sa.DateTime()),
        sa.Column('error_message', sa.String(1000)),
        sa.Column('created_on', sa.DateTime(), nullable=False),
        sa.Column('updated_on', sa.DateTime(), nullable=False),
    )
    op.add_column('reconciliation_discrepancies',
                  sa.Column('run_id', sa.CHAR(36), nullable=True))
    op.create_index('ix_reconciliation_discrepancies_run_id',
                    'reconciliation_discrepancies', ['run_id'])
    op.create_foreign_key('reconciliation_discrepancies_ibfk_1',
                          'reconciliation_discrepancies', 'reconciliation_runs',
                          ['run_id'], ['run_id'])
    op.add_column('credit_applications',
                  sa.Column('requested_limit', sa.Numeric(12, 2), nullable=True))
