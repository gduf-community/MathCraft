"""新增最小出题运行台账，不回填旧批次，不改动既有业务表。"""
from alembic import op
import sqlalchemy as sa

revision = "j5e6f7a8b901"
down_revision = "i4d5e6f7a890"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """仅增加空台账；资源关联保留 ID 快照，账号删除由 RESTRICT 保护。"""
    op.create_table(
        "ops_runs",
        sa.Column("run_id", sa.String(40), primary_key=True),
        sa.Column("entrypoint", sa.String(16), nullable=False),
        sa.Column("owner_user_id", sa.String(40),
                  sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("session_id", sa.String(40)),
        sa.Column("task_id", sa.String(40), unique=True),
        sa.Column("bank_id", sa.String(40), nullable=False),
        sa.Column("document_id", sa.String(40), nullable=False),
        sa.Column("batch_id", sa.String(40), unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("delivered_count", sa.Integer()),
        sa.Column("error_code", sa.String(32)),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("entrypoint IN ('conversation', 'parameterized')", name="ck_ops_entry"),
        sa.CheckConstraint(
            "status IN ('accepted', 'running', 'completed', 'failed', 'canceled', 'unknown')",
            name="ck_ops_status",
        ),
        sa.CheckConstraint(
            "requested_count > 0 AND requested_count = CAST(requested_count AS INTEGER)",
            name="ck_ops_requested",
        ),
        sa.CheckConstraint(
            "delivered_count IS NULL OR (delivered_count >= 0 "
            "AND delivered_count = CAST(delivered_count AS INTEGER))", name="ck_ops_delivered",
        ),
        sa.CheckConstraint(
            "length(run_id) BETWEEN 1 AND 40 AND length(owner_user_id) BETWEEN 1 AND 40 "
            "AND length(bank_id) BETWEEN 1 AND 40 AND length(document_id) BETWEEN 1 AND 40 "
            "AND (session_id IS NULL OR length(session_id) BETWEEN 1 AND 40) "
            "AND (task_id IS NULL OR length(task_id) BETWEEN 1 AND 40) "
            "AND (batch_id IS NULL OR length(batch_id) BETWEEN 1 AND 40)",
            name="ck_ops_identifiers",
        ),
        sa.CheckConstraint(
            "(entrypoint = 'conversation' AND session_id IS NOT NULL AND task_id IS NULL) "
            "OR (entrypoint = 'parameterized' AND session_id IS NULL)",
            name="ck_ops_context",
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND batch_id IS NOT NULL AND delivered_count IS NOT NULL "
            "AND started_at IS NOT NULL AND error_code IS NULL) "
            "OR (status <> 'completed' AND batch_id IS NULL)", name="ck_ops_batch",
        ),
        sa.CheckConstraint(
            "(status IN ('completed', 'failed', 'canceled') AND finished_at IS NOT NULL) "
            "OR (status IN ('accepted', 'running', 'unknown') AND finished_at IS NULL)",
            name="ck_ops_finished",
        ),
        sa.CheckConstraint(
            "(status <> 'accepted' OR started_at IS NULL) "
            "AND (status <> 'running' OR started_at IS NOT NULL)", name="ck_ops_started",
        ),
        sa.CheckConstraint(
            "(status IN ('accepted', 'running', 'unknown') AND delivered_count IS NULL) "
            "OR status = 'completed' OR (status IN ('failed', 'canceled') "
            "AND delivered_count IS NOT NULL AND delivered_count = 0)",
            name="ck_ops_count_evidence",
        ),
        sa.CheckConstraint(
            "(status IN ('accepted', 'running', 'completed') AND error_code IS NULL) "
            "OR (status = 'failed' AND error_code IS NOT NULL "
            "AND error_code IN ('NEED_CONFIRM', 'MODEL_ERROR', 'RETRIEVAL_ERROR', "
            "'GENERATION_ERROR', 'NO_PERSISTABLE_QUESTIONS', 'PERSISTENCE_ERROR', "
            "'TASK_SUBMISSION_ERROR', 'EXECUTION_ERROR')) "
            "OR (status = 'canceled' AND error_code IS NOT NULL AND error_code = 'USER_CANCELED') "
            "OR (status = 'unknown' AND error_code IS NOT NULL "
            "AND error_code IN ('EXECUTION_INTERRUPTED', 'OUTCOME_UNKNOWN'))", name="ck_ops_error",
        ),
        sa.CheckConstraint(
            "last_observed_at >= accepted_at "
            "AND (started_at IS NULL OR (started_at >= accepted_at "
            "AND last_observed_at >= started_at)) "
            "AND (finished_at IS NULL OR (finished_at >= accepted_at "
            "AND last_observed_at >= finished_at "
            "AND (started_at IS NULL OR finished_at >= started_at)))", name="ck_ops_time",
        ),
    )
    op.create_index("ix_ops_runs_time", "ops_runs", ["accepted_at", "run_id"])
    op.create_index("ix_ops_runs_owner_time", "ops_runs", ["owner_user_id", "accepted_at"])
    op.create_index("ix_ops_runs_status_time", "ops_runs", ["status", "accepted_at"])
    op.create_index("ix_ops_runs_session", "ops_runs", ["session_id"])


def downgrade() -> None:
    """拒绝静默丢弃非空运行历史；空台账可安全回退。"""
    if op.get_bind().execute(sa.text("SELECT 1 FROM ops_runs LIMIT 1")).first() is not None:
        raise RuntimeError("运行台账非空，须另行备份并明确处置后才能降级")
    op.drop_table("ops_runs")
