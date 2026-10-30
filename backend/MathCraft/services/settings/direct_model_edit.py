"""Merge one direct model into the latest live catalog inside its write lock."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from MathCraft.services.config.model_catalog import restore_catalog_secrets


class DirectModelEditError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def upsert_direct_model(
    catalog: dict[str, Any], service: str, profile_id: str,
    model: dict[str, Any], *, make_default: bool = False,
    secret_source: dict[str, Any] | None = None,
) -> None:
    """Update a stable model ID without replacing its profile or sibling models."""
    profile_id = profile_id.strip()
    model = deepcopy(model)
    if not profile_id:
        raise DirectModelEditError("A profile ID is required.")
    for field in ("id", "name", "model"):
        if not isinstance(model.get(field), str) or not model[field].strip():
            raise DirectModelEditError(f"Model {field} is required.")
        model[field] = model[field].strip()
    config = model.get("direct_config")
    if not isinstance(config, dict):
        raise DirectModelEditError("A complete direct_config is required.")
    for field in ("binding", "base_url", "api_key", "api_format"):
        if field not in config:
            raise DirectModelEditError(f"direct_config.{field} is required.")
    if not isinstance(config.get("binding"), str) or not config["binding"].strip():
        raise DirectModelEditError("A model provider binding is required.")
    config["binding"] = config["binding"].strip()
    proposed = {"services": {service: {"profiles": [{
        "id": profile_id, "models": [deepcopy(model)],
    }]}}}
    source = secret_source if secret_source is not None else catalog
    profiles = source.get("services", {}).get(service, {}).get("profiles", [])
    source_profile = next((p for p in profiles if p.get("id") == profile_id), {})
    source_model = next((m for m in source_profile.get("models", []) if m.get("id") == model["id"]), {})
    require_mask_sources(config, source_model.get("direct_config"))
    restored = restore_catalog_secrets(proposed, source)
    saved = restored["services"][service]["profiles"][0]["models"][0]
    bucket = catalog["services"][service]
    if service == "task":
        bucket.setdefault("mode", "inherit")
    profile = next((p for p in bucket["profiles"] if p["id"] == profile_id), None)
    if profile is None:
        profile = {"id": profile_id, "models": []}
        bucket["profiles"].append(profile)
    models = profile.setdefault("models", [])
    index = next((i for i, item in enumerate(models) if item["id"] == model["id"]), None)
    if index is None:
        models.append(saved)
    else:
        models[index] = {**models[index], **saved}
    if make_default or not bucket.get("active_model_id"):
        bucket["active_profile_id"] = profile_id
        bucket["active_model_id"] = model["id"]


def _target(catalog: dict[str, Any], service: str, profile_id: str, model_id: str):
    bucket = catalog["services"][service]
    profile = next((p for p in bucket["profiles"] if p["id"] == profile_id), None)
    model = next((m for m in (profile or {}).get("models", []) if m["id"] == model_id), None)
    if model is None:
        raise DirectModelEditError("Saved model was not found.", 404)
    return bucket, profile, model


def select_direct_model(catalog: dict[str, Any], service: str, profile_id: str, model_id: str) -> None:
    bucket, _, model = _target(catalog, service, profile_id, model_id)
    if not model.get("model"):
        raise DirectModelEditError("Choose a configured model first.")
    bucket["active_profile_id"] = profile_id
    bucket["active_model_id"] = model_id


def delete_direct_model(
    catalog: dict[str, Any], service: str, profile_id: str, model_id: str,
    *, knowledge_bases_root: Path,
) -> None:
    bucket, profile, model = _target(catalog, service, profile_id, model_id)
    _protect_referenced_model(catalog, service, profile_id, model_id, profile, knowledge_bases_root)
    profile["models"].remove(model)
    if not profile["models"]:
        bucket["profiles"].remove(profile)
    if (bucket.get("active_profile_id"), bucket.get("active_model_id")) == (profile_id, model_id):
        remaining = [(p, m) for p in bucket["profiles"] for m in p.get("models", []) if m.get("model")]
        bucket["active_profile_id"] = remaining[0][0]["id"] if remaining else None
        bucket["active_model_id"] = remaining[0][1]["id"] if remaining else None


def set_task_mode(catalog: dict[str, Any], mode: str) -> None:
    bucket = catalog["services"]["task"]
    if mode == "profiles":
        _target(catalog, "task", bucket.get("active_profile_id"), bucket.get("active_model_id"))
    bucket["mode"] = mode


def validate_catalog_names(catalog: dict[str, Any]) -> None:
    from MathCraft.services.config.direct_model_config import validate_direct_names

    for service in ("llm", "embedding", "task"):
        for profile in catalog.get("services", {}).get(service, {}).get("profiles", []):
            for model in profile.get("models", []):
                if "name" not in model and "direct_config" not in model:
                    model["name"] = str(model.get("model") or "").strip()
    try:
        validate_direct_names(catalog)
        _convert_legacy_task_reference(catalog)
        validate_direct_names(catalog)
    except DirectModelEditError:
        raise
    except ValueError as exc:
        if "全局唯一" in str(exc):
            raise DirectModelEditError("Model configuration names must be globally unique.", 409) from None
        raise DirectModelEditError("Model configuration name is required.") from None


def draft_secret_source(
    draft: dict[str, Any], updated_at: str | None,
    service: str, profile_id: str, model_id: str,
) -> dict[str, Any]:
    """Select a versioned draft snapshot without mutating or promoting it."""
    from MathCraft.services.config.direct_model_config import migrate_direct_catalog

    if not updated_at:
        raise DirectModelEditError("A draft revision is required for explicit restoration.")
    if not isinstance(draft.get("catalog"), dict):
        raise DirectModelEditError("Saved draft was not found.", 404)
    if draft.get("updated_at") != updated_at:
        raise DirectModelEditError("The saved draft changed. Reload it before restoring.", 409)
    try:
        source = migrate_direct_catalog(deepcopy(draft["catalog"]))
    except ValueError:
        raise DirectModelEditError("The saved draft cannot be migrated safely.") from None
    _target(source, service, profile_id, model_id)
    return source


def require_mask_sources(proposed: Any, source: Any) -> None:
    """A placeholder must have an actual credential at the same source path."""
    if proposed == "***":
        if source is None or source == "" or source == "***":
            raise DirectModelEditError("Saved credentials were not found. Enter them again.")
    elif isinstance(proposed, dict):
        for key, value in proposed.items():
            require_mask_sources(value, source.get(key) if isinstance(source, dict) else None)
    elif isinstance(proposed, list):
        for index, value in enumerate(proposed):
            require_mask_sources(value, source[index] if isinstance(source, list) and index < len(source) else None)


def _convert_legacy_task_reference(catalog: dict[str, Any]) -> None:
    """Expand old reference writes through migration, naming only the new copy."""
    from MathCraft.services.config.direct_model_config import migrate_direct_catalog

    task = catalog.get("services", {}).get("task", {})
    if task.get("mode") != "reference":
        return
    selection = task.get("selection") or {}
    _, _, target = _target(catalog, "llm", selection.get("profile_id"), selection.get("model_id"))
    snapshot = deepcopy(catalog)
    snapshot.pop("direct_config_migration", None)
    snapshot["services"]["task"]["profiles"] = []
    converted = migrate_direct_catalog(snapshot)["services"]["task"]
    copied_profile = next(p for p in converted["profiles"] if p["id"] == converted["active_profile_id"])
    copied = next(m for m in copied_profile["models"] if m["id"] == converted["active_model_id"])
    used = {
        str(model.get("name") or "").strip()
        for service in ("llm", "embedding", "task")
        for profile in catalog["services"][service]["profiles"]
        for model in profile.get("models", [])
        if (service, profile["id"], model["id"]) != ("task", copied_profile["id"], copied["id"])
    }
    base = target["name"].strip()
    name, suffix = base, 2
    while name in used:
        name = f"{base} ({suffix})"
        suffix += 1
    copied["name"] = name
    existing = next((p for p in task["profiles"] if p["id"] == copied_profile["id"]), None)
    if existing is None:
        task["profiles"].append(copied_profile)
    else:
        index = next((i for i, m in enumerate(existing["models"]) if m["id"] == copied["id"]), None)
        if index is None:
            existing["models"].append(copied)
        else:
            existing["models"][index] = copied
    task.update(mode="profiles", active_profile_id=copied_profile["id"], active_model_id=copied["id"])


def _protect_referenced_model(catalog, service, profile_id, model_id, profile, knowledge_bases_root):
    from MathCraft.services.config.provider_links import referenced_models
    from MathCraft.services.model_selection.tasks import TASK_OVERRIDES_KEY

    task = catalog.get("services", {}).get("task", {})
    choices = [task, *task.get(TASK_OVERRIDES_KEY, {}).values()]
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        referenced = (
            service == "llm" and choice.get("mode") == "reference"
            and choice.get("selection", {}).get("profile_id") == profile_id
            and choice.get("selection", {}).get("model_id") == model_id
        ) or (
            choice is not task and service == "task" and choice.get("mode") == "profiles"
            and choice.get("active_profile_id") == profile_id
            and choice.get("active_model_id") == model_id
        )
        if referenced:
            raise DirectModelEditError("This model is assigned to background tasks. Change those assignments first.", 409)
    if len(profile["models"]) == 1:
        references = referenced_models(catalog, {"service": service, "profile_id": profile_id})
        if any((s, p) != (service, profile_id) for s, p, _ in references):
            raise DirectModelEditError("This profile is still referenced by other model configurations.", 409)
    if service != "embedding":
        return
    from MathCraft.knowledge.model_references import (
        KnowledgeBaseReferenceError,
        embedding_model_is_referenced,
    )

    try:
        referenced = embedding_model_is_referenced(knowledge_bases_root, profile_id, model_id)
    except KnowledgeBaseReferenceError:
        raise DirectModelEditError("Knowledge-base references could not be verified. Retry before deleting.", 409) from None
    if referenced:
        raise DirectModelEditError("This embedding model is bound to a knowledge base. Change its binding first.", 409)
