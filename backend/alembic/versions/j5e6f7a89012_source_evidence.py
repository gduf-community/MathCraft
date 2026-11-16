"""新增独立正文证据与 FTS，不改知识点切片和向量索引。"""

import sqlalchemy as sa
from alembic import op

revision = "j5e6f7a89012"
down_revision = "i4d5e6f7a890"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """仅创建新存储，历史资料在合法访问时从本地惰性恢复。"""
    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("bank_id", sa.String(40), sa.ForeignKey("banks.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("document_id", sa.String(40),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_role", sa.String(24), nullable=False),
        sa.Column("source_path", sa.String(1024)),
        sa.Column("doc_name", sa.String(255), nullable=False),
        sa.Column("capabilities_json", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "version", name="uq_source_snapshot_version"),
        sa.UniqueConstraint("id", "bank_id", "document_id", name="uq_source_snapshot_owner"),
        sa.CheckConstraint("version > 0", name="ck_source_snapshot_version"),
    )
    op.create_index("ix_source_snapshots_document", "source_snapshots", ["bank_id", "document_id"])
    op.create_index(
        "uq_source_snapshot_active", "source_snapshots", ["document_id"], unique=True,
        sqlite_where=sa.text("active = 1"), postgresql_where=sa.text("active = true"),
    )
    op.create_table(
        "source_blocks",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("snapshot_id", sa.String(40), nullable=False),
        sa.Column("bank_id", sa.String(40), sa.ForeignKey("banks.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("document_id", sa.String(40),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Text(), nullable=False),
        sa.Column("section", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("offset_start", sa.Integer(), nullable=False),
        sa.Column("offset_end", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "bank_id", "document_id"],
            ["source_snapshots.id", "source_snapshots.bank_id", "source_snapshots.document_id"],
            ondelete="CASCADE", name="fk_source_block_owner",
        ),
        sa.UniqueConstraint("snapshot_id", "block_order", name="uq_source_block_order"),
        sa.CheckConstraint("block_order >= 0", name="ck_source_block_order"),
        sa.CheckConstraint("offset_start >= 0 AND offset_end > offset_start",
                           name="ck_source_block_offsets"),
        sa.CheckConstraint("page IS NULL OR page > 0", name="ck_source_block_page"),
    )
    op.create_index("ix_source_blocks_scope", "source_blocks", ["snapshot_id", "section", "page"])
    op.execute("""CREATE VIRTUAL TABLE source_blocks_fts USING fts5(
        block_id UNINDEXED, snapshot_id UNINDEXED, bank_id UNINDEXED,
        document_id UNINDEXED, tokens, tokenize='unicode61')""")
    op.execute("""CREATE TRIGGER source_blocks_ai AFTER INSERT ON source_blocks BEGIN
        INSERT INTO source_blocks_fts(block_id, snapshot_id, bank_id, document_id, tokens)
        VALUES (new.id, new.snapshot_id, new.bank_id, new.document_id, new.tokens); END""")
    op.execute("""CREATE TRIGGER source_blocks_ad AFTER DELETE ON source_blocks BEGIN
        DELETE FROM source_blocks_fts WHERE block_id = old.id; END""")
    op.execute("""CREATE TRIGGER source_blocks_au AFTER UPDATE ON source_blocks BEGIN
        DELETE FROM source_blocks_fts WHERE block_id = old.id;
        INSERT INTO source_blocks_fts(block_id, snapshot_id, bank_id, document_id, tokens)
        VALUES (new.id, new.snapshot_id, new.bank_id, new.document_id, new.tokens); END""")


def downgrade() -> None:
    """显式降级仅删除正文证据，原文文件及旧检索存储不受影响。"""
    for name in ("source_blocks_ai", "source_blocks_ad", "source_blocks_au"):
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
    op.execute(sa.text("DROP TABLE IF EXISTS source_blocks_fts"))
    op.drop_table("source_blocks")
    op.drop_table("source_snapshots")
