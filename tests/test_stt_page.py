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


class FakeButton:
    def __init__(self) -> None:
        self.enabled = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


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

    def alignment_model_download_succeeded(self, language_code: str) -> None:
        self.events.append(("alignment_download_succeeded", language_code))

    def update_navigation_state(self) -> None:
        return


class FakeSttRetryWorkflow(FakeSttWorkflow):
    def __init__(self) -> None:
        super().__init__()
        self.device_updates: list[str] = []
        self.saved_settings = 0
        self.errors: list[tuple[str, str]] = []

    def ask_question(self, *_args, **_kwargs) -> bool:
        return True

    def set_stt_device_key(self, device: str) -> None:
        self.device_updates.append(device)

    def save_user_settings(self) -> None:
        self.saved_settings += 1

    def show_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))


def test_stt_cancel_button_disables_after_cancel_requested(monkeypatch) -> None:
    monkeypatch.setattr(stt_page, "stt_whisper_model_ready", lambda: True)

    workflow = FakeSttWorkflow()
    workflow.stt_generate_button = FakeButton()
    workflow.stt_download_model_button = FakeButton()
    workflow.stt_cancel_button = FakeButton()
    workflow.stt_open_output_button = FakeButton()
    workflow.stt_open_folder_button = FakeButton()
    workflow.is_stt_running = True
    workflow.stt_cancel_requested = True
    workflow.stt_preflight_ok = True
    workflow.is_converting = False
    workflow.is_video_running = False
    workflow.is_audio_cleanup_running = False
    workflow.is_cleanup_running = False
    workflow.stt_last_output_path = ""

    workflow.update_stt_button_state()

    assert workflow.stt_cancel_button.enabled is False


def test_stt_cuda_retry_uses_captured_callback(monkeypatch) -> None:
    workflow = FakeSttRetryWorkflow()
    retry_calls = []
    workflow.stt_cpu_retry_callback = lambda: retry_calls.append("captured")

    monkeypatch.setattr(stt_page.QTimer, "singleShot", lambda _delay, callback: callback())

    SttWorkflowMixin.stt_job_failed(workflow, "RuntimeError: CUDA out of memory")

    assert workflow.device_updates == ["cpu"]
    assert workflow.saved_settings == 1
    assert retry_calls == ["captured"]
    assert workflow.errors == []


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


def test_alignment_model_download_thread_uses_process_runner_for_worker_output(monkeypatch, tmp_path: Path) -> None:
    calls = {}
    model_dir = tmp_path / "models"

    def fake_run_worker_process_job(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        kwargs["on_process_start"]("process")
        kwargs["on_output"](
            WorkerProcessOutput(
                line="PROGRESS: 75",
                is_progress=True,
                progress_percent=75.0,
            )
        )
        kwargs["on_output"](
            WorkerProcessOutput(
                line="STATUS: Downloading alignment model",
                is_status=True,
                status="Downloading alignment model",
            )
        )
        kwargs["on_output"](WorkerProcessOutput(line="Alignment worker detail"))
        return WorkerProcessResult(return_code=0, cancelled=False, recent_output=())

    monkeypatch.setattr(stt_page, "external_base_dir", lambda: tmp_path)
    monkeypatch.setattr(stt_page, "stt_model_dir", lambda: model_dir)
    monkeypatch.setattr(stt_page, "run_worker_process_job", fake_run_worker_process_job)

    workflow = FakeSttWorkflow()
    workflow.alignment_model_download_thread(tmp_path / "python.exe", tmp_path / "stt_worker.py", "it")

    assert calls["command"] == [
        str(tmp_path / "python.exe"),
        str(tmp_path / "stt_worker.py"),
        "--mode",
        "download_align",
        "--language",
        "it",
        "--model-dir",
        str(model_dir),
        "--device",
        "cpu",
    ]
    assert calls["kwargs"]["cwd"] == str(tmp_path)
    assert calls["kwargs"]["stdin"] is None
    assert calls["kwargs"]["recent_output_limit"] == 12
    assert calls["kwargs"]["should_cancel"]() is False
    assert workflow.progress_values == [75.0]
    assert workflow.stt_status.messages == ["Downloading alignment model"]
    assert workflow.logs == ["STATUS: Downloading alignment model", "Alignment worker detail"]
    assert workflow.events == [("finished", ""), ("alignment_download_succeeded", "it")]
    assert workflow.stt_process is None
