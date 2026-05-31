import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from voicebridge.app_paths import external_base_dir
from voicebridge.app_settings import app_config_dir
from voicebridge.voice_profiles import VOICE_PROFILE_MODELING, VoiceProfile

MODELING_DATASETS_CONFIG = "modeling_datasets.json"
MODELING_DATASETS_DIR = "modeling_datasets"
MODELING_CLIP_TEXT_GUIDED = "text_guided"
MODELING_CLIP_FREE_RECORDING = "free_recording"
MODELING_CLIP_READY = "ready"
MODELING_CLIP_NEEDS_TRANSCRIPT = "needs_transcript"
MODELING_CLIP_MISSING_AUDIO = "missing_audio"


class ModelingClip(TypedDict):
    id: str
    mode: str
    audio_path: str
    transcript_path: str
    transcript_text: str
    transcript_source: str
    language_code: str
    duration_seconds: float
    quality_details: str
    status: str
    created_at: str
    updated_at: str


class ModelingDataset(TypedDict):
    id: str
    profile_id: str
    name: str
    language_code: str
    clips: list[ModelingClip]
    created_at: str
    updated_at: str


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def modeling_datasets_config_path() -> Path:
    return app_config_dir() / MODELING_DATASETS_CONFIG


def modeling_datasets_root() -> Path:
    return external_base_dir() / MODELING_DATASETS_DIR


def modeling_dataset_dir(dataset: ModelingDataset) -> Path:
    return modeling_datasets_root() / dataset["profile_id"]


def modeling_dataset_clips_dir(dataset: ModelingDataset) -> Path:
    return modeling_dataset_dir(dataset) / "clips"


def modeling_dataset_transcripts_dir(dataset: ModelingDataset) -> Path:
    return modeling_dataset_dir(dataset) / "transcripts"


def modeling_clip_audio_path(dataset: ModelingDataset, clip_id: str | None = None) -> Path:
    return modeling_dataset_clips_dir(dataset) / f"{clip_id or uuid4().hex}.wav"


def modeling_clip_transcript_path(dataset: ModelingDataset, clip_id: str) -> Path:
    return modeling_dataset_transcripts_dir(dataset) / f"{clip_id}.txt"


def modeling_clip_display_status(clip: ModelingClip) -> str:
    audio_path = Path(clip.get("audio_path", ""))
    if not audio_path.is_file():
        return MODELING_CLIP_MISSING_AUDIO
    if clip.get("transcript_text", "").strip():
        return MODELING_CLIP_READY
    return MODELING_CLIP_NEEDS_TRANSCRIPT


def modeling_clip_status_label(status: str) -> str:
    return {
        MODELING_CLIP_READY: "Ready",
        MODELING_CLIP_NEEDS_TRANSCRIPT: "Needs transcript",
        MODELING_CLIP_MISSING_AUDIO: "Missing audio",
    }.get(status, status.replace("_", " ").title())


def build_modeling_dataset_for_profile(
    profile: VoiceProfile,
    existing: ModelingDataset | None = None,
) -> ModelingDataset:
    timestamp = utc_timestamp()
    return {
        "id": existing["id"] if existing else profile["id"],
        "profile_id": profile["id"],
        "name": profile["name"],
        "language_code": profile["language_code"],
        "clips": existing["clips"] if existing else [],
        "created_at": existing["created_at"] if existing else timestamp,
        "updated_at": timestamp,
    }


def build_modeling_clip(
    dataset: ModelingDataset,
    *,
    mode: str,
    audio_path: str | Path,
    transcript_text: str = "",
    transcript_source: str = "",
    duration_seconds: float = 0.0,
    quality_details: str = "",
    clip_id: str | None = None,
) -> ModelingClip:
    timestamp = utc_timestamp()
    clip_id = clip_id or uuid4().hex
    transcript_text = transcript_text.strip()
    transcript_path = modeling_clip_transcript_path(dataset, clip_id)
    normalized_mode = (
        mode if mode in {MODELING_CLIP_TEXT_GUIDED, MODELING_CLIP_FREE_RECORDING}
        else MODELING_CLIP_FREE_RECORDING
    )
    clip = {
        "id": clip_id,
        "mode": normalized_mode,
        "audio_path": str(Path(audio_path)),
        "transcript_path": str(transcript_path),
        "transcript_text": transcript_text,
        "transcript_source": transcript_source.strip(),
        "language_code": dataset["language_code"],
        "duration_seconds": max(0.0, float(duration_seconds)),
        "quality_details": quality_details.strip(),
        "status": MODELING_CLIP_READY if transcript_text else MODELING_CLIP_NEEDS_TRANSCRIPT,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    return clip


def update_modeling_clip_transcript(
    clip: ModelingClip,
    transcript_text: str,
    transcript_source: str = "manual",
) -> ModelingClip:
    updated = dict(clip)
    updated["transcript_text"] = transcript_text.strip()
    updated["transcript_source"] = transcript_source.strip()
    updated["status"] = MODELING_CLIP_READY if updated["transcript_text"] else MODELING_CLIP_NEEDS_TRANSCRIPT
    updated["updated_at"] = utc_timestamp()
    return updated  # type: ignore[return-value]


def write_modeling_clip_transcript(clip: ModelingClip) -> None:
    text = clip.get("transcript_text", "").strip()
    transcript_path_value = clip.get("transcript_path", "")
    if not transcript_path_value:
        return
    transcript_path = Path(transcript_path_value)
    if text:
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(text + "\n", encoding="utf-8")
        return
    with suppress(OSError):
        transcript_path.unlink(missing_ok=True)


def delete_modeling_clip_files(clip: ModelingClip) -> tuple[list[Path], list[Path]]:
    deleted: list[Path] = []
    failed: list[Path] = []
    for path_value in (clip.get("audio_path", ""), clip.get("transcript_path", "")):
        if not path_value:
            continue
        path = Path(path_value)
        if not path.exists():
            continue
        try:
            path.unlink()
        except OSError:
            failed.append(path)
        else:
            deleted.append(path)
    return deleted, failed


def normalized_modeling_clip(value: Any) -> ModelingClip | None:
    if not isinstance(value, dict):
        return None
    clip_id = value.get("id")
    audio_path = value.get("audio_path")
    if not isinstance(clip_id, str) or not clip_id or not isinstance(audio_path, str):
        return None
    timestamp = utc_timestamp()
    normalized_mode = (
        value.get("mode")
        if value.get("mode") in {MODELING_CLIP_TEXT_GUIDED, MODELING_CLIP_FREE_RECORDING}
        else MODELING_CLIP_FREE_RECORDING
    )
    transcript_path = value.get("transcript_path") if isinstance(value.get("transcript_path"), str) else ""
    transcript_text = value.get("transcript_text", "") if isinstance(value.get("transcript_text"), str) else ""
    transcript_source = value.get("transcript_source", "") if isinstance(value.get("transcript_source"), str) else ""
    status = (
        value.get("status", MODELING_CLIP_NEEDS_TRANSCRIPT)
        if isinstance(value.get("status"), str)
        else MODELING_CLIP_NEEDS_TRANSCRIPT
    )
    clip: ModelingClip = {
        "id": clip_id,
        "mode": normalized_mode,
        "audio_path": audio_path,
        "transcript_path": transcript_path,
        "transcript_text": transcript_text,
        "transcript_source": transcript_source,
        "language_code": value.get("language_code", "it") if isinstance(value.get("language_code"), str) else "it",
        "duration_seconds": _float(value.get("duration_seconds")),
        "quality_details": value.get("quality_details", "") if isinstance(value.get("quality_details"), str) else "",
        "status": status,
        "created_at": value.get("created_at") if isinstance(value.get("created_at"), str) else timestamp,
        "updated_at": value.get("updated_at") if isinstance(value.get("updated_at"), str) else timestamp,
    }
    clip["status"] = modeling_clip_display_status(clip)
    return clip


def normalized_modeling_dataset(value: Any) -> ModelingDataset | None:
    if not isinstance(value, dict):
        return None
    dataset_id = value.get("id")
    profile_id = value.get("profile_id")
    name = value.get("name")
    if not isinstance(dataset_id, str) or not isinstance(profile_id, str) or not isinstance(name, str):
        return None
    timestamp = utc_timestamp()
    clips = [
        clip for raw_clip in value.get("clips", [])
        if (clip := normalized_modeling_clip(raw_clip)) is not None
    ] if isinstance(value.get("clips"), list) else []
    return {
        "id": dataset_id,
        "profile_id": profile_id,
        "name": name,
        "language_code": value.get("language_code", "it") if isinstance(value.get("language_code"), str) else "it",
        "clips": clips,
        "created_at": value.get("created_at") if isinstance(value.get("created_at"), str) else timestamp,
        "updated_at": value.get("updated_at") if isinstance(value.get("updated_at"), str) else timestamp,
    }


def load_modeling_datasets(path: Path | None = None) -> list[ModelingDataset]:
    config_path = path or modeling_datasets_config_path()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_datasets = data.get("datasets", []) if isinstance(data, dict) else []
    if not isinstance(raw_datasets, list):
        return []
    return [
        dataset for raw_dataset in raw_datasets
        if (dataset := normalized_modeling_dataset(raw_dataset)) is not None
    ]


def save_modeling_datasets(datasets: list[ModelingDataset], path: Path | None = None) -> None:
    config_path = path or modeling_datasets_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"datasets": datasets}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def ensure_modeling_datasets_for_profiles(
    datasets: list[ModelingDataset],
    profiles: list[VoiceProfile],
) -> tuple[list[ModelingDataset], bool]:
    modeling_profiles = [profile for profile in profiles if profile.get("profile_type") == VOICE_PROFILE_MODELING]
    by_profile_id = {dataset["profile_id"]: dataset for dataset in datasets}
    changed = False
    synced: list[ModelingDataset] = []
    for profile in modeling_profiles:
        existing = by_profile_id.get(profile["id"])
        dataset = build_modeling_dataset_for_profile(profile, existing)
        if (
            existing is None
            or dataset["name"] != existing["name"]
            or dataset["language_code"] != existing["language_code"]
        ):
            changed = True
        synced.append(dataset)
    modeling_profile_ids = {profile["id"] for profile in modeling_profiles}
    orphaned = [dataset for dataset in datasets if dataset["profile_id"] not in modeling_profile_ids]
    return [*synced, *orphaned], changed


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0
