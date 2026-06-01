from pathlib import Path

from voicebridge import app_paths, media_tools


def write_sized_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def test_ml_python_path_uses_shared_ml_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_paths, "external_base_dir", lambda: tmp_path)
    bundled_python = tmp_path / "python-ml" / "python.exe"
    bundled_python.parent.mkdir()
    bundled_python.write_text("", encoding="utf-8")

    assert app_paths.ml_python_path() == bundled_python


def test_ml_python_path_falls_back_to_venv_ml(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_paths, "external_base_dir", lambda: tmp_path)

    assert app_paths.ml_python_path() == tmp_path / ".venv-ml" / "Scripts" / "python.exe"


def test_stt_runtime_site_packages_uses_shared_ml_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_paths, "external_base_dir", lambda: tmp_path)

    assert app_paths.stt_runtime_site_packages() == tmp_path / ".venv-ml" / "Lib" / "site-packages"


def test_stt_whisper_model_ready_checks_required_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_paths, "external_base_dir", lambda: tmp_path)
    model_dir = app_paths.stt_model_dir()
    model_dir.mkdir(parents=True)

    assert not app_paths.stt_whisper_model_ready()

    for spec in app_paths.stt_whisper_model_required_file_specs():
        write_sized_file(model_dir / spec.filename, spec.min_bytes)

    assert app_paths.stt_whisper_model_ready()


def test_stt_alignment_model_ready_checks_language_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_paths, "external_base_dir", lambda: tmp_path)
    model_dir = app_paths.stt_model_dir()
    model_dir.mkdir(parents=True)

    assert not app_paths.stt_alignment_model_ready("it")

    (model_dir / app_paths.stt_alignment_model_files()["it"]).write_text("x", encoding="utf-8")

    assert app_paths.stt_alignment_model_ready("it")


def test_local_tts_dvae_ready_checks_xtts_cache_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_paths, "external_base_dir", lambda: tmp_path)

    assert app_paths.local_tts_dvae_path() == app_paths.local_tts_model_cache_dir() / "dvae.pth"
    assert app_paths.local_tts_mel_stats_path() == app_paths.local_tts_model_cache_dir() / "mel_stats.pth"
    assert app_paths.voice_modeling_worker_path() == tmp_path / "voice_modeling_worker.py"
    assert not app_paths.local_tts_dvae_ready()
    assert not app_paths.local_tts_mel_stats_ready()

    app_paths.local_tts_dvae_path().parent.mkdir(parents=True)
    write_sized_file(app_paths.local_tts_dvae_path(), 1024 * 1024)
    write_sized_file(app_paths.local_tts_mel_stats_path(), 32)

    assert app_paths.local_tts_dvae_ready()
    assert app_paths.local_tts_mel_stats_ready()


def test_ffmpeg_candidates_only_include_shared_ml_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(media_tools, "external_base_dir", lambda: tmp_path)
    bundled_dir = tmp_path / "python-ml" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"
    venv_dir = tmp_path / ".venv-ml" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries"
    bundled_dir.mkdir(parents=True)
    venv_dir.mkdir(parents=True)
    (bundled_dir / "ffmpeg.exe").write_text("", encoding="utf-8")
    (venv_dir / "ffmpeg.exe").write_text("", encoding="utf-8")

    candidates = media_tools.ffmpeg_candidates()
    candidate_text = "\n".join(str(candidate) for candidate in candidates)

    assert "python-ml" in candidate_text
    assert ".venv-ml" in candidate_text
    assert "python-stt" not in candidate_text
    assert ".venv-stt" not in candidate_text
