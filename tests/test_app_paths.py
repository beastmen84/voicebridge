from pathlib import Path

from voicebridge import app_paths, media_tools


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
