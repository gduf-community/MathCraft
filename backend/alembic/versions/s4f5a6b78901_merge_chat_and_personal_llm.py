"""合并聊天请求与个人 DeepSeek Base URL 两条迁移分支。"""

revision = "s4f5a6b78901"
down_revision = ("q2d3e4f56789", "r3e4f5a67890")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """仅合并迁移图，不修改业务数据。"""


def downgrade() -> None:
    """恢复两个父迁移标记，不删除业务数据。"""
