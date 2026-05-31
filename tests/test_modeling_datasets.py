from pathlib import Path

import pytest

from voicebridge.modeling_datasets import (
    MODELING_CLIP_FREE_RECORDING,
    MODELING_CLIP_NEEDS_TRANSCRIPT,
    MODELING_CLIP_READY,
    build_modeling_clip,
    build_modeling_dataset_for_profile,
    ensure_modeling_datasets_for_profiles,
    load_modeling_datasets,
    modeling_clip_audio_path,
    modeling_clip_status_label,
    modeling_clip_transcript_path,
    modeling_dataset_dir,
    modeling_datasets_root,
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
    loaded = load_modeling_datasets(config_path)

    assert loaded == [dataset]
