"""轮换可预测的历史空间加入码，保留空间与成员标识。"""
import re
import secrets

from alembic import op
import sqlalchemy as sa

revision = "g2b3c4d5e678"
down_revision = "f1a2b3c4d567"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """旧编号不再作为加入凭据，创建者从空间详情取得新码。"""
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, code FROM study_spaces")).all()
    used = {row.code for row in rows}
    for row in rows:
        if re.fullmatch(r"SP[0-9A-F]{24}", row.code):
            continue
        while True:
            code = "SP" + secrets.token_hex(12).upper()
            if code not in used:
                break
        used.add(code)
        connection.execute(sa.text("UPDATE study_spaces SET code=:code WHERE id=:id"),
                           {"code": code, "id": row.id})


def downgrade() -> None:
    """安全凭据轮换不可逆；回退应用时仍保留随机编号。"""
