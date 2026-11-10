"""新增平台检索配置及索引版本状态，旧 collection 与资源归属保持原样。"""
from alembic import op
import sqlalchemy as sa

revision = "i4d5e6f7a890"
down_revision = "h3c4d5e6f789"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """默认空配置沿用部署模型和原 kb_* 索引，不复制历史秘密配置。"""
    op.create_table(
        "rag_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("pending_json", sa.Text()),
        sa.Column("generation", sa.String(24), nullable=False, server_default=""),
        sa.Column("rebuild_id", sa.String(40)),
        sa.Column("rebuild_status", sa.String(16), nullable=False, server_default="idle"),
        sa.Column("rebuild_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rebuild_stage", sa.String(255), nullable=False, server_default="尚未重建"),
        sa.Column("rebuild_error", sa.Text()),
        sa.Column("mutation_epoch", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(sa.text("INSERT INTO rag_settings (id) VALUES (1)"))


def downgrade() -> None:
    """仅在已恢复旧模型与旧索引后降级；不删除 Chroma 中的任意索引版本。"""
    connection = op.get_bind()
    row = connection.execute(sa.text(
        "SELECT generation, rebuild_status FROM rag_settings WHERE id=1"
    )).first()
    if row and (row.generation or row.rebuild_status in ("queued", "running")):
        raise RuntimeError("索引已切换或正在重建，须先恢复旧模型与索引再降级")
    op.drop_table("rag_settings")
