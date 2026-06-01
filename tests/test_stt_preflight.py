from pathlib import Path

from voicebridge import stt_preflight


def test_stt_preflight_treats_alignment_models_as_optional(monkeypatch, tmp_path: Path) -> None:
    python_path = tmp_path / ".venv-ml" / "Scripts" / "python.exe"
    worker_path = tmp_path / "stt_worker.py"
    model_dir = tmp_path / "models" / "whisperx"
    site_packages = tmp_path / ".venv-ml" / "Lib" / "site-packages"
    ffmpeg_dir = site_packages / "imageio_ffmpeg" / "binaries"

    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")
    worker_path.write_text("", encoding="utf-8")
    model_dir.mkdir(parents=True)
    for spec in stt_preflight.stt_whisper_model_required_file_specs():
        (model_dir / spec.filename).write_bytes(b"x" * spec.min_bytes)
    (tmp_path / "models" / "torch" / "hub" / "snakers4_silero-vad_master").mkdir(parents=True)
    (tmp_path / "models" / "nltk" / "tokenizers" / "punkt_tab" / "english").mkdir(parents=True)
    (tmp_path / "models" / "nltk" / "tokenizers" / "punkt_tab" / "italian").mkdir(parents=True)
    ffmpeg_dir.mkdir(parents=True)
    (ffmpeg_dir / "ffmpeg.exe").write_text("", encoding="utf-8")

    monkeypatch.setattr(stt_preflight, "stt_python_path", lambda: python_path)
    monkeypatch.setattr(stt_preflight, "stt_worker_path", lambda: worker_path)
    monkeypatch.setattr(stt_preflight, "stt_model_dir", lambda: model_dir)
    monkeypatch.setattr(stt_preflight, "stt_models_root", lambda: tmp_path / "models")
    monkeypatch.setattr(stt_preflight, "stt_runtime_site_packages", lambda: site_packages)
    monkeypatch.setattr(
        stt_preflight,
        "inspect_stt_runtime",
        lambda _python_path: {
            "torch_ok": True,
            "torch_version": "test",
            "cuda_build": "",
            "cuda_available": False,
            "cuda_device_count": 0,
            "cuda_device_name": "",
            "detail": "Torch test runtime.",
        },
    )

    ok, _summary, details, _runtime_info = stt_preflight.check_stt_preflight()

    assert ok
    assert any(line.startswith("OPTIONAL: Alignment model it") for line in details)
