from pathlib import Path

import voicebridge.pages.stt as stt_page
from voicebridge.constants import STT_MODEL
from voicebridge.pages.stt import SttWorkflowMixin
from voicebridge.process_jobs import WorkerProcessOutput, WorkerProcessResult


class FakeSttStatus:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def setText(self, message: str) -> None:
        self.messages.append(message)


class FakeSttWorkflow(SttWorkflowMixin):
    def __init__(self) -> None:
        self.stt_cancel_requested = False
        self.stt_process = None
        self.stt_status = FakeSttStatus()
        self.progress_values: list[float] = []
        self.logs: list[str] = []
        self.events: list[tuple[str, str]] = []

    def post(self, callback, *args):
        callback(*args)

    def update_stt_progress_percent(self, percent: float) -> None:
        self.progress_values.append(percent)

    def append_stt_log(self, message: str) -> None:
        self.logs.append(message)

    def finish_stt_job(self) -> None:
        self.events.append(("finished", ""))

    def stt_job_cancelled(self) -> None:
        self.events.append(("cancelled", ""))

    def stt_job_failed(self, message: str) -> None:
        self.events.append(("failed", message))

    def stt_model_download_succeeded(self) -> None:
        self.events.append(("download_succeeded", ""))


def test_stt_model_download_thread_uses_process_runner_for_worker_output(monkeypatch, tmp_path: Path) -> None:
    calls = {}
    model_dir = tmp_path / "models"

    def fake_run_worker_process_job(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        kwargs["on_process_start"]("process")
        kwargs["on_output"](
            WorkerProcessOutput(
                line="PROGRESS: 50",
                is_progress=True,
                progress_percent=50.0,
            )
        )
        kwargs["on_output"](
            WorkerProcessOutput(
                line="STATUS: Downloading Faster Whisper",
                is_status=True,
                status="Downloading Faster Whisper",
            )
        )
        kwargs["on_output"](WorkerProcessOutput(line="Worker detail"))
        return WorkerProcessResult(return_code=0, cancelled=False, recent_output=())

    monkeypatch.setattr(stt_page, "external_base_dir", lambda: tmp_path)
    monkeypatch.setattr(stt_page, "stt_model_dir", lambda: model_dir)
    monkeypatch.setattr(stt_page, "run_worker_process_job", fake_run_worker_process_job)

    workflow = FakeSttWorkflow()
    workflow.stt_model_download_thread(tmp_path / "python.exe", tmp_path / "stt_worker.py")

    assert calls["command"] == [
        str(tmp_path / "python.exe"),
        str(tmp_path / "stt_worker.py"),
        "--mode",
        "download_whisper",
        "--model",
        STT_MODEL,
        "--model-dir",
        str(model_dir),
    ]
    assert calls["kwargs"]["cwd"] == str(tmp_path)
    assert calls["kwargs"]["stdin"] is None
    assert calls["kwargs"]["recent_output_limit"] == 12
    assert calls["kwargs"]["should_cancel"]() is False
    assert workflow.progress_values == [50.0]
    assert workflow.stt_status.messages == ["Downloading Faster Whisper"]
    assert workflow.logs == ["STATUS: Downloading Faster Whisper", "Worker detail"]
    assert workflow.events == [("finished", ""), ("download_succeeded", "")]
    assert workflow.stt_process is None
