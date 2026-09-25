"""Microsecond timestamps on credit transactions

MySQL's DATETIME stores whole seconds. utcnow() produces microseconds and MySQL
was throwing them away, so two purchases made in the same second had identical
created_on values and `ORDER BY created_on DESC` put them in an arbitrary order.
A cardholder who bought two things in quick succession saw them listed in the
wrong order, and a test that asserted the order failed roughly one run in three
- which is how this was found.

DATETIME(6) keeps the microseconds that were already being generated. No data
migration is needed: existing rows keep their whole-second values, which remain
correct, just less precise than the ones written from now on.

The query also gains credit_transaction_id as a final tiebreaker. Not because a
UUID says anything about time - it does not - but because pagination needs a
*total* order. Without one, two rows that compare equal can swap between the
request for page 1 and the request for page 2, which shows one row twice and
hides another entirely.

Revision ID: c3a8f5017bd2
Revises: b2e6d91c4a7f
Create Date: 2026-09-25
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision = 'c3a8f5017bd2'
down_revision = 'b2e6d91c4a7f'
branch_labels = None
depends_on = None

#: (table, column, nullable). Only the columns a list is ordered or filtered by
#: at sub-second resolution. Widening every DateTime in the schema would be
#: churn for no benefit.
COLUMNS = [
    ('credit_transactions', 'created_on', False),
    ('credit_transactions', 'updated_on', False),
    ('credit_transactions', 'settled_at', True),
]


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'credit_transactions' not in inspector.get_table_names():
        return

    for table, column, nullable in COLUMNS:
        op.alter_column(
            table, column,
            existing_type=mysql.DATETIME(),
            type_=mysql.DATETIME(fsp=6),
            existing_nullable=nullable,
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'credit_transactions' not in inspector.get_table_names():
        return

    # Narrowing truncates the microseconds. That loses precision but not
    # ordering correctness for any row written before this feature existed.
    for table, column, nullable in COLUMNS:
        op.alter_column(
            table, column,
            existing_type=mysql.DATETIME(fsp=6),
            type_=mysql.DATETIME(),
            existing_nullable=nullable,
        )
