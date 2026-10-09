"""Restore EMI payment gateway and UPI fields

Some databases reached the current Alembic head without the fields introduced
by the earlier EMI payment migration. These columns are required by the ORM and
their absence breaks admin dashboard queries that count EMI payments.

Revision ID: f7c8a9d2e341
Revises: d8a1f3c5b724
Create Date: 2026-09-30

Originally revised c6f2a8d4e1b7, which d8a1f3c5b724 also revises - two heads,
and `flask db upgrade` refuses to run with two. It only adds what is missing,
so chaining it after d8a1f3c5b724 is safe on every database.
"""
import sqlalchemy as sa
from alembic import op

revision = 'f7c8a9d2e341'
down_revision = 'd8a1f3c5b724'
branch_labels = None
depends_on = None


PAYMENT_COLUMNS = (
    ('gateway_signature', sa.String(255)),
    ('upi_app', sa.String(30)),
    ('upi_vpa', sa.String(120)),
    ('upi_rrn', sa.String(50)),
)


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {
        column['name'] for column in inspector.get_columns('emi_payments')
    }
    for name, type_ in PAYMENT_COLUMNS:
        if name not in columns:
            op.add_column(
                'emi_payments', sa.Column(name, type_, nullable=True)
            )
            columns.add(name)

    indexes = {
        index['name'] for index in sa.inspect(op.get_bind()).get_indexes('emi_payments')
    }
    if 'ix_emi_payments_gateway_payment_id' not in indexes:
        op.create_index(
            'ix_emi_payments_gateway_payment_id', 'emi_payments',
            ['gateway_payment_id'], unique=True,
        )
    if 'ix_emi_payments_upi_rrn' not in indexes:
        op.create_index(
            'ix_emi_payments_upi_rrn', 'emi_payments', ['upi_rrn'],
        )


def downgrade():
    indexes = {
        index['name'] for index in sa.inspect(op.get_bind()).get_indexes('emi_payments')
    }
    if 'ix_emi_payments_upi_rrn' in indexes:
        op.drop_index('ix_emi_payments_upi_rrn', table_name='emi_payments')
    if 'ix_emi_payments_gateway_payment_id' in indexes:
        op.drop_index(
            'ix_emi_payments_gateway_payment_id', table_name='emi_payments'
        )

    columns = {
        column['name'] for column in sa.inspect(op.get_bind()).get_columns('emi_payments')
    }
    for name, _ in reversed(PAYMENT_COLUMNS):
        if name in columns:
            op.drop_column('emi_payments', name)