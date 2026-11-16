"""汇合平台模型配置与生成取消迁移，保留两条分支的历史数据。"""

revision = "p1c2d3e45678"
down_revision = ("o0b1c2d34567", "j5f6g7h8i900")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """仅汇合迁移图，父迁移已分别创建完整结构。"""


def downgrade() -> None:
    """恢复两个父版本标记，不删除业务数据。"""
