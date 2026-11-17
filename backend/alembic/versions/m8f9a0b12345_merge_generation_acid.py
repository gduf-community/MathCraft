"""合并正文证据、出题运行与 ACID 恢复迁移历史。"""

revision = "m8f9a0b12345"
down_revision = ("k6f7a8b90123", "j5e6f7a8b901")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """两个父迁移已分别完成结构变更。"""


def downgrade() -> None:
    """仅拆分迁移分支，不删除数据。"""
