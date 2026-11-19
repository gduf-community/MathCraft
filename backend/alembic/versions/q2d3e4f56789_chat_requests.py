"""持久化对话轮次状态、取消占位和已发布回复。"""

import sqlalchemy as sa
from alembic import op

revision = "q2d3e4f56789"
down_revision = "p1c2d3e45678"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """添加轮次表，保留已有的会话与消息。"""
    op.create_table(
        "chat_requests",
        sa.Column("session_id", sa.String(40), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(40)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("execution_finished_at", sa.DateTime(timezone=True)),
        sa.Column("batch_id", sa.String(40)),
        sa.Column("result_json", sa.Text()),
        sa.PrimaryKeyConstraint("session_id", "request_id"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("run_id"),
    )


def downgrade() -> None:
    """移除新增的轮次记录表。"""
    op.drop_table("chat_requests")
