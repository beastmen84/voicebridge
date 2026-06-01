import json
from pathlib import Path

from voicebridge.app_settings import (
    cleanup_app_config_on_startup,
    legacy_backup_dir,
    load_app_settings,
    settings_config_path,
)
from voicebridge.json_schemas import APP_JSON_SCHEMA_VERSION


def _config_dir(tmp_path: Path) -> Path:
    return tmp_path / "VoiceBridge"


def test_cleanup_app_config_migrates_legacy_preferred_voices(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config_dir = _config_dir(tmp_path)
    config_dir.mkdir()
    settings_config_path().write_text(
        json.dumps({"preferred_voice_short_names": ["it-ElsaNeural"], "window": {"width": 1200}}),
        encoding="utf-8",
    )
    (config_dir / "preferred_voices.json").write_text(
        json.dumps({"short_names": ["en-JennyNeural", "it-ElsaNeural", "", 7]}),
        encoding="utf-8",
    )

    actions = cleanup_app_config_on_startup()

    settings = load_app_settings()
    assert settings["schema_version"] == APP_JSON_SCHEMA_VERSION
    assert settings["kind"] == "voicebridge_settings"
    assert settings["preferred_voice_short_names"] == ["en-JennyNeural", "it-ElsaNeural"]
    assert settings["window"] == {"width": 1200}
    assert not (config_dir / "preferred_voices.json").exists()
    assert any("preferred_voices.json" in action and "migrated" in action for action in actions)
    assert list(legacy_backup_dir().glob("preferred_voices.migrated-*.json"))


def test_cleanup_app_config_archives_corrupt_known_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config_dir = _config_dir(tmp_path)
    config_dir.mkdir()
    for config_name in ("settings.json", "voice_profiles.json", "modeling_datasets.json"):
        (config_dir / config_name).write_text("{broken", encoding="utf-8")

    actions = cleanup_app_config_on_startup()

    assert not (config_dir / "settings.json").exists()
    assert not (config_dir / "voice_profiles.json").exists()
    assert not (config_dir / "modeling_datasets.json").exists()
    assert len(actions) == 3
    assert list(legacy_backup_dir().glob("settings.corrupt-*.json"))
    assert list(legacy_backup_dir().glob("voice_profiles.corrupt-*.json"))
    assert list(legacy_backup_dir().glob("modeling_datasets.corrupt-*.json"))


def test_cleanup_app_config_archives_unknown_top_level_json_only(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config_dir = _config_dir(tmp_path)
    config_dir.mkdir()
    old_config_path = config_dir / "old_config.json"
    readme_path = config_dir / "notes.txt"
    nested_dir = config_dir / "nested"
    old_config_path.write_text("{}", encoding="utf-8")
    readme_path.write_text("keep", encoding="utf-8")
    nested_dir.mkdir()
    (nested_dir / "old_config.json").write_text("{}", encoding="utf-8")

    actions = cleanup_app_config_on_startup()

    assert not old_config_path.exists()
    assert readme_path.exists()
    assert (nested_dir / "old_config.json").exists()
    assert any("old_config.json" in action and "legacy" in action for action in actions)
    assert list(legacy_backup_dir().glob("old_config.legacy-*.json"))


def test_cleanup_app_config_adds_schema_metadata_to_active_configs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config_dir = _config_dir(tmp_path)
    config_dir.mkdir()
    (config_dir / "voice_profiles.json").write_text(json.dumps({"profiles": []}), encoding="utf-8")
    (config_dir / "modeling_datasets.json").write_text(json.dumps({"datasets": []}), encoding="utf-8")

    cleanup_app_config_on_startup()

    profiles_data = json.loads((config_dir / "voice_profiles.json").read_text(encoding="utf-8"))
    datasets_data = json.loads((config_dir / "modeling_datasets.json").read_text(encoding="utf-8"))
    assert profiles_data["schema_version"] == APP_JSON_SCHEMA_VERSION
    assert profiles_data["kind"] == "voicebridge_voice_profiles"
    assert datasets_data["schema_version"] == APP_JSON_SCHEMA_VERSION
    assert datasets_data["kind"] == "voicebridge_modeling_datasets"


def test_cleanup_app_config_archives_unsupported_active_config_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    config_dir = _config_dir(tmp_path)
    config_dir.mkdir()
    (config_dir / "voice_profiles.json").write_text(
        json.dumps({"schema_version": "1.1", "kind": "voicebridge_voice_profiles", "profiles": []}),
        encoding="utf-8",
    )

    actions = cleanup_app_config_on_startup()

    assert not (config_dir / "voice_profiles.json").exists()
    assert any("voice_profiles.json" in action and "unsupported-version" in action for action in actions)
    assert list(legacy_backup_dir().glob("voice_profiles.unsupported-version-*.json"))
