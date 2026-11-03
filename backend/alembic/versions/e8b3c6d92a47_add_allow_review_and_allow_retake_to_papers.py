"""add allow_review and allow_retake to papers

Revision ID: e8b3c6d92a47
Revises: d4e7f2a9c815
Create Date: 2026-11-03

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e8b3c6d92a47"
down_revision = "d4e7f2a9c815"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("papers", sa.Column("allow_review", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("papers", sa.Column("allow_retake", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("papers", "allow_retake")
    op.drop_column("papers", "allow_review")
