from voicebridge.json_schemas import (
    APP_JSON_SCHEMA_VERSION,
    app_json_version_supported,
    with_schema_metadata,
)


def test_app_json_version_supported_accepts_current_and_legacy_int_version() -> None:
    assert app_json_version_supported({"schema_version": APP_JSON_SCHEMA_VERSION})
    assert app_json_version_supported({"version": 1})
    assert not app_json_version_supported({"schema_version": "1.1"})


def test_with_schema_metadata_sets_version_and_kind() -> None:
    payload = with_schema_metadata({"name": "Config"}, "voicebridge_test")

    assert payload["schema_version"] == APP_JSON_SCHEMA_VERSION
    assert payload["kind"] == "voicebridge_test"
    assert payload["name"] == "Config"
