"""difficulty score float and review detail

Revision ID: e3b7c1d94a62
Revises: d9f4a2c7e815
Create Date: 2026-11-07

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e3b7c1d94a62"
down_revision = "d9f4a2c7e815"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 盲评加权总分带小数，另存命题蓝图与评审明细
    with op.batch_alter_table("questions") as batch:
        batch.alter_column(
            "difficulty_score",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
            existing_server_default="0",
            server_default="0",
        )
        batch.add_column(sa.Column("blueprint_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("review_json", sa.Text(), nullable=True))
    with op.batch_alter_table("paper_questions") as batch:
        batch.alter_column(
            "difficulty_score",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
            existing_server_default="0",
            server_default="0",
        )


def downgrade() -> None:
    with op.batch_alter_table("paper_questions") as batch:
        batch.alter_column(
            "difficulty_score",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
            existing_server_default="0",
            server_default="0",
        )
    with op.batch_alter_table("questions") as batch:
        batch.drop_column("review_json")
        batch.drop_column("blueprint_json")
        batch.alter_column(
            "difficulty_score",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=False,
            existing_server_default="0",
            server_default="0",
        )
