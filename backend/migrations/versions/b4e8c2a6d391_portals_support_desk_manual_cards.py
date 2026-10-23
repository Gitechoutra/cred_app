"""Support desk fields, manual cards and card themes

- support_tickets: escalation to administrators (escalated, escalated_at,
  escalated_by, escalation_reason). assigned_agent_id already exists.
- support_messages: is_internal, for staff-only notes.
- manual_cards: cards the holder tracks with figures they type in, labelled
  User-entered - Not Bank Verified. Money is DECIMAL(14,2).
- cards: card_theme, a visual preference only.

Additive only: nothing is dropped or rewritten. Every step checks first, so
it is safe on a database that create_all() already brought up to date.

Revision ID: b4e8c2a6d391
Revises: a3d7e5c2b918
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'b4e8c2a6d391'
down_revision = 'a3d7e5c2b918'
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table):
    return {c['name'] for c in _inspector().get_columns(table)}


def _add(table, column):
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade():
    _add('support_tickets', sa.Column('escalated', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    _add('support_tickets', sa.Column('escalated_at', sa.DateTime(), nullable=True))
    _add('support_tickets', sa.Column('escalated_by', sa.String(36), nullable=True))
    _add('support_tickets', sa.Column('escalation_reason', sa.String(500), nullable=True))
    if 'ix_support_tickets_escalated' not in {
            i['name'] for i in _inspector().get_indexes('support_tickets')}:
        op.create_index('ix_support_tickets_escalated', 'support_tickets', ['escalated'])

    _add('support_messages', sa.Column('is_internal', sa.Boolean(), nullable=False,
                                       server_default=sa.false()))

    _add('cards', sa.Column('card_theme', sa.String(20), nullable=True))

    if 'manual_cards' not in _inspector().get_table_names():
        op.create_table(
            'manual_cards',
            sa.Column('manual_card_id', sa.CHAR(36), primary_key=True),
            sa.Column('user_id', sa.CHAR(36), sa.ForeignKey('users.user_id'),
                      nullable=False),
            sa.Column('issuer_bank', sa.String(150), nullable=False),
            sa.Column('issuer_id', sa.String(40), nullable=True),
            sa.Column('nickname', sa.String(100), nullable=True),
            sa.Column('network', sa.String(20), nullable=False),
            sa.Column('last4', sa.String(4), nullable=False),
            sa.Column('credit_limit', sa.Numeric(14, 2), nullable=True),
            sa.Column('outstanding_balance', sa.Numeric(14, 2), nullable=True),
            sa.Column('available_credit', sa.Numeric(14, 2), nullable=True),
            sa.Column('statement_day', sa.Integer(), nullable=True),
            sa.Column('payment_due_date', sa.Date(), nullable=True),
            sa.Column('minimum_due', sa.Numeric(14, 2), nullable=True),
            sa.Column('total_due', sa.Numeric(14, 2), nullable=True),
            sa.Column('theme', sa.String(20), nullable=False, server_default='AUTO'),
            sa.Column('status', sa.String(10), nullable=False, server_default='ACTIVE'),
            sa.Column('removed_at', sa.DateTime(), nullable=True),
            sa.Column('figures_updated_at', sa.DateTime(), nullable=True),
            sa.Column('created_on', sa.DateTime(), nullable=False),
            sa.Column('updated_on', sa.DateTime(), nullable=False),
        )
        op.create_index('ix_manual_cards_user_id', 'manual_cards', ['user_id'])
        op.create_index('ix_manual_cards_user_status', 'manual_cards',
                        ['user_id', 'status'])
        op.create_index('ix_manual_cards_user_issuer_last4', 'manual_cards',
                        ['user_id', 'issuer_bank', 'last4'])


def downgrade():
    if 'manual_cards' in _inspector().get_table_names():
        op.drop_table('manual_cards')
    for table, column in [('cards', 'card_theme'),
                          ('support_messages', 'is_internal'),
                          ('support_tickets', 'escalation_reason'),
                          ('support_tickets', 'escalated_by'),
                          ('support_tickets', 'escalated_at')]:
        if column in _columns(table):
            op.drop_column(table, column)
    if 'ix_support_tickets_escalated' in {
            i['name'] for i in _inspector().get_indexes('support_tickets')}:
        op.drop_index('ix_support_tickets_escalated', 'support_tickets')
    if 'escalated' in _columns('support_tickets'):
        op.drop_column('support_tickets', 'escalated')
