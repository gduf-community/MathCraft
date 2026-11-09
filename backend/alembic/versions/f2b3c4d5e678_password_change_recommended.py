"""持久化管理员初始密码与重置后的非强制改密提醒。"""
from alembic import op
import sqlalchemy as sa

revision = "f2b3c4d5e678"
down_revision = "g2b3c4d5e678"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """历史账号默认不提醒；以后管理员建号或重置时显式设置。"""
    op.add_column("users", sa.Column(
        "password_change_recommended", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))


def downgrade() -> None:
    """仅移除提醒字段，不改变密码、认证版本或账号归属。"""
    with op.batch_alter_table("users") as batch:
        batch.drop_column("password_change_recommended")
