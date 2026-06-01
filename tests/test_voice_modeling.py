import json
from pathlib import Path

import pytest

from voicebridge.modeling_datasets import (
    MODELING_CLIP_FREE_RECORDING,
    build_modeling_clip,
    build_modeling_dataset_for_profile,
    export_modeling_dataset,
)
from voicebridge.voice_modeling import (
    build_voice_modeling_job_config,
    default_voice_modeling_output_dir,
    save_voice_modeling_job_config,
    validate_voice_modeling_export,
    voice_modeling_export_summary_text,
)
from voicebridge.voice_profiles import VOICE_PROFILE_MODELING, build_voice_profile


def exported_dataset(tmp_path: Path) -> Path:
    profile = build_voice_profile(
        name="Dataset Voice",
        language_code="en",
        profile_type=VOICE_PROFILE_MODELING,
        reference_paths=[],
        consent_confirmed=True,
    )
    dataset = build_modeling_dataset_for_profile(profile)
    for index in range(5):
        audio_path = tmp_path / f"clip-{index}.wav"
        audio_path.write_bytes(f"RIFF {index}".encode())
        dataset["clips"].append(
            build_modeling_clip(
                dataset,
                mode=MODELING_CLIP_FREE_RECORDING,
                audio_path=audio_path,
                transcript_text=f"Clip {index}",
                duration_seconds=12.0,
                quality_details="RMS level: 8%\nInput clipping: 0.00%",
                clip_id=f"clip-{index}",
            )
        )
    result = export_modeling_dataset(dataset, export_root=tmp_path / "exports", timestamp="20260601-120000")
    return Path(result["export_dir"])


def test_validate_voice_modeling_export_reads_exported_dataset(tmp_path: Path) -> None:
    export_dir = exported_dataset(tmp_path)

    export_info = validate_voice_modeling_export(export_dir)

    assert export_info["name"] == "Dataset Voice"
    assert export_info["language_code"] == "en"
    assert export_info["readiness"] == "usable"
    assert export_info["ready_clips"] == 5
    assert export_info["metadata_rows"] == 5
    assert "Dataset: Dataset Voice" in voice_modeling_export_summary_text(export_info)


def test_validate_voice_modeling_export_rejects_bad_metadata(tmp_path: Path) -> None:
    export_dir = exported_dataset(tmp_path)
    (export_dir / "metadata.csv").write_text("missing separator\n", encoding="utf-8")

    with pytest.raises(ValueError, match="wav_path\\|text"):
        validate_voice_modeling_export(export_dir)


def test_build_and_save_voice_modeling_job_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    export_dir = exported_dataset(tmp_path)
    export_info = validate_voice_modeling_export(export_dir)
    monkeypatch.setattr("voicebridge.voice_modeling.external_base_dir", lambda: tmp_path)
    resume_checkpoint = tmp_path / "resume.pth"
    resume_checkpoint.write_bytes(b"checkpoint")

    default_output = default_voice_modeling_output_dir(export_info, timestamp="20260601-130000")
    config = build_voice_modeling_job_config(
        export_info,
        output_dir=default_output,
        resume_checkpoint=resume_checkpoint,
        device="cuda",
        max_epochs=80,
        batch_size=4,
    )
    config_path = save_voice_modeling_job_config(config)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert config_path == default_output / "job_config.json"
    assert saved["training_backend"] == "xtts_v2"
    assert saved["device"] == "cuda"
    assert saved["max_epochs"] == 80
    assert saved["batch_size"] == 4
    assert saved["resume_checkpoint"] == str(resume_checkpoint)
    assert saved["dataset"]["metadata_rows"] == 5


def test_build_voice_modeling_job_config_rejects_missing_resume(tmp_path: Path) -> None:
    export_dir = exported_dataset(tmp_path)
    export_info = validate_voice_modeling_export(export_dir)

    with pytest.raises(ValueError, match="Resume checkpoint"):
        build_voice_modeling_job_config(export_info, resume_checkpoint=tmp_path / "missing.pth")
