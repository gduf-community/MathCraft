"""add paper_urges and urge_read_states

Revision ID: a5c8e21f7b31
Revises: 7dc07287e5a4
Create Date: 2026-11-03

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a5c8e21f7b31"
down_revision = "7dc07287e5a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_urges",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("paper_id", sa.String(length=40), nullable=False),
        sa.Column("space_id", sa.String(length=40), nullable=False),
        sa.Column("teacher_id", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["papers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["space_id"], ["study_spaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_paper_urges_paper_id", "paper_urges", ["paper_id"])
    op.create_index("ix_paper_urges_space_id", "paper_urges", ["space_id"])

    op.create_table(
        "urge_read_states",
        sa.Column("user_id", sa.String(length=40), nullable=False),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("urge_read_states")
    op.drop_index("ix_paper_urges_space_id", table_name="paper_urges")
    op.drop_index("ix_paper_urges_paper_id", table_name="paper_urges")
    op.drop_table("paper_urges")
