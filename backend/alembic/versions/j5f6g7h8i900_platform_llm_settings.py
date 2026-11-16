"""新增平台级 LLM 默认凭据配置，API Key 静态加密存储（主密钥在 data/secret.key）。"""
from alembic import op
import sqlalchemy as sa

revision = "j5f6g7h8i900"
down_revision = "i4d5e6f7a890"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """默认空配置：不设置时沿用部署环境变量里的模型与地址。"""
    op.create_table(
        "platform_llm_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("encrypted_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("base_url", sa.String(255), nullable=False, server_default=""),
        sa.Column("model", sa.String(120), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(120), nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.execute(sa.text("INSERT INTO platform_llm_settings (id) VALUES (1)"))


def downgrade() -> None:
    op.drop_table("platform_llm_settings")
