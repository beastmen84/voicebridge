import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from voicebridge.app_paths import external_base_dir
from voicebridge.app_settings import app_config_dir
from voicebridge.file_checks import required_file_issue
from voicebridge.json_schemas import VOICE_PROFILES_JSON_KIND, app_json_version_supported, with_schema_metadata
from voicebridge.languages import LANGUAGE_NAMES

VOICE_PROFILES_CONFIG = "voice_profiles.json"
VOICE_PROFILES_AUDIO_DIR = "voice_profiles"
VOICE_PROFILE_REFERENCE = "reference"
VOICE_PROFILE_MODELING = "modeling"
VOICE_PROFILE_TYPE_DIR_NAMES = {
    VOICE_PROFILE_REFERENCE: "reference_clone",
    VOICE_PROFILE_MODELING: "modeling_dataset",
}
VOICE_PROFILE_TYPES = {
    "Reference clone": VOICE_PROFILE_REFERENCE,
    "Modeling dataset": VOICE_PROFILE_MODELING,
}
VOICE_PROFILE_TYPE_LABELS = {value: key for key, value in VOICE_PROFILE_TYPES.items()}
VOICE_PROFILE_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
VOICE_PROFILE_LANGUAGES = [
    "it",
    "en",
    "es",
    "fr",
    "de",
    "pt",
    "pl",
    "tr",
    "ru",
    "nl",
    "cs",
    "ar",
    "zh-cn",
    "ja",
    "hu",
    "ko",
    "hi",
]


class VoiceProfile(TypedDict):
    id: str
    name: str
    language_code: str
    profile_type: str
    reference_paths: list[str]
    consent_confirmed: bool
    notes: str
    created_at: str
    updated_at: str


def voice_profiles_config_path() -> Path:
    return app_config_dir() / VOICE_PROFILES_CONFIG


def voice_profiles_audio_dir() -> Path:
    return external_base_dir() / VOICE_PROFILES_AUDIO_DIR


def voice_profile_type_dir_name(profile_type: Any) -> str:
    return VOICE_PROFILE_TYPE_DIR_NAMES[normalize_profile_type(profile_type)]


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def clean_profile_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    return " ".join(name.split()).strip()


def safe_voice_profile_audio_stem(name: Any) -> str:
    cleaned = clean_profile_name(name).lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    cleaned = cleaned.strip("-")
    return cleaned or "voice-profile"


def voice_profile_type_storage_dir(
    profile_type: str = VOICE_PROFILE_REFERENCE,
    audio_dir: Path | None = None,
) -> Path:
    directory = audio_dir or voice_profiles_audio_dir()
    return directory / voice_profile_type_dir_name(profile_type)


def voice_profile_storage_dir(
    name: Any,
    profile_type: str = VOICE_PROFILE_REFERENCE,
    audio_dir: Path | None = None,
) -> Path:
    return voice_profile_type_storage_dir(profile_type, audio_dir) / safe_voice_profile_audio_stem(name)


def voice_profile_recording_path(
    name: Any,
    timestamp: str | None = None,
    audio_dir: Path | None = None,
    profile_type: str = VOICE_PROFILE_REFERENCE,
) -> Path:
    directory = voice_profile_storage_dir(name, profile_type, audio_dir)
    return directory / f"{safe_voice_profile_audio_stem(name)}-{timestamp or file_timestamp()}.wav"


def voice_profile_owned_audio_paths(profile: VoiceProfile, audio_dir: Path | None = None) -> list[Path]:
    audio_root = (audio_dir or voice_profiles_audio_dir()).resolve()
    paths: list[Path] = []
    seen: set[Path] = set()
    for reference_path in normalized_reference_paths(profile.get("reference_paths", [])):
        path = Path(reference_path).expanduser()
        if path.suffix.lower() != ".wav":
            continue
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(audio_root)
        except ValueError:
            continue
        if resolved_path in seen or not resolved_path.is_file():
            continue
        paths.append(resolved_path)
        seen.add(resolved_path)
    return paths


def delete_voice_profile_audio_files(
    profile: VoiceProfile,
    audio_dir: Path | None = None,
) -> tuple[list[Path], list[Path]]:
    deleted_paths: list[Path] = []
    failed_paths: list[Path] = []
    for path in voice_profile_owned_audio_paths(profile, audio_dir):
        try:
            path.unlink()
        except OSError:
            failed_paths.append(path)
        else:
            deleted_paths.append(path)
    return deleted_paths, failed_paths


def normalize_profile_type(value: Any) -> str:
    if isinstance(value, str) and value in VOICE_PROFILE_TYPES.values():
        return value
    if isinstance(value, str) and value in VOICE_PROFILE_TYPES:
        return VOICE_PROFILE_TYPES[value]
    return VOICE_PROFILE_REFERENCE


def normalize_voice_profile_language(value: Any) -> str:
    if not isinstance(value, str):
        return "it"
    language_code = value.strip().lower()
    if language_code in VOICE_PROFILE_LANGUAGES:
        return language_code
    if language_code in LANGUAGE_NAMES:
        return language_code
    return "it"


def normalized_reference_paths(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []

    paths = []
    seen = set()
    for item in values:
        if not isinstance(item, str):
            continue
        if not item.strip():
            continue
        path = str(Path(item).expanduser())
        if not path or path in seen:
            continue
        paths.append(path)
        seen.add(path)
    return paths


def voice_profile_status(profile: VoiceProfile) -> str:
    if profile.get("profile_type") == VOICE_PROFILE_MODELING:
        return "Modeling dataset"
    reference_paths = normalized_reference_paths(profile.get("reference_paths", []))
    if not reference_paths:
        return "Missing reference audio"
    audio_issues = [required_file_issue(path, min_bytes=32) for path in reference_paths]
    if any(issue == "missing" for issue in audio_issues):
        return "Missing audio file"
    if any(issue for issue in audio_issues):
        return "Incomplete audio file"
    unsupported = [
        path for path in reference_paths
        if Path(path).suffix.lower() not in VOICE_PROFILE_AUDIO_SUFFIXES
    ]
    if unsupported:
        return "Unsupported audio format"
    return "Ready"


def ready_voice_profiles(profiles: list[VoiceProfile]) -> list[VoiceProfile]:
    return [
        profile for profile in profiles
        if profile.get("profile_type") == VOICE_PROFILE_REFERENCE and voice_profile_status(profile) == "Ready"
    ]


def voice_profile_display_label(profile: VoiceProfile) -> str:
    language = LANGUAGE_NAMES.get(profile["language_code"], profile["language_code"].upper())
    return f"{profile['name']} ({language})"


def validate_voice_profile(profile: VoiceProfile) -> None:
    if not clean_profile_name(profile.get("name")):
        raise ValueError("Profile name is required.")
    status = voice_profile_status(profile)
    if status in {"Missing reference audio", "Missing audio file", "Incomplete audio file", "Unsupported audio format"}:
        raise ValueError(status + ".")


def build_voice_profile(
    name: str,
    language_code: str,
    profile_type: str,
    reference_paths: list[str],
    consent_confirmed: bool,
    notes: str = "",
    profile_id: str | None = None,
    created_at: str | None = None,
) -> VoiceProfile:
    timestamp = utc_timestamp()
    return {
        "id": profile_id or uuid4().hex,
        "name": clean_profile_name(name),
        "language_code": normalize_voice_profile_language(language_code),
        "profile_type": normalize_profile_type(profile_type),
        "reference_paths": normalized_reference_paths(reference_paths),
        "consent_confirmed": True,
        "notes": notes.strip() if isinstance(notes, str) else "",
        "created_at": created_at or timestamp,
        "updated_at": timestamp,
    }


def normalized_voice_profile(value: Any) -> VoiceProfile | None:
    if not isinstance(value, dict):
        return None
    profile_id = value.get("id")
    name = clean_profile_name(value.get("name"))
    if not isinstance(profile_id, str) or not profile_id or not name:
        return None
    return build_voice_profile(
        name=name,
        language_code=normalize_voice_profile_language(value.get("language_code")),
        profile_type=normalize_profile_type(value.get("profile_type")),
        reference_paths=normalized_reference_paths(value.get("reference_paths")),
        consent_confirmed=bool(value.get("consent_confirmed")),
        notes=value.get("notes", "") if isinstance(value.get("notes"), str) else "",
        profile_id=profile_id,
        created_at=value.get("created_at") if isinstance(value.get("created_at"), str) else None,
    ) | {
        "updated_at": value.get("updated_at") if isinstance(value.get("updated_at"), str) else utc_timestamp(),
    }


def load_voice_profiles(path: Path | None = None) -> list[VoiceProfile]:
    config_path = path or voice_profiles_config_path()
    try:
        with config_path.open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
    except (OSError, json.JSONDecodeError):
        return []

    if isinstance(data, dict) and not app_json_version_supported(data, kind=VOICE_PROFILES_JSON_KIND):
        return []
    raw_profiles = data.get("profiles", []) if isinstance(data, dict) else data
    if not isinstance(raw_profiles, list):
        return []
    profiles = []
    for item in raw_profiles:
        profile = normalized_voice_profile(item)
        if profile:
            profiles.append(profile)
    return profiles


def save_voice_profiles(profiles: list[VoiceProfile], path: Path | None = None) -> None:
    config_path = path or voice_profiles_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = with_schema_metadata({"profiles": profiles}, VOICE_PROFILES_JSON_KIND)
    with config_path.open("w", encoding="utf-8") as config_file:
        json.dump(data, config_file, indent=2, ensure_ascii=False)
