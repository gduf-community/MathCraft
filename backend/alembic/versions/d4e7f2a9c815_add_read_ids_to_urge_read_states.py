"""add read_ids to urge_read_states

Revision ID: d4e7f2a9c815
Revises: a5c8e21f7b31
Create Date: 2026-11-03

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d4e7f2a9c815"
down_revision = "a5c8e21f7b31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("urge_read_states", sa.Column("read_ids", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("urge_read_states", "read_ids")
