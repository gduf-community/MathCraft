"""合并账号安全与出题审核迁移分支，保留两侧已发布版本标识。"""

revision = "h3c4d5e6f789"
down_revision = ("f2b3c4d5e678", "e3b7c1d94a62")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """两侧结构已由各自迁移完成，此合并节点只统一版本图。"""


def downgrade() -> None:
    """只恢复两个分支的版本标记，不修改账号或业务数据。"""
