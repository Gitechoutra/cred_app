"""Retire credit-to-bank transfers

The product no longer moves money from a credit line to a bank account, so the
tables that existed only to record those movements go with it.

A note on what this does *not* drop. master_transactions and
double_entry_ledger keep every transfer that ever settled: they are the ledger,
they are append-only, and a completed transfer is a real historical movement of
real money whatever the product does next. Dropping them would be falsifying
the books, not cleaning up. Only the product-specific rows go.

The downgrade recreates the schema but cannot recreate the data. Anyone who
needs the rows back should restore from a backup taken before this ran; the
empty tables are here so an older application version can start, not so the
history reappears.

Revision ID: a1f4c7b9de02
Revises: 9abf36599b0d
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'a1f4c7b9de02'
down_revision = '9abf36599b0d'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # transfers first: it holds the foreign keys.
    for table in ('transfers', 'transfer_limit_counters', 'penny_drop_verifications'):
        if table == 'penny_drop_verifications':
            # Kept. Bank-account ownership still has to be proved for mandates
            # and for bill payment, so the penny-drop audit trail survives the
            # pivot. Listed here only to make that decision explicit.
            continue
        if table in tables:
            op.drop_table(table)

    if 'cards' in tables:
        columns = {c['name'] for c in inspector.get_columns('cards')}
        if 'is_transfer_eligible' in columns:
            op.drop_column('cards', 'is_transfer_eligible')


def downgrade():
    op.add_column(
        'cards',
        sa.Column('is_transfer_eligible', sa.Boolean(), nullable=True,
                  server_default=sa.true()),
    )

    op.create_table(
        'transfer_limit_counters',
        sa.Column('counter_id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False, index=True),
        sa.Column('window_type', sa.String(10), nullable=False),
        sa.Column('window_key', sa.String(10), nullable=False),
        sa.Column('transfer_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_amount', sa.Numeric(14, 2), nullable=False, server_default='0'),
        sa.Column('created_on', sa.DateTime(), nullable=True),
        sa.Column('updated_on', sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            'user_id', 'window_type', 'window_key', name='uq_user_window',
        ),
    )

    op.create_table(
        'transfers',
        sa.Column('transfer_id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.user_id'),
                  nullable=False, index=True),
        sa.Column('card_id', sa.String(36), sa.ForeignKey('cards.card_id'),
                  nullable=False, index=True),
        sa.Column('bank_account_id', sa.String(36),
                  sa.ForeignKey('bank_accounts.bank_account_id'),
                  nullable=False, index=True),
        sa.Column('transaction_id', sa.String(36), nullable=True, index=True),

        sa.Column('principal_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('convenience_fee', sa.Numeric(12, 2), nullable=False),
        sa.Column('gst_on_fee', sa.Numeric(12, 2), nullable=False),
        sa.Column('total_charged_to_card', sa.Numeric(12, 2), nullable=False),
        sa.Column('net_payout_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('fee_percentage_applied', sa.Numeric(5, 2), nullable=False),

        sa.Column('source_opening_balance', sa.Numeric(12, 2), nullable=True),
        sa.Column('source_closing_balance', sa.Numeric(12, 2), nullable=True),
        sa.Column('destination_opening_balance', sa.Numeric(12, 2), nullable=True),
        sa.Column('destination_closing_balance', sa.Numeric(12, 2), nullable=True),

        sa.Column('idempotency_key', sa.String(64), nullable=False, unique=True),
        sa.Column('status', sa.String(30), nullable=False),

        sa.Column('source_instrument', sa.String(20), nullable=True),
        sa.Column('source_vpa', sa.String(120), nullable=True),
        sa.Column('gateway_provider', sa.String(30), nullable=True),
        sa.Column('gateway_order_id', sa.String(150), nullable=True, index=True),
        sa.Column('gateway_payment_id', sa.String(150), nullable=True),
        sa.Column('gateway_signature', sa.String(512), nullable=True),
        sa.Column('three_ds_url', sa.String(1000), nullable=True),
        sa.Column('charged_at', sa.DateTime(), nullable=True),

        sa.Column('payout_provider', sa.String(30), nullable=True),
        sa.Column('payout_reference', sa.String(150), nullable=True, index=True),
        sa.Column('bank_rrn_utr', sa.String(50), nullable=True, index=True),
        sa.Column('payout_dispatched_at', sa.DateTime(), nullable=True),
        sa.Column('payout_completed_at', sa.DateTime(), nullable=True),
        sa.Column('payout_retry_count', sa.Integer(), server_default='0'),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),

        sa.Column('reversal_reference', sa.String(150), nullable=True),
        sa.Column('reversed_at', sa.DateTime(), nullable=True),

        sa.Column('risk_score', sa.Numeric(5, 2), nullable=True),
        sa.Column('risk_decision', sa.String(30), nullable=True),
        sa.Column('risk_reason', sa.String(500), nullable=True),
        sa.Column('failure_code', sa.String(50), nullable=True),
        sa.Column('failure_reason', sa.String(500), nullable=True),

        sa.Column('device_uuid', sa.String(100), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),

        sa.Column('created_on', sa.DateTime(), nullable=True),
        sa.Column('updated_on', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_transfers_user_created', 'transfers', ['user_id', 'created_on'],
    )
