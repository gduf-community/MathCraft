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
        "刷新与退出使用 HttpOnly Cookie、可信 Origin 和 `X-CSRF-Token`。\n\n",
        "认证、资料字段、错误响应以 OpenAPI schema 为准，不再使用历史单用户设置接口。",
        "完整认证与迁移约定见 [用户系统实施规格](design/用户系统实施规格.md) 和",
        "[认证设计](design/用户系统功能规格.md)。\n\n",
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