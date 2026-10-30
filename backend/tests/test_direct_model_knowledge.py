"""A live legacy embedding migration must keep an already published index usable.

Exercise knowledge HTTP endpoints and the public settings/runtime boundaries;
all vectors come from the session-local fake embedding service.
"""

from __future__ import annotations

from copy import deepcopy
import json
import time


def test_legacy_migration_preserves_published_knowledge_index(client, embedding_server):
    from math_q_agent.services.config import get_model_catalog_service
    from math_q_agent.services.embedding.config import get_embedding_config
    from math_q_agent.services.rag.embedding_signature import signature_from_config

    service = get_model_catalog_service()
    original = service.load()
    kb_name = "direct-migration-index"
    selection = {"profile_id": "direct-kb-profile", "model_id": "direct-kb-model"}
    legacy_profile = {
        "id": selection["profile_id"],
        "name": "Fake knowledge profile",
        "connection_id": "direct-kb-connection",
        "binding": "openai",
        "models": [{"id": selection["model_id"], "name": "Fake knowledge model",
                    "model": "fake-embed", "dimension": 8}],
    }
    legacy = deepcopy(original)
    legacy["connections"].append({
        "id": "direct-kb-connection", "provider": "openai", "name": "Fake knowledge connection",
        "base_url": embedding_server, "api_key": "fake-kb-key",
    })
    legacy["services"]["embedding"] = {
        "profiles": [legacy_profile], "active_profile_id": selection["profile_id"],
        "active_model_id": selection["model_id"],
    }
    legacy.pop("direct_config_migration", None)
    try:
        # Seed an old on-disk catalog. Public reads perform the migration.
        service.path.write_text(json.dumps(legacy), encoding="utf-8")
        configured = client.get("/api/settings/catalog")
        assert configured.status_code == 200, configured.text
        before_signature = signature_from_config(get_embedding_config(selection)).hash()
        created = client.post(
            "/api/knowledge-bases", data={"name": kb_name, "rag_provider": "llamaindex"},
            files={"files": ("notes.txt", b"A helix angle of 20 degrees is a gear property.", "text/plain")},
        )
        assert created.status_code == 200, created.text
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            detail = client.get(f"/api/knowledge-bases/{kb_name}").json()
            statistics = detail.get("statistics", {})
            if statistics.get("rag_initialized"):
                break
            assert statistics.get("status") not in {"error", "failed"}, statistics
            time.sleep(0.1)
        else:
            raise AssertionError("Local fake knowledge index did not become ready")

        # Reintroduce the same legacy representation after the index exists.
        # This emulates an upgrade of a persisted, already indexed knowledge base.
        service.path.write_text(json.dumps(legacy), encoding="utf-8")
        migrated = client.get("/api/settings/catalog")
        assert migrated.status_code == 200, migrated.text
        model = migrated.json()["catalog"]["services"]["embedding"]["profiles"][0]["models"][0]
        assert isinstance(model.get("direct_config"), dict)
        assert signature_from_config(get_embedding_config(selection)).hash() == before_signature
        renamed = client.post("/api/settings/direct-model", json={
            "service": "embedding", "profile_id": selection["profile_id"],
            "model": {**model, "name": "Renamed published embedding"},
        })
        assert renamed.status_code == 200, renamed.text
        assert signature_from_config(get_embedding_config(selection)).hash() == before_signature
        # The persisted KB binding still protects the same IDs after a rename.
        protected = client.post("/api/settings/direct-model/delete", json={
            "service": "embedding", **selection,
        })
        assert protected.status_code == 409, protected.text
        queried = client.post(f"/api/knowledge-bases/{kb_name}/query",
                              json={"query": "helix angle", "top_k": 3})
        assert queried.status_code == 200, queried.text
        assert any("20 degrees" in row["content"] for row in queried.json()["sources"])
    finally:
        client.delete(f"/api/knowledge-bases/{kb_name}")
        restored = client.post("/api/settings/apply", json={"catalog": original})
        assert restored.status_code == 200, restored.text
