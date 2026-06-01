from voicebridge.json_schemas import (
    SETTINGS_JSON_KIND,
    VOICE_PROFILES_JSON_KIND,
    app_json_version_supported,
    current_schema_version,
    with_schema_metadata,
)


def test_app_json_version_supported_accepts_current_and_legacy_int_version() -> None:
    assert app_json_version_supported(
        {"schema_version": current_schema_version(SETTINGS_JSON_KIND)},
        kind=SETTINGS_JSON_KIND,
    )
    assert app_json_version_supported({"version": 1}, kind=SETTINGS_JSON_KIND)
    assert not app_json_version_supported({"schema_version": "1.1"}, kind=SETTINGS_JSON_KIND)
    assert not app_json_version_supported(
        {"schema_version": current_schema_version(SETTINGS_JSON_KIND), "kind": VOICE_PROFILES_JSON_KIND},
        kind=SETTINGS_JSON_KIND,
    )


def test_with_schema_metadata_sets_version_and_kind() -> None:
    payload = with_schema_metadata({"name": "Config"}, "voicebridge_test")

    assert payload["schema_version"] == current_schema_version("voicebridge_test")
    assert payload["kind"] == "voicebridge_test"
    assert payload["name"] == "Config"
