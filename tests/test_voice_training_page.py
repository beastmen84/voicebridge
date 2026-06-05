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


def test_voice_training_buttons_follow_job_status(monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()

    def set_status(status: str) -> None:
        monkeypatch.setattr(voice_training_page, "load_voice_modeling_job_config", lambda _path: {"status": status})
        workflow.update_voice_training_buttons()

    set_status("configured")
    assert workflow.voice_training_prepare_button.enabled is True
    assert workflow.voice_training_dry_run_button.enabled is False
    assert workflow.voice_training_start_button.enabled is False

    set_status("prepared")
    assert workflow.voice_training_prepare_button.enabled is False
    assert workflow.voice_training_dry_run_button.enabled is True
    assert workflow.voice_training_start_button.enabled is False

    set_status("dry_run_ok")
    assert workflow.voice_training_prepare_button.enabled is False
    assert workflow.voice_training_dry_run_button.enabled is False
    assert workflow.voice_training_start_button.enabled is True

    set_status("failed")
    assert workflow.voice_training_prepare_button.enabled is True
    assert workflow.voice_training_dry_run_button.enabled is False
    assert workflow.voice_training_start_button.enabled is False


def test_voice_training_start_methods_are_guarded_by_job_status(monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()

    monkeypatch.setattr(voice_training_page, "load_voice_modeling_job_config", lambda _path: {"status": "configured"})
    workflow.start_voice_training_dry_run()
    workflow.start_voice_training_run()
    assert workflow.retried_jobs == []

    monkeypatch.setattr(voice_training_page, "load_voice_modeling_job_config", lambda _path: {"status": "prepared"})
    workflow.start_voice_training_dry_run()
    assert workflow.retried_jobs == [("current-job.json", True)]

    monkeypatch.setattr(voice_training_page, "load_voice_modeling_job_config", lambda _path: {"status": "dry_run_ok"})
    workflow.start_voice_training_run()
    assert workflow.retried_jobs == [("current-job.json", True), ("current-job.json", False)]


def test_voice_training_cancelled_marks_job_cancelled(monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()
    workflow.voice_training_running_config_path = "running-job.json"
    updated_statuses = []
    monkeypatch.setattr(
        voice_training_page,
        "update_voice_modeling_job_status",
        lambda config_path, status: updated_statuses.append((config_path, status)),
    )

    workflow.voice_training_cancelled()

    assert updated_statuses == [("running-job.json", "cancelled")]
    assert workflow.refreshed_paths == ["running-job.json"]
    assert workflow.local_voice_tab_updates == 1


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
