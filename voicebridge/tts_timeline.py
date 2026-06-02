import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from voicebridge.json_schemas import (
    LOCAL_TTS_CHUNKS_JSON_KIND,
    TTS_TIMELINE_JSON_KIND,
    app_json_version_supported,
    current_schema_version,
)

TTS_TIMELINE_KIND = TTS_TIMELINE_JSON_KIND
LOCAL_TTS_CHUNKS_KIND = LOCAL_TTS_CHUNKS_JSON_KIND
TTS_TIMELINE_SCHEMA_VERSION = current_schema_version(TTS_TIMELINE_KIND)
LOCAL_TTS_CHUNKS_SCHEMA_VERSION = current_schema_version(LOCAL_TTS_CHUNKS_KIND)


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

    cleaned: dict[str, Any] = {
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
    if _is_true(block.get("edited")):
        cleaned["edited"] = True
    for key in ("contains_cut", "contains_silence", "contains_fade"):
        if _is_true(block.get(key)):
            cleaned[key] = True
    cleanup_actions = block.get("cleanup_actions")
    if isinstance(cleanup_actions, list):
        actions = [_text(action) for action in cleanup_actions if _text(action)]
        if actions:
            cleaned["cleanup_actions"] = actions
    return cleaned


def _is_true(value: Any) -> bool:
    return value is True


def block_overlaps_range(block: dict[str, Any], start_seconds: float, end_seconds: float) -> bool:
    return block["start_seconds"] < end_seconds and block["end_seconds"] > start_seconds


def mark_block_edited(block: dict[str, Any], action: str) -> dict[str, Any]:
    updated = dict(block)
    updated["edited"] = True
    if action == "remove":
        updated["contains_cut"] = True
    elif action == "silence":
        updated["contains_silence"] = True
    elif action == "fade":
        updated["contains_fade"] = True
    actions = list(updated.get("cleanup_actions") or [])
    if action not in actions:
        actions.append(action)
    updated["cleanup_actions"] = actions
    return updated


def transformed_block_after_cut(
    block: dict[str, Any],
    start_seconds: float,
    end_seconds: float,
) -> dict[str, Any] | None:
    block_start = block["start_seconds"]
    block_end = block["end_seconds"]
    cut_seconds = max(0.0, end_seconds - start_seconds)
    if block_end <= start_seconds:
        return dict(block)
    if block_start >= end_seconds:
        shifted = dict(block)
        shifted["start_seconds"] = round(block_start - cut_seconds, 6)
        shifted["end_seconds"] = round(block_end - cut_seconds, 6)
        shifted["duration_seconds"] = round(shifted["end_seconds"] - shifted["start_seconds"], 6)
        return shifted
    if block_start >= start_seconds and block_end <= end_seconds:
        return None

    updated = mark_block_edited(block, "remove")
    if block_start < start_seconds and block_end > end_seconds:
        updated["start_seconds"] = block_start
        updated["end_seconds"] = round(block_end - cut_seconds, 6)
    elif block_start < start_seconds:
        updated["start_seconds"] = block_start
        updated["end_seconds"] = start_seconds
    else:
        updated["start_seconds"] = start_seconds
        updated["end_seconds"] = round(block_end - cut_seconds, 6)
    updated["duration_seconds"] = round(updated["end_seconds"] - updated["start_seconds"], 6)
    if updated["end_seconds"] <= updated["start_seconds"]:
        return None
    return updated


def transform_tts_timeline_blocks_for_cleanup(
    blocks: list[dict[str, Any]],
    *,
    action: str,
    start_seconds: float,
    end_seconds: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cleaned_blocks: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            continue
        cleaned = _clean_block(block, index)
        if cleaned is not None:
            cleaned_blocks.append(cleaned)
    if action == "remove":
        updated_blocks: list[dict[str, Any]] = []
        removed_blocks: list[dict[str, Any]] = []
        for block in cleaned_blocks:
            updated = transformed_block_after_cut(block, start_seconds, end_seconds)
            if updated is None:
                removed_blocks.append(mark_block_edited(block, action))
            else:
                updated_blocks.append(updated)
    else:
        updated_blocks = [
            mark_block_edited(block, action) if block_overlaps_range(block, start_seconds, end_seconds) else block
            for block in cleaned_blocks
        ]
        removed_blocks: list[dict[str, Any]] = []

    reindexed_blocks: list[dict[str, Any]] = []
    for index, block in enumerate(updated_blocks, start=1):
        reindexed = dict(block)
        reindexed["index"] = index
        reindexed_blocks.append(reindexed)
    return reindexed_blocks, removed_blocks


def write_tts_timeline(
    audio_path: str | Path,
    *,
    engine: str,
    mode: str,
    blocks: list[dict[str, Any]],
    source_path: str | Path | None = None,
    total_duration_seconds: float | None = None,
) -> Path:
    cleaned_blocks: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        cleaned = _clean_block(block, index)
        if cleaned is not None:
            cleaned_blocks.append(cleaned)
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


def write_audio_cleanup_timeline(
    input_audio_path: str | Path,
    output_audio_path: str | Path,
    *,
    action: str,
    start_seconds: float,
    end_seconds: float,
    total_duration_seconds: float | None = None,
) -> Path | None:
    return write_audio_cleanup_timeline_for_changes(
        input_audio_path,
        output_audio_path,
        changes=[
            {
                "action": action,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
            }
        ],
        total_duration_seconds=total_duration_seconds,
    )


def write_audio_cleanup_timeline_for_changes(
    input_audio_path: str | Path,
    output_audio_path: str | Path,
    *,
    changes: list[dict[str, Any]],
    total_duration_seconds: float | None = None,
) -> Path | None:
    timeline = load_tts_timeline_for_audio(input_audio_path)
    if not timeline:
        remove_tts_timeline(output_audio_path)
        return None

    valid_changes = []
    for change in changes:
        action = _text(change.get("action"))
        start = _seconds(change.get("start_seconds"))
        end = _seconds(change.get("end_seconds"))
        if not action or end <= start:
            continue
        valid_changes.append({**change, "action": action, "start_seconds": start, "end_seconds": end})
    if not valid_changes:
        remove_tts_timeline(output_audio_path)
        return None

    updated_blocks = timeline["blocks"]
    removed_blocks_by_change = []
    for change in valid_changes:
        updated_blocks, removed_blocks = transform_tts_timeline_blocks_for_cleanup(
            updated_blocks,
            action=change["action"],
            start_seconds=change["start_seconds"],
            end_seconds=change["end_seconds"],
        )
        removed_blocks_by_change.append(removed_blocks)
        if not updated_blocks:
            remove_tts_timeline(output_audio_path)
            return None

    input_audio = Path(input_audio_path)
    output_audio = Path(output_audio_path)
    previous_edits = timeline.get("edits")
    edits = list(previous_edits) if isinstance(previous_edits, list) else []
    for change_index, change in enumerate(valid_changes):
        edit = {
            "index": len(edits) + 1,
            "action": change["action"],
            "source_audio_path": str(input_audio.resolve()),
            "start_seconds": change["start_seconds"],
            "end_seconds": change["end_seconds"],
            "duration_seconds": round(change["end_seconds"] - change["start_seconds"], 6),
            "text_policy": "Block text is preserved as an operational guide and is not rewritten after cleanup.",
        }
        for source_key, target_key in (
            ("source_start_seconds", "original_source_start_seconds"),
            ("source_end_seconds", "original_source_end_seconds"),
        ):
            if source_key in change:
                edit[target_key] = _seconds(change[source_key])
        removed_blocks = removed_blocks_by_change[change_index]
        if removed_blocks:
            edit["removed_blocks"] = removed_blocks
        edits.append(edit)

    total_duration = _seconds(total_duration_seconds, updated_blocks[-1]["end_seconds"])
    data = {
        "schema_version": TTS_TIMELINE_SCHEMA_VERSION,
        "kind": TTS_TIMELINE_KIND,
        "created_at": _timestamp(),
        "audio_path": str(output_audio.resolve()),
        "source_path": _text(timeline.get("source_path")),
        "engine": _text(timeline.get("engine")),
        "mode": _text(timeline.get("mode")),
        "total_duration_seconds": total_duration,
        "blocks": updated_blocks,
        "edits": edits,
    }
    timeline_path = tts_timeline_path(output_audio)
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
    if not app_json_version_supported(data, kind=TTS_TIMELINE_KIND, allow_legacy_missing=False):
        return None
    blocks = data.get("blocks")
    if not isinstance(blocks, list):
        return None
    cleaned_blocks: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        if not isinstance(block, dict):
            continue
        cleaned = _clean_block(block, index)
        if cleaned is not None:
            cleaned_blocks.append(cleaned)
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
    cleaned_chunks: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        cleaned = _clean_block(chunk, index)
        if cleaned is not None:
            cleaned_chunks.append(cleaned)
    data = {
        "schema_version": LOCAL_TTS_CHUNKS_SCHEMA_VERSION,
        "kind": LOCAL_TTS_CHUNKS_KIND,
        "created_at": _timestamp(),
        "audio_path": str(Path(audio_path).resolve()),
        "total_duration_seconds": _seconds(total_duration_seconds),
        "chunks": cleaned_chunks,
    }
    Path(metadata_path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_local_tts_chunk_timeline(metadata_path: str | Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not app_json_version_supported(data, kind=LOCAL_TTS_CHUNKS_KIND, allow_legacy_missing=False):
        return []
    chunks = data.get("chunks")
    if not isinstance(chunks, list):
        return []
    cleaned_chunks: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            continue
        cleaned = _clean_block(chunk, index)
        if cleaned is not None:
            cleaned_chunks.append(cleaned)
    return cleaned_chunks
