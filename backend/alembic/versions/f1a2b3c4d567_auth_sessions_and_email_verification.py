"""增加可撤销认证与邮箱验证，保留用户 ID 和全部资源外键。

Revision ID: f1a2b3c4d567
Revises: e8b3c6d92a47
"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d567"
down_revision = "e8b3c6d92a47"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """先审计冲突再增加兼容字段；绝不自动验证历史邮箱。"""
    connection = op.get_bind()
    duplicate = connection.execute(sa.text(
        "SELECT 1 FROM users WHERE email IS NOT NULL AND trim(email) != '' "
        "GROUP BY lower(trim(email)) HAVING count(*) > 1 LIMIT 1"
    )).first()
    role_error = connection.execute(sa.text(
        "SELECT 1 FROM users WHERE role NOT IN ('teacher', 'student') "
        "OR identity != CASE WHEN role = 'teacher' THEN '教师' ELSE '学生' END LIMIT 1"
    )).first()
    number_error = connection.execute(sa.text(
        "SELECT 1 FROM users WHERE user_no IS NOT NULL AND trim(user_no) != '' "
        "GROUP BY trim(user_no) HAVING count(*) > 1 LIMIT 1"
    )).first()
    if duplicate or role_error or number_error:
        raise RuntimeError("历史账号存在邮箱/学工号冲突或角色异常，须按迁移清单处理后重试")
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email_normalized", sa.String(128), nullable=True))
        batch.add_column(sa.Column("email_verified", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
        batch.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))
        batch.create_unique_constraint("uq_users_email_normalized", ["email_normalized"])
    connection.execute(sa.text(
        "UPDATE users SET email_normalized = lower(trim(email)) "
        "WHERE email IS NOT NULL AND trim(email) != ''"
    ))
    connection.execute(sa.text(
        "UPDATE users SET user_no = NULLIF(trim(user_no), '')"
    ))
    op.create_table("auth_sessions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("refresh_digest", sa.String(64), unique=True, nullable=False))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_table("auth_refresh_uses",
        sa.Column("digest", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(40), sa.ForeignKey("auth_sessions.id"), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False))
    op.create_index("ix_auth_refresh_uses_session_id", "auth_refresh_uses", ["session_id"])
    op.create_table("auth_proofs",
        sa.Column("challenge_id", sa.String(64), primary_key=True),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("consumed_at", sa.Integer(), nullable=False))
    op.create_table("auth_email_changes",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("user_id", sa.String(40), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("old_email", sa.String(128), nullable=False),
        sa.Column("new_email", sa.String(128), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False))
    op.create_index("ix_auth_email_changes_user_id", "auth_email_changes", ["user_id"])
    # 旧用户 email_verified=False：拥有者必须受控核验，未完成前禁止发布。


def downgrade() -> None:
    for table in ("auth_email_changes", "auth_proofs", "auth_refresh_uses", "auth_sessions"):
        op.drop_table(table)
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_email_normalized", type_="unique")
        batch.drop_column("auth_version")
        batch.drop_column("email_verified_at")
        batch.drop_column("email_verified")
        batch.drop_column("email_normalized")
