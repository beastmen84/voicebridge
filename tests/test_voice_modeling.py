import json
import os
from hashlib import sha256
from pathlib import Path

import pytest

from voicebridge.json_schemas import (
    VOICE_MODELING_JOB_CONFIG_JSON_KIND,
    VOICE_MODELING_TRAINING_STATE_JSON_KIND,
    current_schema_version,
)
from voicebridge.modeling_datasets import (
    MODELING_CLIP_FREE_RECORDING,
    build_modeling_clip,
    build_modeling_dataset_for_profile,
    export_modeling_dataset,
)
from voicebridge.voice_modeling import (
    build_voice_modeling_job_config,
    build_voice_modeling_training_command,
    check_voice_modeling_preflight,
    default_voice_modeling_output_dir,
    download_file_to_path,
    list_voice_modeling_exports,
    list_voice_modeling_job_configs,
    prepare_voice_modeling_training_job,
    save_voice_modeling_job_config,
    validate_voice_modeling_export,
    voice_modeling_export_label,
    voice_modeling_export_summary_text,
    voice_modeling_job_label,
    voice_modeling_training_plan_text,
)
from voicebridge.voice_profiles import VOICE_PROFILE_MODELING, build_voice_profile


def exported_dataset(
    tmp_path: Path,
    *,
    name: str = "Dataset Voice",
    timestamp: str = "20260601-120000",
) -> Path:
    profile = build_voice_profile(
        name=name,
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
    result = export_modeling_dataset(dataset, export_root=tmp_path / "exports", timestamp=timestamp)
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


def test_list_voice_modeling_exports_returns_valid_exports_first(tmp_path: Path) -> None:
    older_export = exported_dataset(tmp_path, name="Older Voice", timestamp="20260601-120000")
    newer_export = exported_dataset(tmp_path, name="Newer Voice", timestamp="20260601-130000")
    invalid_export = tmp_path / "exports" / "broken-export"
    invalid_export.mkdir(parents=True)
    os.utime(older_export, (1_000_000, 1_000_000))
    os.utime(newer_export, (2_000_000, 2_000_000))

    exports = list_voice_modeling_exports(tmp_path / "exports")

    assert [export["name"] for export in exports] == ["Newer Voice", "Older Voice"]
    assert "Newer Voice" in voice_modeling_export_label(exports[0])
    assert "Usable" in voice_modeling_export_label(exports[0])


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
    assert saved["schema_version"] == current_schema_version(VOICE_MODELING_JOB_CONFIG_JSON_KIND)
    assert saved["kind"] == VOICE_MODELING_JOB_CONFIG_JSON_KIND
    assert saved["training_backend"] == "xtts_v2"
    assert saved["device"] == "cuda"
    assert saved["max_epochs"] == 80
    assert saved["batch_size"] == 4
    assert saved["resume_checkpoint"] == str(resume_checkpoint)
    assert saved["dataset"]["metadata_rows"] == 5


def test_list_voice_modeling_job_configs_reads_saved_configs(tmp_path: Path) -> None:
    export_dir = exported_dataset(tmp_path)
    export_info = validate_voice_modeling_export(export_dir)
    output_dir = tmp_path / "voice-models" / "job-a"
    config = build_voice_modeling_job_config(export_info, output_dir=output_dir, job_id="job-a")
    config_path = save_voice_modeling_job_config(config)

    jobs = list_voice_modeling_job_configs(tmp_path / "voice-models")

    assert jobs[0]["config_path"] == str(config_path.resolve())
    assert jobs[0]["dataset_name"] == "Dataset Voice"
    assert "Dataset Voice" in voice_modeling_job_label(jobs[0])


def test_prepare_voice_modeling_training_job_writes_coqui_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    export_dir = exported_dataset(tmp_path)
    export_info = validate_voice_modeling_export(export_dir)
    output_dir = tmp_path / "voice-models" / "job-a"
    config = build_voice_modeling_job_config(export_info, output_dir=output_dir, job_id="job-a")
    config_path = save_voice_modeling_job_config(config)
    monkeypatch.setattr("voicebridge.voice_modeling.ml_python_path", lambda: tmp_path / "python.exe")
    monkeypatch.setattr("voicebridge.voice_modeling.voice_modeling_worker_path", lambda: tmp_path / "worker.py")

    plan = prepare_voice_modeling_training_job(config_path)

    train_lines = Path(plan["train_csv_path"]).read_text(encoding="utf-8").splitlines()
    eval_lines = Path(plan["eval_csv_path"]).read_text(encoding="utf-8").splitlines()
    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    state = json.loads((output_dir / "training_state.json").read_text(encoding="utf-8"))
    assert train_lines[0] == "audio_file|text|speaker_name"
    assert train_lines[1] == "wavs/0001_clip-0.wav|Clip 0|voicebridge"
    assert eval_lines == ["audio_file|text|speaker_name", "wavs/0005_clip-4.wav|Clip 4|voicebridge"]
    assert plan["train_rows"] == 4
    assert plan["eval_rows"] == 1
    assert plan["total_rows"] == 5
    assert saved_config["status"] == "prepared"
    assert saved_config["schema_version"] == current_schema_version(VOICE_MODELING_JOB_CONFIG_JSON_KIND)
    assert state["status"] == "prepared"
    assert state["schema_version"] == current_schema_version(VOICE_MODELING_TRAINING_STATE_JSON_KIND)
    assert state["kind"] == VOICE_MODELING_TRAINING_STATE_JSON_KIND
    assert "worker.py" in plan["command_text"]
    assert "Prepared rows: 4 train, 1 eval, 5 total" in voice_modeling_training_plan_text(plan)


def test_build_voice_modeling_training_command_can_enable_dry_run(tmp_path: Path) -> None:
    config_path = tmp_path / "job_config.json"
    command = build_voice_modeling_training_command(
        config_path,
        dry_run=True,
        python_path=tmp_path / "python.exe",
        worker_path=tmp_path / "voice_modeling_worker.py",
    )

    assert command[:3] == [str(tmp_path / "python.exe"), "-u", str(tmp_path / "voice_modeling_worker.py")]
    assert command[-1] == "--dry-run"


def test_build_voice_modeling_job_config_rejects_missing_resume(tmp_path: Path) -> None:
    export_dir = exported_dataset(tmp_path)
    export_info = validate_voice_modeling_export(export_dir)

    with pytest.raises(ValueError, match="Resume checkpoint"):
        build_voice_modeling_job_config(export_info, resume_checkpoint=tmp_path / "missing.pth")


def test_check_voice_modeling_preflight_requires_dvae(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    export_dir = exported_dataset(tmp_path)
    export_info = validate_voice_modeling_export(export_dir)
    python_path = tmp_path / ".venv-ml" / "Scripts" / "python.exe"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("python", encoding="utf-8")
    model_dir = tmp_path / "models" / "coqui" / "tts" / "tts_models--multilingual--multi-dataset--xtts_v2"
    model_dir.mkdir(parents=True)
    for filename in ("config.json", "model.pth", "speakers_xtts.pth", "vocab.json"):
        (model_dir / filename).write_text("x", encoding="utf-8")

    monkeypatch.setattr("voicebridge.voice_modeling.ml_python_path", lambda: python_path)
    monkeypatch.setattr("voicebridge.voice_modeling.local_tts_model_cache_dir", lambda: model_dir)
    monkeypatch.setattr("voicebridge.voice_modeling.local_tts_dvae_path", lambda: model_dir / "dvae.pth")
    monkeypatch.setattr("voicebridge.voice_modeling.local_tts_model_ready", lambda: True)
    monkeypatch.setattr("voicebridge.voice_modeling.local_tts_dvae_ready", lambda: False)
    monkeypatch.setattr(
        "voicebridge.voice_modeling.inspect_stt_runtime",
        lambda _python_path: {
            "torch_ok": True,
            "torch_version": "2.0",
            "cuda_build": "",
            "cuda_available": False,
            "cuda_device_count": 0,
            "cuda_device_name": "",
            "detail": "Torch 2.0; CPU runtime.",
        },
    )
    monkeypatch.setattr(
        "voicebridge.voice_modeling.inspect_coqui_runtime",
        lambda _python_path: {
            "coqui_ok": True,
            "coqui_version": "0.27",
            "detail": "Coqui TTS import ready.",
        },
    )

    result = check_voice_modeling_preflight(export_info, output_dir=tmp_path / "voice-model")

    assert not result["ok"]
    assert not result["dvae_ready"]
    assert any("DVAE" in detail and detail.startswith("MISSING") for detail in result["details"])


def test_download_file_to_path_verifies_checksum(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    content = b"dvae"
    source.write_bytes(content)
    progress_values = []

    result = download_file_to_path(
        source.as_uri(),
        target,
        expected_sha256=sha256(content).hexdigest(),
        progress_callback=progress_values.append,
    )

    assert result == target
    assert target.read_bytes() == content
    assert progress_values[-1] == 100.0
