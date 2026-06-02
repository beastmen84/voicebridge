from typing import Any

SCHEMA_VERSION_1_0 = "1.0"
SCHEMA_VERSION_1_1 = "1.1"
SCHEMA_VERSION_1_2 = "1.2"

SETTINGS_JSON_KIND = "voicebridge_settings"
VOICE_PROFILES_JSON_KIND = "voicebridge_voice_profiles"
MODELING_DATASETS_JSON_KIND = "voicebridge_modeling_datasets"
MODELING_DATASET_EXPORT_JSON_KIND = "voicebridge_modeling_dataset_export"
TTS_TIMELINE_JSON_KIND = "voicebridge_tts_timeline"
LOCAL_TTS_CHUNKS_JSON_KIND = "voicebridge_local_tts_chunks"
VOICE_MODELING_JOB_CONFIG_JSON_KIND = "voicebridge_voice_modeling_job_config"
VOICE_MODELING_TRAINING_STATE_JSON_KIND = "voicebridge_voice_modeling_training_state"
VOICE_MODELING_TRAINING_RESULT_JSON_KIND = "voicebridge_voice_modeling_training_result"

APP_JSON_SCHEMA_VERSIONS = {
    SETTINGS_JSON_KIND: SCHEMA_VERSION_1_0,
    VOICE_PROFILES_JSON_KIND: SCHEMA_VERSION_1_0,
    MODELING_DATASETS_JSON_KIND: SCHEMA_VERSION_1_2,
    MODELING_DATASET_EXPORT_JSON_KIND: SCHEMA_VERSION_1_0,
    TTS_TIMELINE_JSON_KIND: SCHEMA_VERSION_1_0,
    LOCAL_TTS_CHUNKS_JSON_KIND: SCHEMA_VERSION_1_0,
    VOICE_MODELING_JOB_CONFIG_JSON_KIND: SCHEMA_VERSION_1_0,
    VOICE_MODELING_TRAINING_STATE_JSON_KIND: SCHEMA_VERSION_1_0,
    VOICE_MODELING_TRAINING_RESULT_JSON_KIND: SCHEMA_VERSION_1_0,
}

APP_JSON_SUPPORTED_SCHEMA_VERSIONS = {
    MODELING_DATASETS_JSON_KIND: {SCHEMA_VERSION_1_0, SCHEMA_VERSION_1_1, SCHEMA_VERSION_1_2},
}


def current_schema_version(kind: str) -> str:
    return APP_JSON_SCHEMA_VERSIONS.get(kind, SCHEMA_VERSION_1_0)


def schema_version_value(value: Any) -> str:
    if isinstance(value, int):
        return f"{value}.0"
    if isinstance(value, float):
        return f"{value:.1f}"
    if isinstance(value, str):
        return value.strip()
    return ""


def app_json_version_supported(
    data: Any,
    *,
    kind: str,
    allow_legacy_missing: bool = True,
) -> bool:
    if not isinstance(data, dict):
        return False
    data_kind = data.get("kind")
    if isinstance(data_kind, str) and data_kind and data_kind != kind:
        return False
    version = schema_version_value(data.get("schema_version"))
    if not version:
        version = schema_version_value(data.get("version"))
    if not version:
        return allow_legacy_missing
    supported_versions = APP_JSON_SUPPORTED_SCHEMA_VERSIONS.get(kind, {current_schema_version(kind)})
    return version in supported_versions


def app_json_metadata_needs_refresh(data: Any, kind: str) -> bool:
    if not isinstance(data, dict):
        return True
    return data.get("schema_version") != current_schema_version(kind) or data.get("kind") != kind


def with_schema_metadata(data: dict[str, Any], kind: str) -> dict[str, Any]:
    payload = dict(data)
    payload["schema_version"] = current_schema_version(kind)
    payload["kind"] = kind
    return payload
