"""增加试卷关闭和作答快照、持久任务及跨存储删除恢复记录。"""
import json

from alembic import op
import sqlalchemy as sa

revision = "j5e6f7a8b901"
down_revision = "i4d5e6f7a890"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增量保留历史行，并为旧作答固定当前试卷题目顺序。"""
    op.add_column("papers", sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("papers", sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("paper_questions", sa.Column(
        "removed", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column("paper_attempts", sa.Column("question_ids_json", sa.Text()))
    op.add_column("paper_attempts", sa.Column("grading_run_id", sa.String(40)))
    connection = op.get_bind()
    questions: dict[str, list[str]] = {}
    for row in connection.execute(sa.text(
        "SELECT paper_id, id FROM paper_questions ORDER BY paper_id, order_no",
    )):
        questions.setdefault(row.paper_id, []).append(row.id)
    for paper_id, question_ids in questions.items():
        connection.execute(sa.text(
            "UPDATE paper_attempts SET question_ids_json=:snapshot WHERE paper_id=:paper_id",
        ), {"snapshot": json.dumps(question_ids), "paper_id": paper_id})
    connection.execute(sa.text(
        "UPDATE paper_attempts SET question_ids_json='[]' WHERE question_ids_json IS NULL",
    ))
    for name, column_type, default in (
        ("mode", sa.String(16), None), ("pending_message", sa.Text(), None),
        ("pending_images_json", sa.Text(), None), ("run_id", sa.String(40), None),
        ("canceled_run_id", sa.String(40), None), ("run_status", sa.String(16), "idle"),
        ("run_progress", sa.Integer(), "0"), ("run_stage", sa.String(256), ""),
    ):
        op.add_column("chat_sessions", sa.Column(
            name, column_type, nullable=default is None, server_default=default,
        ))
    # 旧模式、待续图片与运行状态仅在 Redis；保留 SQL 快照并明确要求重输。
    # 不连接 Redis、不迁移凭据，也不恢复任何旧模型运行。
    connection.execute(sa.text(
        "UPDATE chat_sessions SET run_status='interrupted', "
        "run_stage='服务已升级，旧待续需求请重新发送文字和图片'",
    ))
    op.create_table(
        "generation_tasks",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bank_id", sa.String(40), nullable=False),
        sa.Column("document_id", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("run_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(256), nullable=False),
        sa.Column("batch_id", sa.String(40)),
        sa.Column("result_json", sa.Text()),
        sa.Column("review_json", sa.Text()),
        sa.Column("error_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_generation_tasks_owner_status", "generation_tasks", ["user_id", "status"])
    op.create_table(
        "deletion_operations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("resource_id", sa.String(40), nullable=False),
        sa.Column("bank_id", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("generation", sa.String(64), nullable=False),
        sa.Column("paths_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("resource_type", "resource_id", name="uq_deletion_resource"),
    )
    op.create_index("ix_deletion_operations_bank_id", "deletion_operations", ["bank_id"])
    op.create_index("ix_deletion_operations_status", "deletion_operations", ["status"])


def downgrade() -> None:
    """存在新语义数据时拒绝有损降级，避免删除历史或恢复线索。"""
    connection = op.get_bind()
    for query in (
        "SELECT 1 FROM generation_tasks LIMIT 1",
        "SELECT 1 FROM deletion_operations LIMIT 1",
        "SELECT 1 FROM papers WHERE deleted = true LIMIT 1",
        "SELECT 1 FROM papers WHERE closed = true LIMIT 1",
        "SELECT 1 FROM paper_questions WHERE removed = true LIMIT 1",
        "SELECT 1 FROM paper_attempts WHERE status = 'grading' LIMIT 1",
        "SELECT 1 FROM chat_sessions WHERE mode IS NOT NULL "
        "OR pending_message IS NOT NULL "
        "OR (pending_images_json IS NOT NULL AND pending_images_json <> '[]') "
        "OR run_id IS NOT NULL OR canceled_run_id IS NOT NULL "
        "OR run_status <> 'idle' OR run_progress <> 0 OR run_stage <> '' LIMIT 1",
    ):
        if connection.execute(sa.text(query)).first():
            raise RuntimeError("存在持久任务、对话状态、删除恢复或历史快照数据，拒绝有损降级")
    op.drop_table("deletion_operations")
    op.drop_table("generation_tasks")
    for name in (
        "mode", "pending_message", "pending_images_json", "run_id", "canceled_run_id",
        "run_status", "run_progress", "run_stage",
    ):
        op.drop_column("chat_sessions", name)
    op.drop_column("paper_attempts", "grading_run_id")
    op.drop_column("paper_attempts", "question_ids_json")
    op.drop_column("paper_questions", "removed")
    op.drop_column("papers", "deleted")
    op.drop_column("papers", "closed")
