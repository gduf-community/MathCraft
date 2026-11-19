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
        "个人 DeepSeek 连接测试与出题任务进度仅返回固定脱敏错误提示。",
        "个人模型设置的 `mineru_using_default` 仅在未配置个人 Token 且服务端默认 Token 存在时为真，",
        "不代表凭据已通过鉴权；两者均缺失时连接测试返回 `400 MINERU_TOKEN_MISSING`，不发起外部请求。",
        "检索仅发布 ready 文档；`hybrid` 只融合向量与稀疏结果，",
        "`hybrid_rerank` 另行调用重排。修复与验收记录见",
        "[设置设计](design/设置拆分与保存反馈设计.md#模型配置与检索审查修复2026-11-14)。\n\n",
        "删除资料或题库时，SQLite 写锁有限重试耗尽返回 `503 DATABASE_BUSY`；",
        "向量存储故障返回 `503 VECTOR_STORE_UNAVAILABLE`。登记持久删除意图后资源进入 `deleting`，",
        "登记意图后的向量故障仍可能返回 `503 VECTOR_STORE_UNAVAILABLE`；",
        "文件等后续清理未完成返回 `503 DELETION_PENDING`。两者均保留恢复记录，",
        "可重试并在启动时恢复；完整清理才返回 204。",
        "失败状态或零切片计数不能作为跳过向量清理的依据。",
        "试卷关闭、历史作答保留、任务持久化与删除边界见",
        "[数据一致性与故障恢复设计](design/数据一致性与故障恢复设计.md)。\n\n",
        "单 worker 启动恢复将未完成的持久任务及运行中的会话标为 `interrupted`，",
        "同一事务将对应仍为 `accepted`/`running` 的台账标为 `unknown`，",
        "错误码为 `EXECUTION_INTERRUPTED`；无持久任务或会话关联的历史台账不被扫描。\n\n",
        "对话支持快速出题、创新命题、知识答疑和数据管理四种模式。",
        "对话消息携带 request_id 时可按轮次暂停与查询结果；",
        "参数化异步出题支持 request_id 幂等受理、按任务取消及执行退出确认；",
        "取消中仍占用生成门禁，一键清空的完整语义见",
        "[快速出题取消与清空](implementation/快速出题取消与清空.md)。",
        "图片与数据操作确认的契约和边界见",
        "[四模式对话与主线整合](design/对话四模式与主线整合.md)。\n\n",
        "运维 V2 提供管理员只读概览、运行列表及基本详情，响应 `schema_version` 为 `v2`。",
        "查询仅投影正式 SQL 台账，支持受理时间、账号、入口、状态及会话／任务／批次筛选，",
        "列表使用 `limit`/`offset`；未知与空值保留，不返回正文或质量结论。",
        "`from`/`to` 只接受带时区的 ISO 8601 字符串；数字时间戳、无效日期及 UTC 范围溢出返回 ",
        "`422 VALIDATION_ERROR`。SQLAlchemy Enum 结果解码失败返回 ",
        "`503 OPS_DATA_UNAVAILABLE`，不回显内部值或 SQL。",
        "`error_code` 仅展示已确认的 RunErrorCode 安全分类；未知值显示 `UNKNOWN`，",
        "无错误保留 `null`，旧分类和自由文本不直接透传。",
        "正式模型、增量迁移和两类出题入口已在 V2 分支与查询层整合；部署须先核验并升级迁移，",
        "表缺失、契约不兼容或读取失败返回 `503 OPS_DATA_UNAVAILABLE`，不回退合成数据。",
        "前端 V2 适配及隔离页面联调已完成，合并后及部署仍需验收。完整字段、错误和交接边界见",
        "[运维查询 V2 接口与查询设计](design/运维查询V2接口与查询设计.md)，",
        "职责见[三人分工](implementation/运维后台三人实施分工方案.md)。",
        "依赖监测、告警、质量统计、复杂清理、自监控和正文审计不属于当前接口范围。\n\n",
        "[Phoenix 可选扩展](design/Phoenix可选扩展.md)使用普通 OpenAI 客户端手工导出 OTLP 元数据，",
        "默认关闭，不引入 Agent SDK，不采集正文，不新增业务 HTTP 契约；",
        "其可用性不作为运维查询的前置条件。\n\n",
    ]
    for tag, rows in groups.items():
        parts.append(f"## {tag}\n\n| 方法 | 路径 | 说明 |\n| --- | --- | --- |\n")
        parts.append("\n".join(rows) + "\n\n")
    parts.append(f"共 {count} 个 HTTP 操作。WebSocket 契约与启动配置见根目录 README。\n")
    (ROOT / "docs" / "api.md").write_text("".join(parts), encoding="utf-8", newline="\n")
    print(f"已生成 docs/api.md，覆盖 {count} 个 HTTP 操作")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
