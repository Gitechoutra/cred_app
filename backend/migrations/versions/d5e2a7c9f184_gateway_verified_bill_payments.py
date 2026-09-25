"""Gateway-verified bill payments, declines, and available credit on record

A bill payment used to restore credit the moment the client said it had paid.
It now opens a gateway order first and waits in PROCESSING, touching no balance,
until the gateway's own record of the payment settles it. That needs somewhere
to keep the order and the payment the gateway knows it by.

Declined purchases are now recorded as FAILED rows, and every row carries the
credit that was available once it landed, because that is what the cardholder
was shown at the time.

Statements gain the limit and available credit at the moment the cycle closed,
for the same reason: both move with every spend, and an issued statement must
keep saying what it said.

Backfill: available_after is limit minus balance_after, floored at zero, which
is exactly what the engine would have written - limits have never changed on an
issued line, so the current limit is the historical one. Statements get the
limit and closing figure the same way.

Revision ID: d5e2a7c9f184
Revises: c3a8f5017bd2
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op

revision = 'd5e2a7c9f184'
down_revision = 'c3a8f5017bd2'
branch_labels = None
depends_on = None

TXN_COLUMNS = [
    ('available_after', sa.Numeric(12, 2)),
    ('payment_method', sa.String(20)),
    ('gateway_provider', sa.String(20)),
    ('gateway_order_id', sa.String(100)),
    ('gateway_payment_id', sa.String(100)),
    ('gateway_reference', sa.String(64)),
    ('target_statement_id', sa.String(36)),
]


def upgrade():
    for name, type_ in TXN_COLUMNS:
        op.add_column('credit_transactions', sa.Column(name, type_, nullable=True))
    op.create_index(
        'ix_credit_transactions_gateway_order_id', 'credit_transactions',
        ['gateway_order_id'],
    )

    op.add_column('credit_statements',
                  sa.Column('credit_limit', sa.Numeric(12, 2), nullable=True))
    op.add_column('credit_statements',
                  sa.Column('available_credit', sa.Numeric(12, 2), nullable=True))

    op.execute("""
        UPDATE credit_transactions t
        JOIN credit_accounts a ON a.credit_account_id = t.credit_account_id
        SET t.available_after = GREATEST(a.credit_limit - t.balance_after, 0)
        WHERE t.balance_after IS NOT NULL AND t.available_after IS NULL
    """)
    op.execute("""
        UPDATE credit_statements s
        JOIN credit_accounts a ON a.credit_account_id = s.credit_account_id
        SET s.credit_limit = a.credit_limit,
            s.available_credit = GREATEST(a.credit_limit - s.closing_balance, 0)
        WHERE s.credit_limit IS NULL
    """)


def downgrade():
    op.drop_column('credit_statements', 'available_credit')
    op.drop_column('credit_statements', 'credit_limit')
    op.drop_index('ix_credit_transactions_gateway_order_id',
                  table_name='credit_transactions')
    for name, _ in reversed(TXN_COLUMNS):
        op.drop_column('credit_transactions', name)
