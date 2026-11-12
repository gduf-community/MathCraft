"""Small authenticated client restricted to this isolated Phoenix instance."""

import json
from datetime import UTC, datetime, timedelta

import httpx

from .environment import HOME

BASE_URL = "http://127.0.0.1:6016"


class Phoenix:
    """Never exposes headers, keys, response bodies or raw HTTP exceptions in errors."""

    def __init__(self) -> None:
        private = json.loads((HOME / "private.json").read_text(encoding="utf-8"))
        self.key: str = private["admin_secret"]
        self.client = httpx.Client(
            base_url=BASE_URL,
            timeout=10,
            trust_env=False,
            headers={"Authorization": "Bearer " + self.key},
        )

    def request(self, method: str, path: str, **kwargs: object) -> dict:
        """Call fixed local public APIs; fail without echoing server details."""
        if not path.startswith(("/v1/", "/graphql")) or "://" in path:
            raise ValueError("Only isolated Phoenix public API paths are allowed")
        response = self.client.request(method, path, **kwargs)
        if not response.is_success:
            raise RuntimeError(f"Phoenix API status {response.status_code}")
        if response.status_code == 204:
            return {}
        return response.json()

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        """Execute a supported schema operation and surface only error presence."""
        result = self.request(
            "POST", "/graphql", json={"query": query, "variables": variables or {}}
        )
        if result.get("errors"):
            raise RuntimeError("Phoenix GraphQL operation failed; inspect its schema")
        return result["data"]

    def export_key(self) -> str:
        """Bootstrap one expiring system key and keep it only in ignored configuration."""
        path = HOME / "private.json"
        private = json.loads(path.read_text(encoding="utf-8"))
        if "export_key" not in private:
            result = self.request(
                "POST",
                "/v1/system/api_keys",
                json={
                    "data": {
                        "name": "isolated-g0-export",
                        "description": "Synthetic preparation only",
                        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
                    }
                },
            )["data"]
            private["export_key"] = result["key"]
            private["export_key_id"] = result["id"]
            path.write_text(json.dumps(private, indent=2), encoding="utf-8")
        return private["export_key"]

    def close(self) -> None:
        """Release the dedicated HTTP connection pool."""
        self.client.close()
