"""Versioned, in-memory migration to independently owned model connections.

No settings, drafts, environment files, or provider endpoints are read here.
The caller owns the catalog write lock and atomic persistence boundary.
"""
from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, uuid5

if TYPE_CHECKING:
    from .model_catalog import ModelCatalogService


DIRECT_SERVICES = ("llm", "embedding", "task")
DIRECT_CONFIG_VERSION = 1


def _entries(catalog: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    for service in DIRECT_SERVICES:
        for profile in catalog.get("services", {}).get(service, {}).get("profiles", []):
            for model in profile.get("models", []):
                yield service, profile, model


def validate_direct_names(catalog: dict[str, Any]) -> None:
    """Validate global, case-sensitive names; trim happens before persistence.

    Error text deliberately excludes arbitrary configuration values and secrets.
    Legacy name repair is performed by ``migrate_direct_catalog`` first.
    """
    names: set[str] = set()
    for _, _, model in _entries(catalog):
        raw = model.get("name")
        name = raw.strip() if isinstance(raw, str) else ""
        if not name:
            raise ValueError("模型配置名称不能为空")
        if name in names:
            raise ValueError("模型配置名称必须全局唯一（区分大小写）")
        names.add(name)


def _repair_names(catalog: dict[str, Any]) -> list[dict[str, str]]:
    # Reserve ALL original names before allocating suffixes, including names
    # like 'A (2)' that occur after the duplicate being repaired.
    entries = sorted(_entries(catalog), key=lambda item: (
        DIRECT_SERVICES.index(item[0]), str(item[1].get("id")), str(item[2].get("id"))
    ))
    reserved = {
        str(model.get("name") or model.get("model") or "模型配置").strip() or "模型配置"
        for _, _, model in entries
    }
    used: set[str] = set()
    renamed = []
    for service, profile, model in entries:
        old = str(model.get("name") or "")
        base = old.strip() or str(model.get("model") or "").strip() or "模型配置"
        name = base
        suffix = 2
        while name in used:
            name = f"{base} ({suffix})"
            suffix += 1
            if name in reserved:
                name = base
        used.add(name)
        model["name"] = name
        if old != name:
            renamed.append({"service": service, "profile_id": profile["id"],
                            "model_id": model["id"], "old_name": old, "new_name": name})
    return renamed


def _validate_references(catalog: dict[str, Any]) -> None:
    from .provider_links import provider_source

    connections = {item.get("id") for item in catalog.get("connections", [])}
    for _, profile, model in _entries(catalog):
        if isinstance(model.get("direct_config"), dict):
            continue
        ref = model.get("provider_ref") or profile.get("provider_ref")
        if isinstance(ref, dict):
            provider_source(catalog, ref)
        elif profile.get("connection_id") and profile["connection_id"] not in connections:
            raise ValueError("模型配置迁移失败：原连接已不存在")


def _snapshot(
    catalog: dict[str, Any], service: str, profile: dict[str, Any],
    model: dict[str, Any], resolver: ModelCatalogService,
) -> dict[str, Any]:
    from .provider_links import resolve_profile_provider
    from .provider_runtime import resolve_embedding_runtime_config, resolve_llm_runtime_config

    effective = resolve_profile_provider(catalog, service, profile, model)
    # Keep advanced/vendor extension fields, but never carry references back
    # into the self-contained connection or copy its display/model identity.
    excluded = {"id", "name", "models", "model", "provider_ref", "connection_id",
                "service_overrides", "provider_only"}
    direct = {key: deepcopy(value) for key, value in effective.items() if key not in excluded}
    selected = deepcopy(catalog)
    bucket = selected["services"][service]
    bucket["active_profile_id"] = profile["id"]
    bucket["active_model_id"] = model["id"]
    if service == "embedding":
        config = resolve_embedding_runtime_config(selected, service=resolver)
    else:
        if service == "task":
            bucket["mode"] = "profiles"
        config = resolve_llm_runtime_config(
            selected, service=resolver, service_name=service, catalog_only=True
        )
    # Capture the actual legacy fallback results, including missing/null
    # credentials and canonical embedding endpoint/provider identity.
    direct.update(binding=config.binding, api_key=deepcopy(config.api_key),
                  base_url=config.base_url or "", api_version=config.api_version or "",
                  extra_headers=deepcopy(config.extra_headers))
    if service != "embedding":
        direct.update(api_format=config.api_format, wire_api=config.wire_api)
    else:
        from .embedding_endpoint import normalize_embedding_endpoint_for_display

        # Old catalog loads displayed and persisted full embedding endpoints.
        # Normalize only after resolving inherited URLs, so an empty source
        # cannot replace the actual endpoint with a registry default.
        direct["base_url"] = normalize_embedding_endpoint_for_display(
            config.binding, config.base_url, model.get("model"),
        )
        direct.setdefault("api_format", "auto")
    direct.setdefault("proxy", "")
    direct.setdefault("app_id", "")
    return direct


def migrate_direct_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """Return a migrated copy, or raise before any mutation/persistence.

    ``direct_config_migration`` carries a version plus safe, visible name
    adjustments. Repeated calls preserve identities and feedback exactly.
    """
    from .model_catalog import ModelCatalogService

    migrated = deepcopy(catalog)
    marker = migrated.get("direct_config_migration")
    if marker is not None and (
        not isinstance(marker, dict) or marker.get("version") != DIRECT_CONFIG_VERSION
    ):
        raise ValueError("不支持的模型配置迁移版本")
    # Older unversioned files may lack IDs; derive these from their structural
    # position rather than generating a different identity on each failed retry.
    for service in DIRECT_SERVICES:
        profiles = migrated.get("services", {}).get(service, {}).get("profiles", [])
        for pi, profile in enumerate(profiles):
            profile.setdefault("id", f"{service}-profile-" + uuid5(
                NAMESPACE_URL, f"mathcraft:legacy:{service}:{pi}"
            ).hex)
            for mi, model in enumerate(profile.get("models", [])):
                model.setdefault("id", f"{service}-model-" + uuid5(
                    NAMESPACE_URL, f"mathcraft:legacy:{service}:{profile['id']}:{mi}"
                ).hex)
    _validate_references(migrated)
    # Old loads supplied a missing provider binding before runtime resolution.
    # Keep that default so connection-only profiles participate in credential
    # pools. Do not normalize endpoints here: it would replace an inherited
    # embedding endpoint with a registry default before it can be snapshotted.
    resolver = ModelCatalogService(Path("model_catalog.json"))
    source = resolver.resolve_connections(migrated)
    for service in DIRECT_SERVICES:
        for profile in source.get("services", {}).get(service, {}).get("profiles", []):
            profile.setdefault("binding", "openai")
    for service, profile, model in _entries(migrated):
        if isinstance(model.get("direct_config"), dict):
            continue
        source_profile = next(p for p in source["services"][service]["profiles"]
                              if p["id"] == profile["id"])
        source_model = next(m for m in source_profile["models"] if m["id"] == model["id"])
        model["direct_config"] = _snapshot(source, service, source_profile, source_model, resolver)
    task = migrated.get("services", {}).get("task", {})
    if task.get("mode") == "reference":
        selection = task.get("selection") or {}
        target_profile = next((p for p in migrated.get("services", {}).get("llm", {}).get("profiles", [])
                               if p.get("id") == selection.get("profile_id")), None)
        target = next((m for m in (target_profile or {}).get("models", [])
                       if m.get("id") == selection.get("model_id")), None)
        if target is None or target_profile.get("provider_only"):
            raise ValueError("模型配置迁移失败：原任务模型引用已失效")
        identity = uuid5(NAMESPACE_URL, "mathcraft:task-reference:" +
                         str(selection.get("profile_id")) + ":" + str(selection.get("model_id"))).hex
        pid, mid = f"task-profile-{identity}", f"task-model-{identity}"
        if any(p.get("id") == pid for p in task.get("profiles", [])):
            raise ValueError("模型配置迁移失败：任务副本标识已存在")
        copied = deepcopy(target)
        copied["id"] = mid
        if selection.get("reasoning_effort"):
            copied["reasoning_effort"] = selection["reasoning_effort"]
        task.setdefault("profiles", []).append({"id": pid, "name": copied.get("name", ""),
                                                 "models": [copied]})
        task.update(mode="profiles", active_profile_id=pid, active_model_id=mid)
    if marker is None:
        migrated["direct_config_migration"] = {
            "version": DIRECT_CONFIG_VERSION, "renamed": _repair_names(migrated)
        }
    else:
        for _, _, model in _entries(migrated):
            if isinstance(model.get("name"), str):
                model["name"] = model["name"].strip()
    validate_direct_names(migrated)
    return migrated
