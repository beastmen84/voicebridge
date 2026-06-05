import logging
from types import SimpleNamespace

import pytest

import voice_modeling_worker


def test_run_trainer_fit_converts_nonzero_system_exit_to_runtime_error() -> None:
    trainer = SimpleNamespace(fit=lambda: (_ for _ in ()).throw(SystemExit(1)))

    with pytest.raises(RuntimeError, match="Trainer exited with code 1"):
        voice_modeling_worker.run_trainer_fit(trainer)


def test_run_trainer_fit_allows_zero_system_exit() -> None:
    trainer = SimpleNamespace(fit=lambda: (_ for _ in ()).throw(SystemExit(0)))

    voice_modeling_worker.run_trainer_fit(trainer)


def test_windows_safe_trainer_cleanup_preserves_failed_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = []

    def original_remove(path):
        calls.append(path)

    trainer_impl_module = SimpleNamespace(remove_experiment_folder=original_remove)
    monkeypatch.setattr(voice_modeling_worker.os, "name", "nt")

    voice_modeling_worker.install_windows_safe_trainer_cleanup(trainer_impl_module)
    trainer_impl_module.remove_experiment_folder("run-path")

    assert calls == []
    assert "Preserving failed training run folder on Windows" in capsys.readouterr().err


def test_trainer_cleanup_is_unchanged_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    def original_remove(path):
        return path

    trainer_impl_module = SimpleNamespace(remove_experiment_folder=original_remove)
    monkeypatch.setattr(voice_modeling_worker.os, "name", "posix")

    voice_modeling_worker.install_windows_safe_trainer_cleanup(trainer_impl_module)

    assert trainer_impl_module.remove_experiment_folder is original_remove


def test_close_trainer_file_handlers_only_closes_handlers_under_output(tmp_path) -> None:
    trainer_logger = logging.getLogger("trainer")
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    trainer_log_path = output_dir / "trainer_0_log.txt"
    outside_log_path = tmp_path / "outside.log"
    trainer_handler = logging.FileHandler(trainer_log_path)
    outside_handler = logging.FileHandler(outside_log_path)
    trainer_logger.addHandler(trainer_handler)
    trainer_logger.addHandler(outside_handler)

    try:
        voice_modeling_worker.close_trainer_file_handlers(output_dir)

        assert trainer_handler not in trainer_logger.handlers
        assert outside_handler in trainer_logger.handlers
        trainer_log_path.unlink()
    finally:
        trainer_logger.removeHandler(outside_handler)
        outside_handler.close()
