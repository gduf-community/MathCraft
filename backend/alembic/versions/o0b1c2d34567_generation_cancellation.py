"""持久化快速任务请求身份与执行退出事实。"""
from alembic import op
import sqlalchemy as sa

revision = "o0b1c2d34567"
down_revision = "n9a0b1c23456"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """保留全部历史任务，只有历史终态被视为已经退出。"""
    op.add_column("generation_tasks", sa.Column("request_id", sa.String(36)))
    op.add_column("generation_tasks", sa.Column(
        "execution_finished_at", sa.DateTime(timezone=True),
    ))
    op.create_index("uq_generation_tasks_owner_request", "generation_tasks",
                    ["user_id", "request_id"], unique=True)
    op.execute(sa.text(
        "UPDATE generation_tasks SET execution_finished_at = updated_at "
        "WHERE status NOT IN ('queued', 'running', 'canceling')"
    ))


def downgrade() -> None:
    """拒绝丢弃新版本的任务身份、取消或执行结束事实。"""
    connection = op.get_bind()
    if connection.execute(sa.text(
        "SELECT 1 FROM generation_tasks WHERE request_id IS NOT NULL "
        "OR execution_finished_at IS NOT NULL OR status IN ('canceling', 'canceled') LIMIT 1"
    )).first():
        raise RuntimeError("出题任务含取消或执行退出事实，拒绝有损降级")
    op.drop_index("uq_generation_tasks_owner_request", table_name="generation_tasks")
    op.drop_column("generation_tasks", "execution_finished_at")
    op.drop_column("generation_tasks", "request_id")
