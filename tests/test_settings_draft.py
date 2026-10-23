"""Settings bookkeeping: readiness, drafts, presets.

These endpoints are what a settings UI uses to stage a change without applying
it, so the contract is: stage → inspect → discard, and never leak a draft into
the live catalogue.
"""

from __future__ import annotations


def test_readiness_matrix(client):
    response = client.get("/api/settings/readiness")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, (dict, list))
    # The matrix must not echo secrets.
    assert "***" in response.text or "api_key" not in response.text


def test_draft_round_trip_never_touches_live_catalog(client):
    live_before = client.get("/api/settings/catalog").json()["catalog"]

    staged = client.put("/api/settings/draft", json={"catalog": live_before, "extensions": {}})
    assert staged.status_code == 200, staged.text

    draft = client.get("/api/settings/draft")
    assert draft.status_code == 200
    assert draft.json()["draft"], "draft should be readable after staging"

    # Staging must not promote anything into the live catalogue.
    live_after = client.get("/api/settings/catalog").json()["catalog"]
    assert live_after == live_before

    discarded = client.delete("/api/settings/draft")
    assert discarded.status_code == 200
    assert client.get("/api/settings/draft").json()["draft"] is None


def test_presets_are_listed_and_stageable(client):
    presets = client.get("/api/settings/presets")
    assert presets.status_code == 200, presets.text
    items = presets.json()
    entries = items.get("presets") if isinstance(items, dict) else items
    assert isinstance(entries, list)
    if not entries:
        return

    preset_id = entries[0].get("id") or entries[0].get("preset_id")
    assert preset_id

    staged = client.post(f"/api/settings/presets/{preset_id}/draft", json={})
    assert staged.status_code == 200, staged.text
    assert client.get("/api/settings/draft").json()["draft"]

    client.delete("/api/settings/draft")


def test_settings_profile_reports_values_free_envelope(client):
    response = client.get("/api/settings/profile")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    # Profiles are value-free by construction: no provider key may appear.
    assert "sk-test" not in response.text
