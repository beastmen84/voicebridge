import json
import re
import shutil
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict
from uuid import uuid4

from voicebridge.app_paths import external_base_dir
from voicebridge.app_settings import app_config_dir
from voicebridge.json_schemas import (
    MODELING_DATASET_EXPORT_JSON_KIND,
    MODELING_DATASETS_JSON_KIND,
    app_json_version_supported,
    with_schema_metadata,
)
from voicebridge.modeling_prompt_generator import (
    generated_prompt_source,
    modeling_prompt_available_count,
    normalize_prompt_text,
)
from voicebridge.voice_profiles import (
    VOICE_PROFILE_MODELING,
    VoiceProfile,
    safe_voice_profile_audio_stem,
    voice_profile_storage_dir,
    voice_profile_type_storage_dir,
)

MODELING_DATASETS_CONFIG = "modeling_datasets.json"
MODELING_DATASET_EXPORTS_DIR = "modeling_exports"
MODELING_CLIP_TEXT_GUIDED = "text_guided"
MODELING_CLIP_FREE_RECORDING = "free_recording"
MODELING_CLIP_READY = "ready"
MODELING_CLIP_NEEDS_TRANSCRIPT = "needs_transcript"
MODELING_CLIP_MISSING_AUDIO = "missing_audio"
MODELING_DATASET_NOT_READY = "not_ready"
MODELING_DATASET_USABLE = "usable"
MODELING_DATASET_GOOD = "good"
MODELING_DATASET_TIER_NOT_READY = "not_ready"
MODELING_DATASET_TIER_TEST = "technical_test"
MODELING_DATASET_TIER_BASE = "base"
MODELING_DATASET_TIER_RECOMMENDED = "recommended"
MODELING_DATASET_TIER_HIGH_QUALITY = "high_quality"
MODELING_DATASET_TIER_PREMIUM = "premium"
MODELING_MIN_READY_CLIPS = 5
MODELING_MIN_READY_SECONDS = 60.0
MODELING_GOOD_READY_CLIPS = 20
MODELING_GOOD_READY_SECONDS = 600.0
MODELING_TARGET_READY_CLIPS = 60
MODELING_TARGET_READY_SECONDS = 1800.0
MODELING_STRETCH_READY_CLIPS = 120
MODELING_STRETCH_READY_SECONDS = 3600.0
MODELING_BASE_TIER_SECONDS = 300.0
MODELING_RECOMMENDED_TIER_SECONDS = 900.0
MODELING_HIGH_QUALITY_TIER_SECONDS = 1800.0
MODELING_PREMIUM_TIER_SECONDS = 3600.0
MODELING_MIN_READY_CLIP_SECONDS = 5.0
MODELING_MAX_READY_CLIP_SECONDS = 60.0
MODELING_LOW_RMS_PERCENT = 3.0
MODELING_CLIPPING_PERCENT = 0.10
MODELING_LOW_SNR_DB = 18.0


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
    guided_prompt_history: list[str]
    created_at: str
    updated_at: str


class ModelingDatasetSummary(TypedDict):
    total_clips: int
    ready_clips: int
    pending_transcript_clips: int
    missing_audio_clips: int
    ready_duration_seconds: float
    average_ready_duration_seconds: float
    short_ready_clips: int
    long_ready_clips: int
    low_level_clips: int
    clipping_clips: int
    noisy_clips: int
    readiness: str
    dataset_tier: str
    target_reached: bool
    target_clips_percent: int
    target_duration_percent: int
    guided_prompt_used_count: int
    guided_prompt_available_count: int
    issues: list[str]
    recommendations: list[str]


class ModelingDatasetExportResult(TypedDict):
    export_dir: str
    wavs_dir: str
    metadata_path: str
    dataset_json_path: str
    exported_clips: int
    skipped_clips: int


def utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def file_timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def modeling_datasets_config_path() -> Path:
    return app_config_dir() / MODELING_DATASETS_CONFIG


def modeling_datasets_root() -> Path:
    return voice_profile_type_storage_dir(VOICE_PROFILE_MODELING)


def modeling_dataset_dir(dataset: ModelingDataset) -> Path:
    return voice_profile_storage_dir(dataset["name"], VOICE_PROFILE_MODELING)


def modeling_dataset_clips_dir(dataset: ModelingDataset) -> Path:
    return modeling_dataset_dir(dataset) / "clips"


def modeling_dataset_transcripts_dir(dataset: ModelingDataset) -> Path:
    return modeling_dataset_dir(dataset) / "transcripts"


def modeling_dataset_exports_root() -> Path:
    return external_base_dir() / MODELING_DATASET_EXPORTS_DIR


def modeling_dataset_export_dir(
    dataset: ModelingDataset,
    *,
    timestamp: str | None = None,
    export_root: Path | None = None,
) -> Path:
    root = export_root or modeling_dataset_exports_root()
    return root / f"{safe_voice_profile_audio_stem(dataset['name'])}-{timestamp or file_timestamp()}"


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


def modeling_dataset_readiness_label(readiness: str) -> str:
    return {
        MODELING_DATASET_NOT_READY: "Not ready",
        MODELING_DATASET_USABLE: "Usable",
        MODELING_DATASET_GOOD: "Good",
    }.get(readiness, readiness.replace("_", " ").title())


def modeling_dataset_tier_label(tier: str) -> str:
    return {
        MODELING_DATASET_TIER_NOT_READY: "Not ready",
        MODELING_DATASET_TIER_TEST: "Technical test",
        MODELING_DATASET_TIER_BASE: "Base",
        MODELING_DATASET_TIER_RECOMMENDED: "Recommended",
        MODELING_DATASET_TIER_HIGH_QUALITY: "High quality",
        MODELING_DATASET_TIER_PREMIUM: "Premium",
    }.get(tier, tier.replace("_", " ").title())


def modeling_dataset_duration_tier(ready_duration_seconds: float) -> str:
    if ready_duration_seconds <= 0:
        return MODELING_DATASET_TIER_NOT_READY
    if ready_duration_seconds < MODELING_BASE_TIER_SECONDS:
        return MODELING_DATASET_TIER_TEST
    if ready_duration_seconds < MODELING_RECOMMENDED_TIER_SECONDS:
        return MODELING_DATASET_TIER_BASE
    if ready_duration_seconds < MODELING_HIGH_QUALITY_TIER_SECONDS:
        return MODELING_DATASET_TIER_RECOMMENDED
    if ready_duration_seconds < MODELING_PREMIUM_TIER_SECONDS:
        return MODELING_DATASET_TIER_HIGH_QUALITY
    return MODELING_DATASET_TIER_PREMIUM


def modeling_dataset_summary(dataset: ModelingDataset) -> ModelingDatasetSummary:
    ready_duration_seconds = 0.0
    ready_clips = 0
    pending_transcript_clips = 0
    missing_audio_clips = 0
    short_ready_clips = 0
    long_ready_clips = 0
    low_level_clips = 0
    clipping_clips = 0
    noisy_clips = 0

    for clip in dataset["clips"]:
        status = modeling_clip_display_status(clip)
        if status == MODELING_CLIP_MISSING_AUDIO:
            missing_audio_clips += 1
            continue
        if status == MODELING_CLIP_NEEDS_TRANSCRIPT:
            pending_transcript_clips += 1
            continue

        ready_clips += 1
        duration_seconds = _float(clip.get("duration_seconds"))
        ready_duration_seconds += duration_seconds
        if duration_seconds < MODELING_MIN_READY_CLIP_SECONDS:
            short_ready_clips += 1
        if duration_seconds > MODELING_MAX_READY_CLIP_SECONDS:
            long_ready_clips += 1
        quality_details = clip.get("quality_details", "")
        rms_percent = _quality_percent(quality_details, "RMS level")
        clipping_percent = _quality_percent(quality_details, "Input clipping")
        snr_db = _quality_db(quality_details, "Estimated SNR")
        if rms_percent is not None and rms_percent < MODELING_LOW_RMS_PERCENT:
            low_level_clips += 1
        if clipping_percent is not None and clipping_percent > MODELING_CLIPPING_PERCENT:
            clipping_clips += 1
        if snr_db is not None and snr_db < MODELING_LOW_SNR_DB:
            noisy_clips += 1

    average_ready_duration_seconds = ready_duration_seconds / ready_clips if ready_clips else 0.0
    quality_warning_count = short_ready_clips + long_ready_clips + low_level_clips + clipping_clips + noisy_clips
    issue_count = quality_warning_count + pending_transcript_clips + missing_audio_clips
    if ready_clips >= MODELING_GOOD_READY_CLIPS and ready_duration_seconds >= MODELING_GOOD_READY_SECONDS:
        readiness = MODELING_DATASET_GOOD if issue_count == 0 else MODELING_DATASET_USABLE
    elif ready_clips >= MODELING_MIN_READY_CLIPS and ready_duration_seconds >= MODELING_MIN_READY_SECONDS:
        readiness = MODELING_DATASET_USABLE
    else:
        readiness = MODELING_DATASET_NOT_READY

    issues = modeling_dataset_summary_issues(
        ready_clips=ready_clips,
        pending_transcript_clips=pending_transcript_clips,
        missing_audio_clips=missing_audio_clips,
        ready_duration_seconds=ready_duration_seconds,
        short_ready_clips=short_ready_clips,
        long_ready_clips=long_ready_clips,
        low_level_clips=low_level_clips,
        clipping_clips=clipping_clips,
        noisy_clips=noisy_clips,
    )
    dataset_tier = modeling_dataset_duration_tier(ready_duration_seconds)
    recommendations = modeling_dataset_summary_recommendations(
        ready_clips=ready_clips,
        readiness=readiness,
        dataset_tier=dataset_tier,
    )
    guided_prompt_used_count, guided_prompt_available = modeling_dataset_guided_prompt_usage(dataset)
    target_reached = (
        ready_clips >= MODELING_TARGET_READY_CLIPS
        and ready_duration_seconds >= MODELING_TARGET_READY_SECONDS
    )
    return {
        "total_clips": len(dataset["clips"]),
        "ready_clips": ready_clips,
        "pending_transcript_clips": pending_transcript_clips,
        "missing_audio_clips": missing_audio_clips,
        "ready_duration_seconds": round(ready_duration_seconds, 3),
        "average_ready_duration_seconds": round(average_ready_duration_seconds, 3),
        "short_ready_clips": short_ready_clips,
        "long_ready_clips": long_ready_clips,
        "low_level_clips": low_level_clips,
        "clipping_clips": clipping_clips,
        "noisy_clips": noisy_clips,
        "readiness": readiness,
        "dataset_tier": dataset_tier,
        "target_reached": target_reached,
        "target_clips_percent": _progress_percent(ready_clips, MODELING_TARGET_READY_CLIPS),
        "target_duration_percent": _progress_percent(ready_duration_seconds, MODELING_TARGET_READY_SECONDS),
        "guided_prompt_used_count": guided_prompt_used_count,
        "guided_prompt_available_count": guided_prompt_available,
        "issues": issues,
        "recommendations": recommendations,
    }


def modeling_dataset_summary_text(dataset: ModelingDataset) -> str:
    summary = modeling_dataset_summary(dataset)
    lines = [
        f"Export readiness: {modeling_dataset_readiness_label(summary['readiness'])}",
        f"Dataset tier: {modeling_dataset_tier_label(summary['dataset_tier'])}",
        f"Language: {dataset['language_code']}",
        f"Ready clips: {summary['ready_clips']}/{summary['total_clips']}",
        f"Ready duration: {format_modeling_dataset_duration(summary['ready_duration_seconds'])}",
        f"Average ready clip: {summary['average_ready_duration_seconds']:.1f}s",
        f"Guided prompts: {summary['guided_prompt_used_count']} / {summary['guided_prompt_available_count']} used",
        (
            f"Target progress: {summary['ready_clips']}/{MODELING_TARGET_READY_CLIPS} clips, "
            f"{format_modeling_dataset_duration(summary['ready_duration_seconds'])}/"
            f"{format_modeling_dataset_duration(MODELING_TARGET_READY_SECONDS)}"
        ),
        (
            f"Recommended target: {MODELING_TARGET_READY_CLIPS}-{MODELING_STRETCH_READY_CLIPS} ready clips, "
            f"{format_modeling_dataset_duration(MODELING_TARGET_READY_SECONDS)}-"
            f"{format_modeling_dataset_duration(MODELING_STRETCH_READY_SECONDS)} clean audio"
        ),
        "Tier scale: test <5m, base 5-15m, recommended 15-30m, high quality 30-60m, premium 60m+",
    ]
    if summary["issues"]:
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"- {issue}" for issue in summary["issues"])
    else:
        lines.append("")
        lines.append("No blocking dataset issues detected.")
    if summary["recommendations"]:
        lines.append("")
        lines.append("Recommendations:")
        lines.extend(f"- {recommendation}" for recommendation in summary["recommendations"])
    return "\n".join(lines)


def ready_modeling_export_clips(dataset: ModelingDataset) -> list[ModelingClip]:
    return [
        clip for clip in dataset["clips"]
        if modeling_clip_display_status(clip) == MODELING_CLIP_READY
    ]


def modeling_dataset_exportable(dataset: ModelingDataset) -> bool:
    return modeling_dataset_summary(dataset)["readiness"] in {MODELING_DATASET_USABLE, MODELING_DATASET_GOOD}


def modeling_dataset_guided_prompt_texts(dataset: ModelingDataset) -> tuple[str, ...]:
    used: list[str] = []
    seen: set[str] = set()
    for text in (*dataset.get("guided_prompt_history", []), *generated_clip_prompt_texts(dataset)):
        normalized_text = normalize_prompt_text(text)
        if not normalized_text or normalized_text in seen:
            continue
        used.append(normalized_text)
        seen.add(normalized_text)
    return tuple(used)


def generated_clip_prompt_texts(dataset: ModelingDataset) -> tuple[str, ...]:
    return tuple(
        clip.get("transcript_text", "")
        for clip in dataset["clips"]
        if generated_prompt_source(clip.get("transcript_source", ""))
    )


def modeling_dataset_guided_prompt_usage(dataset: ModelingDataset) -> tuple[int, int]:
    return (
        len(modeling_dataset_guided_prompt_texts(dataset)),
        modeling_prompt_available_count(dataset["language_code"]),
    )


def add_modeling_dataset_guided_prompt_history(dataset: ModelingDataset, text: str) -> bool:
    normalized_text = normalize_prompt_text(text)
    if not normalized_text:
        return False
    history = dataset["guided_prompt_history"]
    if normalized_text in {normalize_prompt_text(entry) for entry in history}:
        return False
    history.append(normalized_text)
    dataset["updated_at"] = utc_timestamp()
    return True


def reset_modeling_dataset_guided_prompt_history(dataset: ModelingDataset) -> bool:
    if not dataset["guided_prompt_history"]:
        return False
    dataset["guided_prompt_history"] = []
    dataset["updated_at"] = utc_timestamp()
    return True


def export_modeling_dataset(
    dataset: ModelingDataset,
    *,
    export_root: Path | None = None,
    timestamp: str | None = None,
) -> ModelingDatasetExportResult:
    if not modeling_dataset_exportable(dataset):
        raise ValueError("Dataset export requires at least Usable readiness.")
    ready_clips = ready_modeling_export_clips(dataset)
    if not ready_clips:
        raise ValueError("No ready clips are available for export.")

    export_dir = unique_export_dir(modeling_dataset_export_dir(dataset, timestamp=timestamp, export_root=export_root))
    wavs_dir = export_dir / "wavs"
    metadata_path = export_dir / "metadata.csv"
    dataset_json_path = export_dir / "dataset.json"
    wavs_dir.mkdir(parents=True, exist_ok=False)

    metadata_lines: list[str] = []
    exported_clips: list[dict[str, Any]] = []
    for index, clip in enumerate(ready_clips, start=1):
        source_audio_path = Path(clip["audio_path"])
        export_name = modeling_export_wav_name(clip, index)
        export_audio_path = wavs_dir / export_name
        shutil.copy2(source_audio_path, export_audio_path)
        transcript_text = normalize_modeling_export_text(clip.get("transcript_text", ""))
        relative_audio_path = f"wavs/{export_name}"
        metadata_lines.append(f"{relative_audio_path}|{transcript_text}")
        exported_clips.append(
            {
                "id": clip["id"],
                "mode": clip["mode"],
                "source_audio_path": str(source_audio_path),
                "export_audio_path": relative_audio_path,
                "transcript_text": transcript_text,
                "transcript_source": clip.get("transcript_source", ""),
                "duration_seconds": _float(clip.get("duration_seconds")),
            }
        )

    metadata_path.write_text("\n".join(metadata_lines) + "\n", encoding="utf-8")
    summary = modeling_dataset_summary(dataset)
    dataset_json_path.write_text(
        json.dumps(
            with_schema_metadata(
                {
                    "dataset_id": dataset["id"],
                    "profile_id": dataset["profile_id"],
                    "name": dataset["name"],
                    "language_code": dataset["language_code"],
                    "exported_at": utc_timestamp(),
                    "metadata_format": "relative_wav_path|transcript_text",
                    "summary": summary,
                    "exported_clips": exported_clips,
                },
                MODELING_DATASET_EXPORT_JSON_KIND,
            ),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    return {
        "export_dir": str(export_dir),
        "wavs_dir": str(wavs_dir),
        "metadata_path": str(metadata_path),
        "dataset_json_path": str(dataset_json_path),
        "exported_clips": len(exported_clips),
        "skipped_clips": len(dataset["clips"]) - len(exported_clips),
    }


def unique_export_dir(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.name}-{index}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not create a unique export directory for {path}.")


def modeling_export_wav_name(clip: ModelingClip, index: int) -> str:
    clip_id = re.sub(r"[^a-zA-Z0-9_-]+", "-", clip.get("id", "")).strip("-")
    return f"{index:04d}_{clip_id or 'clip'}.wav"


def normalize_modeling_export_text(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(text.replace("|", ",").split())


def modeling_dataset_summary_issues(
    *,
    ready_clips: int,
    pending_transcript_clips: int,
    missing_audio_clips: int,
    ready_duration_seconds: float,
    short_ready_clips: int,
    long_ready_clips: int,
    low_level_clips: int,
    clipping_clips: int,
    noisy_clips: int,
) -> list[str]:
    issues = []
    if ready_clips == 0:
        issues.append("Add at least one ready clip with audio and transcript.")
    elif ready_clips < MODELING_MIN_READY_CLIPS:
        issues.append(f"Collect at least {MODELING_MIN_READY_CLIPS} ready clips for a first training test.")
    if ready_duration_seconds < MODELING_MIN_READY_SECONDS:
        issues.append(
            f"Collect at least {format_modeling_dataset_duration(MODELING_MIN_READY_SECONDS)} of ready audio."
        )
    if pending_transcript_clips:
        issues.append(f"{pending_transcript_clips} clip(s) need transcript text.")
    if missing_audio_clips:
        issues.append(f"{missing_audio_clips} clip(s) are missing their WAV file.")
    if short_ready_clips:
        issues.append(f"{short_ready_clips} ready clip(s) are shorter than {MODELING_MIN_READY_CLIP_SECONDS:.0f}s.")
    if long_ready_clips:
        issues.append(f"{long_ready_clips} ready clip(s) are longer than {MODELING_MAX_READY_CLIP_SECONDS:.0f}s.")
    if low_level_clips:
        issues.append(f"{low_level_clips} ready clip(s) have low RMS level.")
    if clipping_clips:
        issues.append(f"{clipping_clips} ready clip(s) show input clipping.")
    if noisy_clips:
        issues.append(f"{noisy_clips} ready clip(s) have low estimated SNR.")
    return issues


def modeling_dataset_summary_recommendations(
    *,
    ready_clips: int,
    readiness: str,
    dataset_tier: str,
) -> list[str]:
    if ready_clips <= 0:
        return []
    if dataset_tier == MODELING_DATASET_TIER_PREMIUM:
        return ["Extended target reached; prioritize transcript accuracy and recording consistency."]
    if dataset_tier == MODELING_DATASET_TIER_HIGH_QUALITY:
        return [
            "High-quality duration reached; extra variety beyond 60 minutes can still help, but gains are gradual."
        ]
    if dataset_tier == MODELING_DATASET_TIER_RECOMMENDED:
        return [
            "Recommended duration reached; continue toward 30-60 minutes for a stronger daily-use voice."
        ]
    if dataset_tier == MODELING_DATASET_TIER_BASE:
        return [
            "Base dataset; useful for early voice checks, then aim for 15-30 minutes."
        ]
    if readiness in {MODELING_DATASET_USABLE, MODELING_DATASET_GOOD}:
        return [
            "Exportable for pipeline tests only; collect 5-15 minutes before judging voice quality."
        ]
    return []


def format_modeling_dataset_duration(seconds: float) -> str:
    seconds = max(0, round(float(seconds)))
    minutes, seconds = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _progress_percent(value: float, target: float) -> int:
    if target <= 0:
        return 0
    return min(100, max(0, round((float(value) / target) * 100)))


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
        "guided_prompt_history": existing.get("guided_prompt_history", []) if existing else [],
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
    if mode in {MODELING_CLIP_TEXT_GUIDED, MODELING_CLIP_FREE_RECORDING}:
        normalized_mode = mode
    else:
        normalized_mode = MODELING_CLIP_FREE_RECORDING
    clip: ModelingClip = {
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
    raw_mode = value.get("mode")
    if isinstance(raw_mode, str) and raw_mode in {MODELING_CLIP_TEXT_GUIDED, MODELING_CLIP_FREE_RECORDING}:
        normalized_mode = raw_mode
    else:
        normalized_mode = MODELING_CLIP_FREE_RECORDING
    transcript_path = _string_or_default(value.get("transcript_path"))
    transcript_text = _string_or_default(value.get("transcript_text"))
    transcript_source = _string_or_default(value.get("transcript_source"))
    status = _string_or_default(value.get("status"), MODELING_CLIP_NEEDS_TRANSCRIPT)
    language_code = _string_or_default(value.get("language_code"), "it")
    clip: ModelingClip = {
        "id": clip_id,
        "mode": normalized_mode,
        "audio_path": audio_path,
        "transcript_path": transcript_path,
        "transcript_text": transcript_text,
        "transcript_source": transcript_source,
        "language_code": language_code,
        "duration_seconds": _float(value.get("duration_seconds")),
        "quality_details": _string_or_default(value.get("quality_details")),
        "status": status,
        "created_at": _string_or_default(value.get("created_at"), timestamp),
        "updated_at": _string_or_default(value.get("updated_at"), timestamp),
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
    raw_clips = value.get("clips")
    clips: list[ModelingClip] = []
    if isinstance(raw_clips, list):
        for raw_clip in raw_clips:
            clip = normalized_modeling_clip(raw_clip)
            if clip is not None:
                clips.append(clip)
    guided_prompt_history = normalized_guided_prompt_history(value.get("guided_prompt_history"))
    dataset: ModelingDataset = {
        "id": dataset_id,
        "profile_id": profile_id,
        "name": name,
        "language_code": _string_or_default(value.get("language_code"), "it"),
        "clips": clips,
        "guided_prompt_history": guided_prompt_history,
        "created_at": _string_or_default(value.get("created_at"), timestamp),
        "updated_at": _string_or_default(value.get("updated_at"), timestamp),
    }
    return dataset


def load_modeling_datasets(path: Path | None = None) -> list[ModelingDataset]:
    config_path = path or modeling_datasets_config_path()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict) and not app_json_version_supported(data, kind=MODELING_DATASETS_JSON_KIND):
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
        json.dumps(
            with_schema_metadata({"datasets": datasets}, MODELING_DATASETS_JSON_KIND),
            indent=2,
            ensure_ascii=False,
        ) + "\n",
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


def normalized_guided_prompt_history(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    prompts: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        normalized_text = normalize_prompt_text(item)
        if not normalized_text or normalized_text in seen:
            continue
        prompts.append(normalized_text)
        seen.add(normalized_text)
    return prompts


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _string_or_default(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _quality_percent(details: str, label: str) -> float | None:
    if not isinstance(details, str):
        return None
    match = re.search(rf"^{re.escape(label)}:\s*([0-9]+(?:\.[0-9]+)?)%", details, flags=re.MULTILINE)
    if not match:
        return None
    return _float(match.group(1))


def _quality_db(details: str, label: str) -> float | None:
    if not isinstance(details, str):
        return None
    match = re.search(rf"^{re.escape(label)}:\s*([0-9]+(?:\.[0-9]+)?)\s*dB", details, flags=re.MULTILINE)
    if not match:
        return None
    return _float(match.group(1))
