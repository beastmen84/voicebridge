import json
from pathlib import Path

from tests.test_voice_modeling import exported_dataset
from voicebridge.local_voice_sources import (
    LOCAL_VOICE_REFERENCE,
    LOCAL_VOICE_TRAINED,
    grouped_local_voice_sources,
    list_trained_local_voices,
    local_voice_display_label,
    local_voice_from_training_result,
    local_voice_model_args,
    local_voice_requires_base_xtts,
    local_voice_status_text,
)
from voicebridge.voice_modeling import (
    build_voice_modeling_job_config,
    save_voice_modeling_job_config,
    validate_voice_modeling_export,
)


def write_training_result(tmp_path: Path) -> Path:
    export_dir = exported_dataset(tmp_path)
    export_info = validate_voice_modeling_export(export_dir)
    output_dir = tmp_path / "voice-models" / "job-a"
    config = build_voice_modeling_job_config(export_info, output_dir=output_dir, job_id="job-a")
    config_path = save_voice_modeling_job_config(config)
    inference_dir = output_dir / "inference_model"
    inference_dir.mkdir(parents=True)
    model_path = inference_dir / "model.pth"
    config_path_for_inference = inference_dir / "config.json"
    vocab_path = inference_dir / "vocab.json"
    speaker_wav = output_dir / "speaker.wav"
    for path in (model_path, config_path_for_inference, vocab_path, speaker_wav):
        path.write_text("x", encoding="utf-8")
    result_path = output_dir / "training_result.json"
    result_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "config_path": str(config_path),
                "model_path": str(model_path),
                "config_path_for_inference": str(config_path_for_inference),
                "vocab_path": str(vocab_path),
                "speaker_wav": str(speaker_wav),
            }
        ),
        encoding="utf-8",
    )
    return result_path


def test_training_result_becomes_trained_local_voice(tmp_path: Path) -> None:
    result_path = write_training_result(tmp_path)

    voice = local_voice_from_training_result(result_path)

    assert voice["kind"] == LOCAL_VOICE_TRAINED
    assert voice["name"] == "Dataset Voice"
    assert voice["language_code"] == "en"
    assert voice["reference_paths"] == [str((result_path.parent / "speaker.wav").resolve())]
    assert voice["id"].startswith("trained:")
    assert not local_voice_requires_base_xtts(voice)
    assert local_voice_model_args(voice) == ["--model-path", voice["model_path"], "--config-path", voice["config_path"]]
    assert "trained" in local_voice_display_label(voice)
    assert "Trained model" in local_voice_status_text(voice)


def test_list_trained_local_voices_skips_incomplete_results(tmp_path: Path) -> None:
    result_path = write_training_result(tmp_path)
    broken_dir = tmp_path / "voice-models" / "broken"
    broken_dir.mkdir(parents=True)
    (broken_dir / "training_result.json").write_text("{}", encoding="utf-8")

    voices = list_trained_local_voices(tmp_path / "voice-models")

    assert [voice["source_path"] for voice in voices] == [str(result_path.resolve())]


def test_grouped_local_voice_sources_keeps_reference_before_trained(tmp_path: Path) -> None:
    trained_voice = local_voice_from_training_result(write_training_result(tmp_path))
    reference_voice = {
        "id": "profile-1",
        "kind": LOCAL_VOICE_REFERENCE,
        "name": "Reference Voice",
        "language_code": "it",
        "reference_paths": [str(tmp_path / "reference.wav")],
        "model_path": "",
        "config_path": "",
        "source_path": "",
        "status": "Ready",
    }

    groups = grouped_local_voice_sources([trained_voice, reference_voice])

    assert [(label, [voice["id"] for voice in voices]) for label, voices in groups] == [
        ("Reference profiles", ["profile-1"]),
        ("Trained models", [trained_voice["id"]]),
    ]
