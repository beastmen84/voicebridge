import json
from pathlib import Path

import pytest

from voicebridge.json_schemas import (
    MODELING_DATASET_EXPORT_JSON_KIND,
    MODELING_DATASETS_JSON_KIND,
    current_schema_version,
)
from voicebridge.modeling_datasets import (
    MODELING_CLIP_FREE_RECORDING,
    MODELING_CLIP_NEEDS_TRANSCRIPT,
    MODELING_CLIP_READY,
    MODELING_DATASET_GOOD,
    MODELING_DATASET_NOT_READY,
    MODELING_DATASET_TIER_BASE,
    MODELING_DATASET_TIER_HIGH_QUALITY,
    MODELING_DATASET_TIER_TEST,
    MODELING_DATASET_USABLE,
    add_modeling_dataset_guided_prompt_history,
    build_modeling_clip,
    build_modeling_dataset_for_profile,
    ensure_modeling_datasets_for_profiles,
    export_modeling_dataset,
    load_modeling_datasets,
    modeling_clip_audio_path,
    modeling_clip_status_label,
    modeling_clip_transcript_path,
    modeling_dataset_dir,
    modeling_dataset_exportable,
    modeling_dataset_guided_prompt_texts,
    modeling_dataset_guided_prompt_usage,
    modeling_dataset_summary,
    modeling_dataset_summary_text,
    modeling_datasets_root,
    reset_modeling_dataset_guided_prompt_history,
    save_modeling_datasets,
    update_modeling_clip_transcript,
    write_modeling_clip_transcript,
)
from voicebridge.voice_profiles import VOICE_PROFILE_MODELING, VOICE_PROFILE_REFERENCE, build_voice_profile


def test_ensure_modeling_dataset_for_modeling_profile_only(tmp_path: Path) -> None:
    modeling = build_voice_profile(
        name="Model Voice",
        language_code="it",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    reference = build_voice_profile(
        name="Reference",
        language_code="it",
        profile_type=VOICE_PROFILE_REFERENCE,
        reference_paths=[str(tmp_path / "ref.wav")],
        consent_confirmed=True,
    )

    datasets, changed = ensure_modeling_datasets_for_profiles([], [reference, modeling])

    assert changed is True
    assert len(datasets) == 1
    assert datasets[0]["profile_id"] == modeling["id"]
    assert datasets[0]["name"] == "Model Voice"


def test_modeling_dataset_paths_live_under_voice_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("voicebridge.voice_profiles.external_base_dir", lambda: tmp_path)
    profile = build_voice_profile(
        name="Model Voice",
        language_code="it",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)

    dataset_dir = tmp_path / "voice_profiles" / "modeling_dataset" / "model-voice"

    assert modeling_datasets_root() == tmp_path / "voice_profiles" / "modeling_dataset"
    assert modeling_dataset_dir(dataset) == dataset_dir
    assert modeling_clip_audio_path(dataset, "clip-1") == dataset_dir / "clips" / "clip-1.wav"
    assert modeling_clip_transcript_path(dataset, "clip-1") == dataset_dir / "transcripts" / "clip-1.txt"


def test_modeling_clip_transcript_sidecar(tmp_path: Path) -> None:
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"RIFF")
    clip = build_modeling_clip(
        dataset,
        mode=MODELING_CLIP_FREE_RECORDING,
        audio_path=audio_path,
        transcript_text="",
        clip_id="clip-1",
    )

    assert clip["status"] == MODELING_CLIP_NEEDS_TRANSCRIPT
    updated = update_modeling_clip_transcript(clip, "Hello world")
    updated["transcript_path"] = str(tmp_path / "clip.txt")
    write_modeling_clip_transcript(updated)

    assert updated["status"] == MODELING_CLIP_READY
    assert Path(updated["transcript_path"]).read_text(encoding="utf-8") == "Hello world\n"
    assert modeling_clip_status_label(updated["status"]) == "Ready"


def test_modeling_dataset_guided_prompt_history_counts_unique_used_prompts(tmp_path: Path) -> None:
    profile = build_voice_profile(
        name="Dataset",
        language_code="it",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    assert add_modeling_dataset_guided_prompt_history(dataset, "Prompt one") is True
    assert add_modeling_dataset_guided_prompt_history(dataset, "Prompt one") is False
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"RIFF")
    dataset["clips"].append(
        build_modeling_clip(
            dataset,
            mode=MODELING_CLIP_FREE_RECORDING,
            audio_path=audio_path,
            transcript_text="Prompt two",
            transcript_source="generated_prompt:1.0",
            duration_seconds=12.0,
            clip_id="clip",
        )
    )

    used_count, available_count = modeling_dataset_guided_prompt_usage(dataset)

    assert used_count == 2
    assert available_count == 262_144
    assert modeling_dataset_guided_prompt_texts(dataset) == ("Prompt one", "Prompt two")
    assert reset_modeling_dataset_guided_prompt_history(dataset) is True
    assert modeling_dataset_guided_prompt_texts(dataset) == ("Prompt two",)


def test_export_modeling_dataset_copies_ready_clips(tmp_path: Path) -> None:
    profile = build_voice_profile(
        name="Dataset Voice",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    pending_audio = tmp_path / "pending.wav"
    pending_audio.write_bytes(b"RIFF pending")
    for index in range(5):
        ready_audio = tmp_path / f"ready-{index}.wav"
        ready_audio.write_bytes(f"RIFF ready {index}".encode())
        dataset["clips"].append(
            build_modeling_clip(
                dataset,
                mode=MODELING_CLIP_FREE_RECORDING,
                audio_path=ready_audio,
                transcript_text=f"Hello | world\nfrom dataset {index}",
                transcript_source="generated_prompt:1.0" if index == 0 else "",
                duration_seconds=12.0,
                quality_details="RMS level: 8%\nInput clipping: 0.00%",
                clip_id=f"ready/{index}",
            )
        )
    dataset["clips"].append(
        build_modeling_clip(
            dataset,
            mode=MODELING_CLIP_FREE_RECORDING,
            audio_path=pending_audio,
            duration_seconds=12.0,
            clip_id="pending",
        )
    )

    result = export_modeling_dataset(dataset, export_root=tmp_path / "exports", timestamp="20260601-120000")

    export_dir = Path(result["export_dir"])
    exported_wav = export_dir / "wavs" / "0001_ready-0.wav"
    metadata_path = export_dir / "metadata.csv"
    dataset_json_path = export_dir / "dataset.json"
    assert result["exported_clips"] == 5
    assert result["skipped_clips"] == 1
    assert exported_wav.read_bytes() == b"RIFF ready 0"
    metadata_lines = metadata_path.read_text(encoding="utf-8").splitlines()
    assert metadata_lines[0] == (
        "wavs/0001_ready-0.wav|Hello , world from dataset 0"
    )
    export_data = json.loads(dataset_json_path.read_text(encoding="utf-8"))
    assert export_data["schema_version"] == current_schema_version(MODELING_DATASET_EXPORT_JSON_KIND)
    assert export_data["kind"] == MODELING_DATASET_EXPORT_JSON_KIND
    assert export_data["name"] == "Dataset Voice"
    assert export_data["language_code"] == "en"
    assert export_data["metadata_format"] == "relative_wav_path|transcript_text"
    assert export_data["exported_clips"][0]["export_audio_path"] == "wavs/0001_ready-0.wav"
    assert export_data["exported_clips"][0]["transcript_source"] == "generated_prompt:1.0"
    assert len(metadata_lines) == len(export_data["exported_clips"])
    for index, (metadata_line, exported_clip) in enumerate(
        zip(metadata_lines, export_data["exported_clips"], strict=True)
    ):
        export_audio_path, transcript_text = metadata_line.split("|", 1)
        assert export_audio_path == exported_clip["export_audio_path"]
        assert transcript_text == exported_clip["transcript_text"]
        assert (export_dir / export_audio_path).read_bytes() == f"RIFF ready {index}".encode()


def test_export_modeling_dataset_rejects_without_ready_clips(tmp_path: Path) -> None:
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)

    with pytest.raises(ValueError, match="Usable readiness"):
        export_modeling_dataset(dataset, export_root=tmp_path / "exports", timestamp="20260601-120000")


def test_export_modeling_dataset_rejects_before_usable_readiness(tmp_path: Path) -> None:
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    audio_path = tmp_path / "ready.wav"
    audio_path.write_bytes(b"RIFF")
    dataset["clips"].append(
        build_modeling_clip(
            dataset,
            mode=MODELING_CLIP_FREE_RECORDING,
            audio_path=audio_path,
            transcript_text="Ready but not enough data",
            duration_seconds=12.0,
            clip_id="ready",
        )
    )

    assert modeling_dataset_exportable(dataset) is False
    with pytest.raises(ValueError, match="Usable readiness"):
        export_modeling_dataset(dataset, export_root=tmp_path / "exports", timestamp="20260601-120000")


def test_modeling_dataset_summary_reports_not_ready_without_clips() -> None:
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)

    summary = modeling_dataset_summary(dataset)

    assert summary["readiness"] == MODELING_DATASET_NOT_READY
    assert summary["ready_clips"] == 0
    assert "Add at least one ready clip" in summary["issues"][0]
    assert "Export readiness: Not ready" in modeling_dataset_summary_text(dataset)


def test_modeling_dataset_summary_uses_ready_clip_subset(tmp_path: Path) -> None:
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    for index in range(5):
        audio_path = tmp_path / f"ready-{index}.wav"
        audio_path.write_bytes(b"RIFF")
        dataset["clips"].append(
            build_modeling_clip(
                dataset,
                mode=MODELING_CLIP_FREE_RECORDING,
                audio_path=audio_path,
                transcript_text=f"Ready clip {index}",
                duration_seconds=12.0,
                quality_details="RMS level: 8%\nInput clipping: 0.00%",
                clip_id=f"ready-{index}",
            )
        )
    pending_audio = tmp_path / "pending.wav"
    pending_audio.write_bytes(b"RIFF")
    dataset["clips"].append(
        build_modeling_clip(
            dataset,
            mode=MODELING_CLIP_FREE_RECORDING,
            audio_path=pending_audio,
            duration_seconds=12.0,
            clip_id="pending",
        )
    )
    dataset["clips"].append(
        build_modeling_clip(
            dataset,
            mode=MODELING_CLIP_FREE_RECORDING,
            audio_path=tmp_path / "missing.wav",
            transcript_text="Missing audio",
            duration_seconds=12.0,
            clip_id="missing",
        )
    )

    summary = modeling_dataset_summary(dataset)

    assert summary["readiness"] == MODELING_DATASET_USABLE
    assert summary["dataset_tier"] == MODELING_DATASET_TIER_TEST
    assert summary["ready_clips"] == 5
    assert summary["total_clips"] == 7
    assert summary["ready_duration_seconds"] == 60.0
    assert summary["pending_transcript_clips"] == 1
    assert summary["missing_audio_clips"] == 1
    assert summary["target_reached"] is False
    assert any("need transcript" in issue for issue in summary["issues"])
    assert any("missing their WAV" in issue for issue in summary["issues"])
    assert any("Exportable for pipeline tests" in recommendation for recommendation in summary["recommendations"])


def test_modeling_dataset_summary_flags_clip_quality(tmp_path: Path) -> None:
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    for clip_id, duration, quality_details in (
        ("short", 4.0, "RMS level: 8%\nInput clipping: 0.00%"),
        ("long", 61.0, "RMS level: 8%\nInput clipping: 0.00%"),
        ("quiet", 12.0, "RMS level: 1%\nInput clipping: 0.00%"),
        ("clipped", 12.0, "RMS level: 8%\nInput clipping: 0.50%"),
        ("noisy", 12.0, "RMS level: 8%\nEstimated SNR: 12.5 dB\nInput clipping: 0.00%"),
    ):
        audio_path = tmp_path / f"{clip_id}.wav"
        audio_path.write_bytes(b"RIFF")
        dataset["clips"].append(
            build_modeling_clip(
                dataset,
                mode=MODELING_CLIP_FREE_RECORDING,
                audio_path=audio_path,
                transcript_text=f"{clip_id} text",
                duration_seconds=duration,
                quality_details=quality_details,
                clip_id=clip_id,
            )
        )

    summary = modeling_dataset_summary(dataset)

    assert summary["short_ready_clips"] == 1
    assert summary["long_ready_clips"] == 1
    assert summary["low_level_clips"] == 1
    assert summary["clipping_clips"] == 1
    assert summary["noisy_clips"] == 1


def test_modeling_dataset_summary_reports_good_dataset(tmp_path: Path) -> None:
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    for index in range(20):
        audio_path = tmp_path / f"good-{index}.wav"
        audio_path.write_bytes(b"RIFF")
        dataset["clips"].append(
            build_modeling_clip(
                dataset,
                mode=MODELING_CLIP_FREE_RECORDING,
                audio_path=audio_path,
                transcript_text=f"Good clip {index}",
                duration_seconds=30.0,
                quality_details="RMS level: 8%\nInput clipping: 0.00%",
                clip_id=f"good-{index}",
            )
        )

    summary = modeling_dataset_summary(dataset)

    assert summary["readiness"] == MODELING_DATASET_GOOD
    assert summary["dataset_tier"] == MODELING_DATASET_TIER_BASE
    assert summary["ready_duration_seconds"] == 600.0
    assert summary["target_reached"] is False
    assert summary["target_clips_percent"] == 33
    assert summary["target_duration_percent"] == 33
    assert summary["issues"] == []
    assert any("Base dataset" in recommendation for recommendation in summary["recommendations"])


def test_modeling_dataset_summary_reports_target_dataset(tmp_path: Path) -> None:
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    for index in range(60):
        audio_path = tmp_path / f"target-{index}.wav"
        audio_path.write_bytes(b"RIFF")
        dataset["clips"].append(
            build_modeling_clip(
                dataset,
                mode=MODELING_CLIP_FREE_RECORDING,
                audio_path=audio_path,
                transcript_text=f"Target clip {index}",
                duration_seconds=30.0,
                quality_details="RMS level: 8%\nInput clipping: 0.00%",
                clip_id=f"target-{index}",
            )
        )

    summary = modeling_dataset_summary(dataset)
    summary_text = modeling_dataset_summary_text(dataset)

    assert summary["readiness"] == MODELING_DATASET_GOOD
    assert summary["dataset_tier"] == MODELING_DATASET_TIER_HIGH_QUALITY
    assert summary["target_reached"] is True
    assert summary["target_clips_percent"] == 100
    assert summary["target_duration_percent"] == 100
    assert summary["issues"] == []
    assert any("High-quality duration reached" in recommendation for recommendation in summary["recommendations"])
    assert "Target progress: 60/60 clips, 30m 00s/30m 00s" in summary_text
    assert "Recommended target: 60-120 ready clips, 30m 00s-60m 00s clean audio" in summary_text
    assert "Dataset tier: High quality" in summary_text


def test_save_and_load_modeling_datasets(tmp_path: Path) -> None:
    profile = build_voice_profile(
        name="Dataset",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    config_path = tmp_path / "modeling_datasets.json"

    save_modeling_datasets([dataset], config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    loaded = load_modeling_datasets(config_path)

    assert saved["schema_version"] == current_schema_version(MODELING_DATASETS_JSON_KIND)
    assert saved["kind"] == MODELING_DATASETS_JSON_KIND
    assert loaded == [dataset]


def test_load_modeling_datasets_accepts_version_1_0_without_guided_history(tmp_path: Path) -> None:
    config_path = tmp_path / "modeling_datasets.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "kind": MODELING_DATASETS_JSON_KIND,
                "datasets": [
                    {
                        "id": "dataset-1",
                        "profile_id": "profile-1",
                        "name": "Dataset",
                        "language_code": "it",
                        "clips": [],
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-01T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_modeling_datasets(config_path)

    assert loaded[0]["guided_prompt_history"] == []
