import json
import os
from pathlib import Path
from typing import Any

APP_CONFIG_DIR_NAME = "VoiceBridge"
SETTINGS_CONFIG = "settings.json"
LEGACY_PREFERRED_VOICES_CONFIG = "preferred_voices.json"
SETTINGS_VERSION = 1

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


def load_app_settings() -> Settings:
    try:
        with settings_config_path().open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except (OSError, json.JSONDecodeError):
        data = {}

    settings = data if isinstance(data, dict) else {}
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
    try:
        config_path = settings_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as config_file:
            json.dump(clean_settings, config_file, indent=2, ensure_ascii=False)
    except OSError:
        pass


def load_preferred_voice_short_names() -> set[str]:
    settings = load_app_settings()
    return _short_name_set(settings.get("preferred_voice_short_names", []))


def save_preferred_voice_short_names(short_names: set[str]) -> None:
    settings = load_app_settings()
    settings["preferred_voice_short_names"] = sorted(short_names)
    save_app_settings(settings)
