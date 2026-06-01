from typing import Any

APP_JSON_SCHEMA_VERSION = "1.0"


def schema_version_value(value: Any) -> str:
    if isinstance(value, int):
        return f"{value}.0"
    if isinstance(value, float):
        return f"{value:.1f}"
    if isinstance(value, str):
        return value.strip()
    return ""


def app_json_version_supported(data: Any, *, allow_legacy_missing: bool = True) -> bool:
    if not isinstance(data, dict):
        return False
    version = schema_version_value(data.get("schema_version"))
    if not version:
        version = schema_version_value(data.get("version"))
    if not version:
        return allow_legacy_missing
    return version == APP_JSON_SCHEMA_VERSION


def app_json_metadata_needs_refresh(data: Any, kind: str) -> bool:
    if not isinstance(data, dict):
        return True
    return data.get("schema_version") != APP_JSON_SCHEMA_VERSION or data.get("kind") != kind


def with_schema_metadata(data: dict[str, Any], kind: str) -> dict[str, Any]:
    payload = dict(data)
    payload["schema_version"] = APP_JSON_SCHEMA_VERSION
    payload["kind"] = kind
    return payload
