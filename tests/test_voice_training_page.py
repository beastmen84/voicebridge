import voicebridge.pages.voice_training as voice_training_page
from voicebridge.pages.voice_training import VoiceTrainingWorkflowMixin


class FakeButton:
    def __init__(self) -> None:
        self.enabled = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakeCombo:
    def __init__(self, selected_path: str = "current-job.json") -> None:
        self.enabled = None
        self.selected_path = selected_path

    def currentData(self, _role):
        return self.selected_path

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakeVoiceTrainingWorkflow(VoiceTrainingWorkflowMixin):
    def __init__(self) -> None:
        self.voice_training_job_combo = FakeCombo()
        self.voice_training_open_folder_button = FakeButton()
        self.voice_training_prepare_button = FakeButton()
        self.voice_training_dry_run_button = FakeButton()
        self.voice_training_start_button = FakeButton()
        self.voice_training_cancel_button = FakeButton()
        self.voice_training_refresh_jobs_button = FakeButton()
        self.voice_training_running = False
        self.voice_training_cancel_requested = False
        self.logs: list[str] = []
        self.refreshed_paths: list[str] = []
        self.retried_jobs: list[tuple[str, bool]] = []
        self.errors: list[tuple[str, str]] = []
        self.local_voice_tab_updates = 0

    def voice_training_text(self, text: str, **kwargs) -> str:
        return text.format(**kwargs) if kwargs else text

    def ask_question(self, *_args, **_kwargs) -> bool:
        return True

    def append_voice_training_log(self, message: str) -> None:
        self.logs.append(message)

    def refresh_voice_training_jobs(self, selected_path: str = "") -> None:
        self.refreshed_paths.append(selected_path)

    def start_voice_training_worker_for_config(self, config_path: str, *, dry_run: bool) -> None:
        self.retried_jobs.append((config_path, dry_run))

    def show_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def update_local_voice_tabs(self) -> None:
        self.local_voice_tab_updates += 1


def test_voice_training_cancel_button_disables_after_cancel_requested() -> None:
    workflow = FakeVoiceTrainingWorkflow()
    workflow.voice_training_running = True
    workflow.voice_training_cancel_requested = True

    workflow.update_voice_training_buttons()

    assert workflow.voice_training_job_combo.enabled is False
    assert workflow.voice_training_cancel_button.enabled is False


def test_voice_training_cuda_retry_uses_running_config_path(monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()
    workflow.voice_training_job_combo.selected_path = "current-job.json"
    workflow.voice_training_running_config_path = "captured-job.json"
    loaded_paths = []
    saved_configs = []

    def fake_load_config(config_path: str) -> dict:
        loaded_paths.append(config_path)
        return {"device": "cuda"}

    monkeypatch.setattr(voice_training_page, "load_voice_modeling_job_config", fake_load_config)
    monkeypatch.setattr(voice_training_page, "save_voice_modeling_job_config", saved_configs.append)
    monkeypatch.setattr(voice_training_page.QTimer, "singleShot", lambda _delay, callback: callback())

    workflow.voice_training_failed("RuntimeError: CUDA out of memory")

    assert loaded_paths == ["captured-job.json"]
    assert saved_configs == [{"device": "cpu"}]
    assert workflow.refreshed_paths == ["captured-job.json"]
    assert workflow.retried_jobs == [("captured-job.json", False)]
    assert workflow.errors == []
