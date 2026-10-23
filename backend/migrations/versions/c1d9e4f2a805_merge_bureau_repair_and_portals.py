"""Merge the bureau column repair with the portals migration

3eaa1c6847bf and b4e8c2a6d391 both follow a3d7e5c2b918. Joining them gives
Alembic a single head again, so flask db upgrade runs.

Revision ID: c1d9e4f2a805
Revises: 3eaa1c6847bf, b4e8c2a6d391
Create Date: 2026-10-23
"""

revision = 'c1d9e4f2a805'
down_revision = ('3eaa1c6847bf', 'b4e8c2a6d391')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
