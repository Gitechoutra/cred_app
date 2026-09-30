"""Pay Bills: credit drawn for a declared bill, paid out to a verified account

Reinstates a credit-to-bank movement (retired in a1f4c7b9de02) as a narrower
product: every draw names a bill category, a biller, a bill reference and a
purpose, is priced with fee and GST before consent, is authenticated by OTP,
and pays out only to the holder's own penny-drop-verified account. See
BillPayments for the audit fields and Version1.md for the deviation note.

Revision ID: b9d4f1a7c3e2
Revises: a8c4e2f7b513
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = 'b9d4f1a7c3e2'
down_revision = 'a8c4e2f7b513'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'bill_payments',
        sa.Column('bill_payment_id', sa.CHAR(36), primary_key=True),
        sa.Column('reference', sa.String(20), nullable=False),
        sa.Column('user_id', sa.CHAR(36), sa.ForeignKey('users.user_id'),
                  nullable=False),
        sa.Column('credit_account_id', sa.CHAR(36),
                  sa.ForeignKey('credit_accounts.credit_account_id'),
                  nullable=False),
        sa.Column('bank_account_id', sa.CHAR(36),
                  sa.ForeignKey('bank_accounts.bank_account_id'),
                  nullable=False),
        sa.Column('status', sa.String(20), nullable=False),

        sa.Column('category', sa.String(20), nullable=False),
        sa.Column('provider', sa.String(120), nullable=False),
        sa.Column('bill_reference_number', sa.String(50), nullable=False),
        sa.Column('purpose', sa.String(20), nullable=False),
        sa.Column('purpose_note', sa.String(200), nullable=True),

        sa.Column('bill_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('fee_percent', sa.Numeric(5, 2), nullable=False),
        sa.Column('fee_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('gst_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('total_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('bank_display', sa.String(160), nullable=False),

        sa.Column('consent_at', mysql.DATETIME(fsp=6), nullable=False),
        sa.Column('disclosure_version', sa.String(20), nullable=False),
        sa.Column('otp_verified_at', mysql.DATETIME(fsp=6), nullable=True),

        sa.Column('transaction_id', sa.String(36), nullable=True),
        sa.Column('credit_transaction_id', sa.String(36), nullable=True),
        sa.Column('restore_credit_transaction_id', sa.String(36), nullable=True),
        sa.Column('available_after', sa.Numeric(12, 2), nullable=True),

        sa.Column('payout_provider', sa.String(20), nullable=True),
        sa.Column('payout_reference', sa.String(100), nullable=True),
        sa.Column('bank_utr', sa.String(50), nullable=True),
        sa.Column('payout_dispatched_at', mysql.DATETIME(fsp=6), nullable=True),
        sa.Column('completed_at', mysql.DATETIME(fsp=6), nullable=True),

        sa.Column('failure_code', sa.String(50), nullable=True),
        sa.Column('failure_reason', sa.String(500), nullable=True),

        sa.Column('idempotency_key', sa.String(64), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('device_uuid', sa.String(100), nullable=True),

        sa.Column('created_on', mysql.DATETIME(fsp=6), nullable=False),
        sa.Column('updated_on', mysql.DATETIME(fsp=6), nullable=False),

        sa.UniqueConstraint('idempotency_key', name='uq_bill_payments_idempotency'),
    )
    op.create_index('ix_bill_payments_reference', 'bill_payments', ['reference'],
                    unique=True)
    op.create_index('ix_bill_payments_user_id', 'bill_payments', ['user_id'])
    op.create_index('ix_bill_payments_credit_account_id', 'bill_payments',
                    ['credit_account_id'])
    op.create_index('ix_bill_payments_bank_account_id', 'bill_payments',
                    ['bank_account_id'])
    op.create_index('ix_bill_payments_transaction_id', 'bill_payments',
                    ['transaction_id'])
    op.create_index('ix_bill_payments_credit_transaction_id', 'bill_payments',
                    ['credit_transaction_id'])
    op.create_index('ix_bill_payments_payout_reference', 'bill_payments',
                    ['payout_reference'])
    op.create_index('ix_bill_payments_user_created', 'bill_payments',
                    ['user_id', 'created_on'])
    op.create_index('ix_bill_payments_status', 'bill_payments', ['status'])


def downgrade():
    # The table is dropped, but the ledger rows its draws posted are not: they
    # are append-only history of money that really moved (see a1f4c7b9de02).
    op.drop_table('bill_payments')
