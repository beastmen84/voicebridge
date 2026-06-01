import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from voicebridge.json_schemas import (
    APP_JSON_SCHEMA_VERSION,
    app_json_metadata_needs_refresh,
    app_json_version_supported,
    with_schema_metadata,
)

APP_CONFIG_DIR_NAME = "VoiceBridge"
SETTINGS_CONFIG = "settings.json"
LEGACY_PREFERRED_VOICES_CONFIG = "preferred_voices.json"
VOICE_PROFILES_CONFIG = "voice_profiles.json"
MODELING_DATASETS_CONFIG = "modeling_datasets.json"
APP_CONFIG_BACKUP_DIR = "legacy_backup"
SETTINGS_JSON_KIND = "voicebridge_settings"
VOICE_PROFILES_JSON_KIND = "voicebridge_voice_profiles"
MODELING_DATASETS_JSON_KIND = "voicebridge_modeling_datasets"
SETTINGS_VERSION = APP_JSON_SCHEMA_VERSION
ACTIVE_CONFIG_FILES = {SETTINGS_CONFIG, VOICE_PROFILES_CONFIG, MODELING_DATASETS_CONFIG}
LEGACY_CONFIG_FILES = {LEGACY_PREFERRED_VOICES_CONFIG}
KNOWN_CONFIG_FILES = ACTIVE_CONFIG_FILES | LEGACY_CONFIG_FILES
VERSIONED_CONFIG_SPECS = {
    VOICE_PROFILES_CONFIG: (VOICE_PROFILES_JSON_KIND, "profiles"),
    MODELING_DATASETS_CONFIG: (MODELING_DATASETS_JSON_KIND, "datasets"),
}

Settings = dict[str, Any]


def app_config_dir() -> Path:
    base_dir = os.environ.get("APPDATA")
    if base_dir:
        return Path(base_dir) / APP_CONFIG_DIR_NAME
    return Path.home() / f".{APP_CONFIG_DIR_NAME.lower()}"


def settings_config_path() -> Path:
    return app_config_dir() / SETTINGS_CONFIG


def legacy_preferred_voices_config_path() -> Path:
    return app_config_dir() / LEGACY_PREFERRED_VOICES_CONFIG


def legacy_backup_dir() -> Path:
    return app_config_dir() / APP_CONFIG_BACKUP_DIR


def _file_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _read_json(path: Path) -> tuple[Any, str | None]:
    try:
        with path.open("r", encoding="utf-8") as config_file:
            return json.load(config_file), None
    except json.JSONDecodeError:
        return None, "invalid-json"
    except OSError:
        return None, "unreadable"


def _archive_config_file(path: Path, reason: str) -> Path | None:
    if not path.is_file():
        return None
    try:
        backup_dir = legacy_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"{path.stem}.{reason}-{_file_timestamp()}{path.suffix}"
        counter = 2
        while target.exists():
            target = backup_dir / f"{path.stem}.{reason}-{_file_timestamp()}-{counter}{path.suffix}"
            counter += 1
        path.replace(target)
    except OSError:
        return None
    return target


def _archive_with_action(path: Path, reason: str, actions: list[str]) -> None:
    archived_path = _archive_config_file(path, reason)
    if archived_path:
        actions.append(f"archived {path.name} -> {archived_path.name}")


def _write_json_file(path: Path, data: dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as config_file:
            json.dump(data, config_file, indent=2, ensure_ascii=False)
    except OSError:
        return False
    return True


def _upgrade_collection_config(
    path: Path,
    value: Any,
    *,
    kind: str,
    collection_key: str,
    actions: list[str],
) -> None:
    if isinstance(value, list):
        upgraded = with_schema_metadata({collection_key: value}, kind)
    elif isinstance(value, dict):
        if not app_json_version_supported(value):
            _archive_with_action(path, "unsupported-version", actions)
            return
        if not app_json_metadata_needs_refresh(value, kind):
            return
        upgraded = with_schema_metadata(value, kind)
    else:
        _archive_with_action(path, "corrupt", actions)
        return

    if _write_json_file(path, upgraded):
        actions.append(f"updated {path.name} schema metadata")


def _short_name_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _load_legacy_preferred_voice_short_names() -> set[str]:
    try:
        with legacy_preferred_voices_config_path().open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except (OSError, json.JSONDecodeError):
        return set()
    short_names = data.get("short_names", []) if isinstance(data, dict) else []
    return _short_name_set(short_names)


def cleanup_app_config_on_startup() -> list[str]:
    """Archive stale AppData JSON files without deleting user assets."""
    config_dir = app_config_dir()
    if not config_dir.is_dir():
        return []

    actions: list[str] = []
    settings_path = settings_config_path()
    settings_data: Settings = {}
    settings_value = None
    if settings_path.exists():
        settings_value, error = _read_json(settings_path)
        if error or not isinstance(settings_value, dict):
            _archive_with_action(settings_path, "corrupt", actions)
        elif not app_json_version_supported(settings_value):
            _archive_with_action(settings_path, "unsupported-version", actions)
        else:
            settings_data = settings_value
            if app_json_metadata_needs_refresh(settings_data, SETTINGS_JSON_KIND):
                save_app_settings(settings_data)
                actions.append("updated settings.json schema metadata")

    for config_name, (kind, collection_key) in VERSIONED_CONFIG_SPECS.items():
        config_path = config_dir / config_name
        if not config_path.exists():
            continue
        value, error = _read_json(config_path)
        if error:
            _archive_with_action(config_path, "corrupt", actions)
            continue
        _upgrade_collection_config(
            config_path,
            value,
            kind=kind,
            collection_key=collection_key,
            actions=actions,
        )

    legacy_path = legacy_preferred_voices_config_path()
    if legacy_path.exists():
        legacy_value, error = _read_json(legacy_path)
        if error or not isinstance(legacy_value, dict):
            _archive_with_action(legacy_path, "legacy-invalid", actions)
        else:
            existing_short_names = _short_name_set(settings_data.get("preferred_voice_short_names", []))
            legacy_short_names = _short_name_set(legacy_value.get("short_names", []))
            merged_short_names = sorted(existing_short_names | legacy_short_names)
            if merged_short_names:
                settings_data["preferred_voice_short_names"] = merged_short_names
            settings_data["version"] = SETTINGS_VERSION
            save_app_settings(settings_data)
            _archive_with_action(legacy_path, "migrated", actions)

    for config_path in config_dir.glob("*.json"):
        if config_path.name not in KNOWN_CONFIG_FILES:
            _archive_with_action(config_path, "legacy", actions)

    return actions


def load_app_settings() -> Settings:
    try:
        with settings_config_path().open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except (OSError, json.JSONDecodeError):
        data = {}

    settings = data if isinstance(data, dict) and app_json_version_supported(data) else {}
    settings.setdefault("schema_version", SETTINGS_VERSION)
    settings.setdefault("kind", SETTINGS_JSON_KIND)
    settings.setdefault("version", SETTINGS_VERSION)

    if "preferred_voice_short_names" not in settings:
        legacy_short_names = _load_legacy_preferred_voice_short_names()
        if legacy_short_names:
            settings["preferred_voice_short_names"] = sorted(legacy_short_names)
            save_app_settings(settings)

    return settings


def save_app_settings(settings: Settings) -> None:
    clean_settings = dict(settings)
    clean_settings["version"] = SETTINGS_VERSION
    clean_settings = with_schema_metadata(clean_settings, SETTINGS_JSON_KIND)
    try:
        config_path = settings_config_path()
        _write_json_file(config_path, clean_settings)
    except OSError:
        pass


def load_preferred_voice_short_names() -> set[str]:
    settings = load_app_settings()
    return _short_name_set(settings.get("preferred_voice_short_names", []))


def save_preferred_voice_short_names(short_names: set[str]) -> None:
    settings = load_app_settings()
    settings["preferred_voice_short_names"] = sorted(short_names)
    save_app_settings(settings)
