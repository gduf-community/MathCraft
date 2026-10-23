"""Local connector behaviour: probe, reject, link, delete.

The "linked folder" connector links an **already built index** (a knowledge-base
folder containing a ``version-N`` directory), not a folder of raw documents.
These tests pin that contract: probing reports readiness, connecting refuses a
plain folder, and a real indexed knowledge base can be linked and removed
without touching the source.

Remote connectors (Kiwix, IMA, WeKnora, remote LightRAG) need external services
and are covered by their configuration endpoints, not here.

Source folders live inside the repository: the test runner's sandbox does not
grant write access to the system temp directory.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

SOURCES = Path(__file__).resolve().parent / ".sources"
DATA_HOME = Path(__file__).resolve().parent / ".data-home"


@pytest.fixture()
def workspace():
    shutil.rmtree(SOURCES, ignore_errors=True)
    SOURCES.mkdir(parents=True, exist_ok=True)
    yield SOURCES
    shutil.rmtree(SOURCES, ignore_errors=True)


def _folder(root: Path, name: str = "notes") -> str:
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "chapter.md").write_text("# Gears\n\nA helix angle of 20 degrees.", encoding="utf-8")
    return str(target.resolve())


def _wait_for_index(client, name: str, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        stats = client.get(f"/api/knowledge-bases/{name}").json().get("statistics", {})
        if stats.get("rag_initialized"):
            return
        if stats.get("status") in {"error", "failed"}:
            raise AssertionError(f"indexing failed: {stats}")
        time.sleep(0.5)
    raise AssertionError(f"indexing timed out for {name}")


def test_probe_reports_missing_index(client, workspace):
    response = client.post(
        "/api/knowledge-bases/probe-folder", json={"folder_path": _folder(workspace)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert "index" in (body.get("error") or "").lower()


def test_probe_rejects_missing_folder(client, workspace):
    response = client.post(
        "/api/knowledge-bases/probe-folder",
        json={"folder_path": str(workspace / "does-not-exist")},
    )
    assert response.status_code in {400, 404, 422}


def test_connect_refuses_folder_without_index(client, workspace):
    response = client.post(
        "/api/knowledge-bases/connect-folder",
        json={"name": "plain-folder-kb", "folder_path": _folder(workspace, "plain")},
    )
    assert response.status_code == 400
    assert "index" in response.json()["detail"].lower()
    names = {item["name"] for item in client.get("/api/knowledge-bases").json()}
    assert "plain-folder-kb" not in names


def test_link_indexed_knowledge_base(client):
    client.post(
        "/api/knowledge-bases",
        data={"name": "linked-source"},
        files={"files": ("notes.txt", b"A worm gear has a lead angle.", "text/plain")},
    )
    _wait_for_index(client, "linked-source")

    source_dir = DATA_HOME / "data" / "knowledge_bases" / "linked-source"
    assert any(path.name.startswith("version-") for path in source_dir.iterdir())

    linked = client.post(
        "/api/knowledge-bases/connect-folder",
        json={"name": "linked-copy", "folder_path": str(source_dir)},
    )
    assert linked.status_code == 200, linked.text

    names = {item["name"] for item in client.get("/api/knowledge-bases").json()}
    assert "linked-copy" in names

    detail = client.get("/api/knowledge-bases/linked-copy").json()
    assert detail["metadata"].get("type") in {"linked", "linked-folder", "folder", "local-folder"}

    assert client.delete("/api/knowledge-bases/linked-copy").status_code == 200
    assert client.delete("/api/knowledge-bases/linked-source").status_code == 200


def test_connect_obsidian_vault(client, workspace):
    vault = workspace / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "note.md").write_text("# Note\n\nObsidian content.", encoding="utf-8")

    response = client.post(
        "/api/knowledge-bases/connect-obsidian",
        json={"name": "obsidian-kb", "vault_path": str(vault)},
    )
    assert response.status_code == 200, response.text

    names = {item["name"] for item in client.get("/api/knowledge-bases").json()}
    assert "obsidian-kb" in names

    detail = client.get("/api/knowledge-bases/obsidian-kb").json()
    assert detail["metadata"].get("type") == "obsidian"

    assert client.delete("/api/knowledge-bases/obsidian-kb").status_code == 200
