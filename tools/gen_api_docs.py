"""从当前 OpenAPI 生成完整接口索引，拒绝遗漏或历史替身说明。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def main() -> int:
    """按真实接口标签输出全部 HTTP 契约入口。"""
    spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    groups: dict[str, list[str]] = {}
    count = 0
    for path, operations in sorted(spec["paths"].items()):
        for method, operation in sorted(operations.items()):
            if method not in METHODS:
                continue
            tag = next(iter(operation.get("tags", [])), "其他")
            summary = (operation.get("summary") or "").replace("|", "\\|")
            groups.setdefault(tag, []).append(
                f"| `{method.upper()}` | `{path}` | {summary} |"
            )
            count += 1
    parts = [
        "# MathCraft API\n\n",
        "本文件由根目录 `openapi.json` 自动生成；运行时契约以 `/openapi.json` 和 `/docs` 为准。\n\n",
        "后端入口为 `app.main:app`，示例地址 `http://127.0.0.1:8000`。",
        "除健康检查及公开认证流程外，受保护 HTTP 接口使用 `Authorization: Bearer <access_token>`；",
        "刷新要求 HttpOnly Cookie、可信 Origin 和 `X-CSRF-Token`；",
        "退出另外要求本标签的 `Authorization`，仅撤销该访问令牌绑定的会话，",
        "不清除其他会话的共享 Cookie。\n\n",
        "认证、资料字段、错误响应以 OpenAPI schema 为准，不再使用历史单用户设置接口。",
        "完整认证与迁移约定见 [用户系统实施规格](design/用户系统实施规格.md) 和",
        "[认证设计](design/用户系统功能规格.md)。\n\n",
        "模型凭据使用 `/api/users/me/model-settings`，知识库资料使用 `/api/banks`；",
        "旧 `/api/settings` 与 `/api/knowledge-bases` 不属于当前后端契约。",
        "平台模型与检索通过管理员专用 `/api/admin/rag-settings` 维护；",
        "嵌入模型或地址变更先保存待应用值，另行提交重建后才切换，",
        "使用方法见 [设置拆分与保存反馈设计](design/设置拆分与保存反馈设计.md)。",
        "配置优先级、保存与测试规则见 [模型配置与入库流程](design/模型配置来源与普通知识库流程.md)，",
        "权限、完成情况及验收边界见 [知识库模块说明](design/知识库模块说明.md) 和",
        "[扫描 PDF 策略](design/扫描PDF云端OCR策略.md)。\n\n",
        "删除资料或题库时，SQLite 写锁有限重试耗尽返回 `503 DATABASE_BUSY`；",
        "向量存储故障返回 `503 VECTOR_STORE_UNAVAILABLE`，两者均保留 SQL 记录与原件。",
        "失败状态或零切片计数不能作为跳过向量清理的依据。\n\n",
        "对话支持快速出题、创新命题、知识答疑和数据管理四种模式；",
        "图片与数据操作确认的契约和边界见",
        "[四模式对话与主线整合](design/对话四模式与主线整合.md)。\n\n",
        "运维五个 `/api/admin/ops/*` 接口仍待实现，不属于当前 OpenAPI。",
        "设计字段、采集接点及题目版本／审核范围见",
        "[运维联调契约](design/运维后台接口与联调契约.md)，",
        "接口负责人见[三人实施分工方案](design/运维后台三人实施分工方案.md)，",
        "部署和值守见[运行手册](design/运维后台运行手册.md)；",
        "G0／G1／G3 尚未通过，本轮仅更新说明入口。\n\n",
        "2026-11-12 前端已先行补全可选自监控、每题最终版本／审核范围证据、",
        "详情重出配置及告警指引／配置，准确字段见",
        "[联调契约第 1.2 节](design/运维后台接口与联调契约.md#12-2026-11-12-前端先行扩展待-g1-冻结)。",
        "新增前端及合成交互已完成，新增前端检查及独立复审已通过；",
        "真实授权审计和后端联调待完成。真实 async openTrace 固定 not_integrated，",
        "正文入口关闭；本次未新增后端或审计 API，未修改／重新生成 OpenAPI 或本文件的接口正文。\n\n",
    ]
    for tag, rows in groups.items():
        parts.append(f"## {tag}\n\n| 方法 | 路径 | 说明 |\n| --- | --- | --- |\n")
        parts.append("\n".join(rows) + "\n\n")
    parts.append(f"共 {count} 个 HTTP 操作。WebSocket 契约与启动配置见根目录 README。\n")
    (ROOT / "docs" / "api.md").write_text("".join(parts), encoding="utf-8")
    print(f"已生成 docs/api.md，覆盖 {count} 个 HTTP 操作")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
