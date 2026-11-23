"""为个人 DeepSeek 配置增加可选 Base URL。"""
from alembic import op
import sqlalchemy as sa


revision = "r3e4f5a67890"
down_revision = "p1c2d3e45678"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_model_settings",
        sa.Column("deepseek_base_url", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_model_settings", "deepseek_base_url")
