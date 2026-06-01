import json
from pathlib import Path
from typing import Any, Literal, TypedDict

from voicebridge.file_checks import validate_existing_file
from voicebridge.languages import LANGUAGE_NAMES
from voicebridge.voice_modeling import (
    load_voice_modeling_job_config,
    voice_modeling_outputs_root,
)
from voicebridge.voice_profiles import (
    VoiceProfile,
    ready_voice_profiles,
    voice_profile_status,
)

LOCAL_VOICE_REFERENCE = "reference"
LOCAL_VOICE_TRAINED = "trained"
TRAINING_RESULT_JSON = "training_result.json"


class LocalVoiceSource(TypedDict):
    id: str
    kind: Literal["reference", "trained"]
    name: str
    language_code: str
    reference_paths: list[str]
    model_path: str
    config_path: str
    source_path: str
    status: str


def local_voice_from_reference_profile(profile: VoiceProfile) -> LocalVoiceSource:
    return {
        "id": profile["id"],
        "kind": LOCAL_VOICE_REFERENCE,
        "name": profile["name"],
        "language_code": profile["language_code"],
        "reference_paths": list(profile["reference_paths"]),
        "model_path": "",
        "config_path": "",
        "source_path": "",
        "status": voice_profile_status(profile),
    }


def local_voice_from_training_result(result_path: str | Path) -> LocalVoiceSource:
    path = Path(result_path).expanduser().resolve()
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Training result is not readable JSON: {path}") from exc
    if not isinstance(result, dict):
        raise ValueError(f"Training result must contain an object: {path}")

    config_path = _string(result.get("config_path"))
    job_config = load_voice_modeling_job_config(config_path) if config_path else {}
    dataset = job_config.get("dataset", {}) if isinstance(job_config, dict) else {}
    dataset_name = dataset.get("name") if isinstance(dataset, dict) else ""
    language_code = dataset.get("language_code") if isinstance(dataset, dict) else ""

    model_path = _existing_file(result.get("model_path"), "model_path", min_bytes=1024 * 1024)
    inference_config_path = _existing_file(
        result.get("config_path_for_inference") or Path(model_path).with_name("config.json"),
        "config_path_for_inference",
        min_bytes=32,
    )
    _existing_file(result.get("vocab_path") or Path(model_path).with_name("vocab.json"), "vocab_path", min_bytes=32)
    speaker_wav = _existing_file(result.get("speaker_wav"), "speaker_wav", min_bytes=32)

    name = dataset_name if isinstance(dataset_name, str) and dataset_name else Path(model_path).parent.parent.name
    return {
        "id": f"trained:{path}",
        "kind": LOCAL_VOICE_TRAINED,
        "name": name,
        "language_code": language_code if isinstance(language_code, str) and language_code else "it",
        "reference_paths": [speaker_wav],
        "model_path": model_path,
        "config_path": inference_config_path,
        "source_path": str(path),
        "status": "Trained model",
    }


def list_trained_local_voices(outputs_root: str | Path | None = None) -> list[LocalVoiceSource]:
    root = Path(outputs_root).expanduser() if outputs_root else voice_modeling_outputs_root()
    if not root.is_dir():
        return []
    voices: list[tuple[float, LocalVoiceSource]] = []
    for result_path in root.rglob(TRAINING_RESULT_JSON):
        try:
            voice = local_voice_from_training_result(result_path)
            modified_at = result_path.stat().st_mtime
        except (OSError, ValueError):
            continue
        voices.append((modified_at, voice))
    return [
        voice
        for _modified_at, voice in sorted(
            voices,
            key=lambda item: (item[0], item[1]["id"]),
            reverse=True,
        )
    ]


def ready_local_voice_sources(profiles: list[VoiceProfile]) -> list[LocalVoiceSource]:
    return [
        *(local_voice_from_reference_profile(profile) for profile in ready_voice_profiles(profiles)),
        *list_trained_local_voices(),
    ]


def grouped_local_voice_sources(voices: list[LocalVoiceSource]) -> list[tuple[str, list[LocalVoiceSource]]]:
    groups = [
        ("Reference profiles", LOCAL_VOICE_REFERENCE),
        ("Trained models", LOCAL_VOICE_TRAINED),
    ]
    return [
        (label, [voice for voice in voices if voice["kind"] == kind])
        for label, kind in groups
        if any(voice["kind"] == kind for voice in voices)
    ]


def local_voice_display_label(voice: LocalVoiceSource) -> str:
    language = LANGUAGE_NAMES.get(voice["language_code"], voice["language_code"].upper())
    suffix = "trained" if voice["kind"] == LOCAL_VOICE_TRAINED else "reference"
    return f"{voice['name']} ({language}) | {suffix}"


def local_voice_status_text(voice: LocalVoiceSource) -> str:
    if voice["kind"] == LOCAL_VOICE_TRAINED:
        return f"Trained model | {Path(voice['model_path']).parent.name}"
    return f"{voice['status']} | {Path(voice['reference_paths'][0]).name}"


def local_voice_requires_base_xtts(voice: LocalVoiceSource | None) -> bool:
    return not voice or voice["kind"] == LOCAL_VOICE_REFERENCE


def local_voice_model_args(voice: LocalVoiceSource) -> list[str]:
    if voice["kind"] != LOCAL_VOICE_TRAINED:
        return []
    return ["--model-path", voice["model_path"], "--config-path", voice["config_path"]]


def local_voice_relative_root_label(path: str) -> str:
    resolved_path = Path(path).expanduser().resolve()
    try:
        return str(resolved_path.relative_to(voice_modeling_outputs_root().resolve()))
    except ValueError:
        try:
            return str(resolved_path.relative_to(Path.cwd().resolve()))
        except ValueError:
            return str(resolved_path)


def _existing_file(value: Any, label: str, *, min_bytes: int = 1) -> str:
    path_text = _string(value)
    if not path_text:
        raise ValueError(f"Training result is missing {label}.")
    path = validate_existing_file(path_text, f"Training result {label}", min_bytes=min_bytes)
    return str(path.resolve())


def _string(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    return value.strip() if isinstance(value, str) else ""
