"""校验运行时 OpenAPI、受版本管理契约与 V2 的最小公开字段。"""
import json
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[2]
OPS_PATHS = {
    "/api/admin/ops/overview": "OpsOverview",
    "/api/admin/ops/runs": "OpsRuns",
    "/api/admin/ops/runs/{run_id}": "OpsRunDetail",
}


def test_runtime_openapi_contract(tmp_path):
    """生成只读契约产物；不调用 lifespan、真实数据库或业务入口。"""
    schema = app.openapi()
    assert {p for p in schema["paths"] if p.startswith("/api/admin/ops")} == set(OPS_PATHS)
    for path, response in OPS_PATHS.items():
        operation = schema["paths"][path]["get"]
        responses = operation["responses"]
        assert responses["200"]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{response}",
        }
        for status in ("401", "403", "422", "503"):
            assert responses[status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse",
            }
    run = schema["components"]["schemas"]["OpsRun"]
    assert run["properties"]["status"]["enum"] == [
        "accepted", "running", "completed", "failed", "canceled", "unknown",
    ]
    assert set(run["properties"]) == {
        "run_id", "entrypoint", "owner_user_id", "session_id", "task_id", "bank_id",
        "document_id", "batch_id", "status", "requested_count", "delivered_count",
        "error_code", "accepted_at", "started_at", "finished_at", "last_observed_at",
    }
    assert {"type": "null"} in run["properties"]["finished_at"]["anyOf"]
    assert run["additionalProperties"] is False
    parameters = schema["paths"]["/api/admin/ops/runs"]["get"]["parameters"]
    assert {p["name"] for p in parameters if p["in"] == "query"} == {
        "from", "to", "owner_user_id", "entrypoint", "status", "session_id", "task_id",
        "batch_id", "limit", "offset",
    }
    # 外部隔离执行器可复制此产物更新版本库；测试本身不修改仓库文件。
    (tmp_path / "ops-openapi.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


def test_checked_in_openapi_matches_runtime():
    checked_in = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    assert checked_in == app.openapi()


def test_api_index_covers_new_operations_and_drops_deleted_contract_links():
    document = (ROOT / "docs/api.md").read_text(encoding="utf-8")
    for path in OPS_PATHS:
        assert f"| `GET` | `{path}` |" in document
    assert "运维后台接口与联调契约.md" not in document
    assert "运维查询V2实现与交接.md" in document
