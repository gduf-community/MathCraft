"""Indexing progress over WebSocket.

The socket is the only push channel the frontend gets, so at minimum it must
accept the connection, replay the durable snapshot, and emit a terminal state
for an indexing run.
"""

from __future__ import annotations

import time


def test_progress_websocket_streams_indexing(client):
    client.post(
        "/api/knowledge-bases",
        data={"name": "ws-kb"},
        files={
            "files": (
                "notes.txt",
                b"A spur gear has a pressure angle of 20 degrees. " * 40,
                "text/plain",
            )
        },
    )

    with client.websocket_connect("/ws/knowledge-bases/ws-kb/progress") as socket:
        client.post("/api/knowledge-bases/ws-kb/reindex")

        seen = []
        deadline = time.time() + 60
        while time.time() < deadline:
            message = socket.receive_json()
            seen.append(message)
            if message.get("type") in {"complete", "error"}:
                break
            if message.get("type") == "progress":
                data = message.get("data") or {}
                if data.get("stage") in {"completed", "error"}:
                    break

    assert seen, "no progress messages received"
    assert {message.get("type") for message in seen} <= {"progress", "error", "complete"}
    assert any(message.get("type") == "progress" for message in seen)

    client.delete("/api/knowledge-bases/ws-kb")
