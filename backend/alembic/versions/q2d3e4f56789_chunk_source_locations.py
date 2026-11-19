"""为文档切片保存 OCR 来源位置。"""

import sqlalchemy as sa
from alembic import op

revision = "q2d3e4f56789"
down_revision = "p1c2d3e45678"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增可空来源列，保留已有切片。"""
    op.add_column(
        "document_chunks",
        sa.Column("source_locations", sa.JSON(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    """移除来源列，保留切片正文和索引。"""
    with op.batch_alter_table("document_chunks") as batch:
        batch.drop_column("source_locations")
