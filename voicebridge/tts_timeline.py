import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

TTS_TIMELINE_KIND = "voicebridge_tts_timeline"
LOCAL_TTS_CHUNKS_KIND = "voicebridge_local_tts_chunks"
TTS_TIMELINE_SCHEMA_VERSION = 1


def tts_timeline_path(audio_path: str | Path) -> Path:
    path = Path(audio_path)
    return path.with_name(f"{path.stem}.voicebridge-tts.json")


def remove_tts_timeline(audio_path: str | Path) -> None:
    with suppress(OSError):
        tts_timeline_path(audio_path).unlink(missing_ok=True)


def _timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _seconds(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, round(float(value), 6))
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_block(block: dict[str, Any], fallback_index: int) -> dict[str, Any] | None:
    start = _seconds(block.get("start_seconds"))
    end = _seconds(block.get("end_seconds"))
    if end <= start:
        duration = _seconds(block.get("duration_seconds"))
        end = round(start + duration, 6)
    if end <= start:
        return None

    cleaned = {
        "id": _text(block.get("id")) or f"block-{fallback_index:04d}",
        "index": _int(block.get("index"), fallback_index),
        "source_block_index": _int(block.get("source_block_index"), fallback_index),
        "chunk_index": _int(block.get("chunk_index"), 1),
        "start_seconds": start,
        "end_seconds": end,
        "duration_seconds": round(end - start, 6),
        "text": _text(block.get("text")),
    }
    for key in ("voice_label", "voice_short_name", "voice_profile_id", "language_code", "rate"):
        value = _text(block.get(key))
        if value:
            cleaned[key] = value
    return cleaned


def write_tts_timeline(
    audio_path: str | Path,
    *,
    engine: str,
    mode: str,
    blocks: list[dict[str, Any]],
    source_path: str | Path | None = None,
    total_duration_seconds: float | None = None,
) -> Path:
    cleaned_blocks = [
        cleaned
        for index, block in enumerate(blocks, start=1)
        if (cleaned := _clean_block(block, index)) is not None
    ]
    if not cleaned_blocks:
        raise ValueError("Cannot write a TTS timeline without valid blocks.")

    audio = Path(audio_path)
    total_duration = _seconds(total_duration_seconds, cleaned_blocks[-1]["end_seconds"])
    data = {
        "schema_version": TTS_TIMELINE_SCHEMA_VERSION,
        "kind": TTS_TIMELINE_KIND,
        "created_at": _timestamp(),
        "audio_path": str(audio.resolve()),
        "source_path": str(Path(source_path).resolve()) if source_path else "",
        "engine": engine,
        "mode": mode,
        "total_duration_seconds": total_duration,
        "blocks": cleaned_blocks,
    }
    timeline_path = tts_timeline_path(audio)
    timeline_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return timeline_path


def load_tts_timeline_for_audio(audio_path: str | Path) -> dict[str, Any] | None:
    timeline_path = tts_timeline_path(audio_path)
    if not timeline_path.is_file():
        return None
    try:
        data = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("schema_version") != TTS_TIMELINE_SCHEMA_VERSION or data.get("kind") != TTS_TIMELINE_KIND:
        return None
    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        return None
    cleaned_blocks = [
        cleaned
        for index, block in enumerate(blocks, start=1)
        if isinstance(block, dict) and (cleaned := _clean_block(block, index)) is not None
    ]
    if not cleaned_blocks:
        return None
    data["blocks"] = cleaned_blocks
    data["metadata_path"] = str(timeline_path)
    return data


def write_local_tts_chunk_timeline(
    metadata_path: str | Path,
    *,
    audio_path: str | Path,
    chunks: list[dict[str, Any]],
    total_duration_seconds: float,
) -> None:
    data = {
        "schema_version": TTS_TIMELINE_SCHEMA_VERSION,
        "kind": LOCAL_TTS_CHUNKS_KIND,
        "created_at": _timestamp(),
        "audio_path": str(Path(audio_path).resolve()),
        "total_duration_seconds": _seconds(total_duration_seconds),
        "chunks": [
            cleaned
            for index, chunk in enumerate(chunks, start=1)
            if (cleaned := _clean_block(chunk, index)) is not None
        ],
    }
    Path(metadata_path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_local_tts_chunk_timeline(metadata_path: str | Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if data.get("schema_version") != TTS_TIMELINE_SCHEMA_VERSION or data.get("kind") != LOCAL_TTS_CHUNKS_KIND:
        return []
    chunks = data.get("chunks")
    if not isinstance(chunks, list):
        return []
    return [
        cleaned
        for index, chunk in enumerate(chunks, start=1)
        if isinstance(chunk, dict) and (cleaned := _clean_block(chunk, index)) is not None
    ]
