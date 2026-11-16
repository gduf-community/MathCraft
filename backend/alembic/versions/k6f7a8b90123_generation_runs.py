"""新增出题质量运行与续跑检查点。"""
from alembic import op
import sqlalchemy as sa

revision = "k6f7a8b90123"
down_revision = "j5e6f7a89012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_runs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("user_id", sa.String(length=40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("bank_id", sa.String(length=40), nullable=False),
        sa.Column("document_id", sa.String(length=40), nullable=False),
        sa.Column("doc_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="parametric"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("params_json", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("requested_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("accepted_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("missing_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("rejected_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("evidence_json", sa.Text()),
        sa.Column("stop_reason", sa.String(length=64)),
        sa.Column("error_json", sa.Text()),
        sa.Column("batch_id", sa.String(length=40)),
        sa.Column("execution_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("repair_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refill_rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stalled_rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage", sa.String(length=255), nullable=False, server_default="任务已创建"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("generation_batches", sa.Column("run_id", sa.String(length=40)))
    op.create_index("ix_generation_batches_run_id", "generation_batches", ["run_id"])
    op.create_index("ix_generation_runs_user_id", "generation_runs", ["user_id"])
    op.create_index("ix_generation_runs_bank_id", "generation_runs", ["bank_id"])
    op.create_index("ix_generation_runs_document_id", "generation_runs", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_generation_batches_run_id", table_name="generation_batches")
    op.drop_column("generation_batches", "run_id")
    op.drop_index("ix_generation_runs_document_id", table_name="generation_runs")
    op.drop_index("ix_generation_runs_bank_id", table_name="generation_runs")
    op.drop_index("ix_generation_runs_user_id", table_name="generation_runs")
    op.drop_table("generation_runs")
