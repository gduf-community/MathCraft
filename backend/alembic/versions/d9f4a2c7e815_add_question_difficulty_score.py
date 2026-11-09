"""add question difficulty_score

Revision ID: d9f4a2c7e815
Revises: c3e8a1f5b279
Create Date: 2026-11-07

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "d9f4a2c7e815"
down_revision = "c3e8a1f5b279"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 出题中间件按 1~5 分评估难度，0 表示未评估（历史数据）
    op.add_column("questions", sa.Column("difficulty_score", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("paper_questions", sa.Column("difficulty_score", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("paper_questions", "difficulty_score")
    op.drop_column("questions", "difficulty_score")
