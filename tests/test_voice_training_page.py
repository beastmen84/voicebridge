import voicebridge.pages.voice_training as voice_training_page
from voicebridge.pages.voice_training import VoiceTrainingWorkflowMixin


class FakeButton:
    def __init__(self) -> None:
        self.enabled = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakePlainText:
    def __init__(self) -> None:
        self.text = ""

    def appendPlainText(self, message: str) -> None:
        self.text = f"{self.text}\n{message}" if self.text else message

    def clear(self) -> None:
        self.text = ""

    def setPlainText(self, text: str) -> None:
        self.text = text

    def toPlainText(self) -> str:
        return self.text


class FakeVoiceTrainingWorkflow(VoiceTrainingWorkflowMixin):
    def __init__(self) -> None:
        self.voice_training_selected_job_path = "current-job.json"
        self.voice_training_job_status = FakePlainText()
        self.voice_training_open_folder_button = FakeButton()
        self.voice_training_prepare_button = FakeButton()
        self.voice_training_dry_run_button = FakeButton()
        self.voice_training_start_button = FakeButton()
        self.voice_training_cancel_button = FakeButton()
        self.voice_training_refresh_jobs_button = FakeButton()
        self.voice_training_running = False
        self.voice_training_cancel_requested = False
        self.voice_training_running_dry_run = False
        self.logs: list[str] = []
        self.refreshed_paths: list[str] = []
        self.retried_jobs: list[tuple[str, bool]] = []
        self.errors: list[tuple[str, str]] = []
        self.recorded_jobs: list[tuple[str, str, str, str, str]] = []
        self.local_voice_tab_updates = 0
        self.questions: list[tuple[tuple, dict]] = []
        self.question_result = True

    def voice_training_text(self, text: str, **kwargs) -> str:
        return text.format(**kwargs) if kwargs else text

    def ask_question(self, *args, **kwargs) -> bool:
        self.questions.append((args, kwargs))
        return self.question_result

    def append_voice_training_log(self, message: str) -> None:
        self.logs.append(message)
        VoiceTrainingWorkflowMixin.append_voice_training_log(self, message)

    def refresh_voice_training_jobs(self, selected_path: str = "") -> None:
        self.refreshed_paths.append(selected_path)
        self.voice_training_job_status.setPlainText(
            f"Selected job config:\n{selected_path}" if selected_path else "No training job selected."
        )

    def start_voice_training_worker_for_config(self, config_path: str, *, dry_run: bool) -> None:
        self.retried_jobs.append((config_path, dry_run))

    def show_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def record_job(self, kind: str, title: str, input_path: str, output_path: str, detail: str = "") -> None:
        self.recorded_jobs.append((kind, title, input_path, output_path, detail))

    def update_local_voice_tabs(self) -> None:
        self.local_voice_tab_updates += 1

    def refresh_local_voice_profile_combo(self) -> None:
        pass


def test_voice_training_cancel_button_disables_after_cancel_requested() -> None:
    workflow = FakeVoiceTrainingWorkflow()
    workflow.voice_training_running = True
    workflow.voice_training_cancel_requested = True

    workflow.update_voice_training_buttons()

    assert workflow.voice_training_refresh_jobs_button.enabled is False
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

    set_status("completed")
    assert workflow.voice_training_prepare_button.enabled is False
    assert workflow.voice_training_dry_run_button.enabled is False
    assert workflow.voice_training_start_button.enabled is False


def test_voice_training_start_methods_are_guarded_by_job_status(monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()
    monkeypatch.setattr(
        voice_training_page,
        "inspect_voice_modeling_cuda_memory",
        lambda: {
            "available": False,
            "total_bytes": 0,
            "free_bytes": 0,
            "used_bytes": 0,
            "detail": "",
        },
    )

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


def test_voice_training_start_warns_when_cuda_vram_margin_is_low(monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()

    monkeypatch.setattr(
        voice_training_page,
        "load_voice_modeling_job_config",
        lambda _path: {"status": "dry_run_ok", "device": "cuda", "batch_size": 2},
    )
    monkeypatch.setattr(
        voice_training_page,
        "inspect_voice_modeling_cuda_memory",
        lambda: {
            "available": True,
            "total_bytes": 8 * 1024**3,
            "free_bytes": 4 * 1024**3,
            "used_bytes": 4 * 1024**3,
            "detail": "",
        },
    )

    workflow.start_voice_training_run()

    assert workflow.retried_jobs == [("current-job.json", False)]
    assert workflow.questions
    assert "CUDA VRAM margin looks low: 4.0 GB free of 8.0 GB." in workflow.questions[0][0][1]


def test_voice_training_cancelled_marks_job_cancelled(monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()
    workflow.voice_training_running_config_path = "running-job.json"
    updated_statuses = []
    cleanups = []
    monkeypatch.setattr(
        voice_training_page,
        "update_voice_modeling_job_status",
        lambda config_path, status: updated_statuses.append((config_path, status)),
    )
    monkeypatch.setattr(
        voice_training_page,
        "cleanup_incomplete_voice_modeling_job",
        lambda config_path, *, reason: cleanups.append((config_path, reason))
        or {"archive_dir": "logs/job", "deleted_output_dir": "voice_models/job"},
    )

    workflow.voice_training_cancelled()

    assert updated_statuses == [("running-job.json", "cancelled")]
    assert cleanups == [("running-job.json", "cancelled")]
    assert workflow.refreshed_paths == ["running-job.json"]
    assert workflow.local_voice_tab_updates == 1


def test_voice_training_failed_cleans_real_training_job(monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()
    workflow.voice_training_running_config_path = "running-job.json"
    cleanups = []
    monkeypatch.setattr(
        voice_training_page,
        "cleanup_incomplete_voice_modeling_job",
        lambda config_path, *, reason: cleanups.append((config_path, reason))
        or {"archive_dir": "logs/job", "deleted_output_dir": "voice_models/job"},
    )

    workflow.voice_training_failed("Trainer failed.")

    assert cleanups == [("running-job.json", "failed")]
    assert workflow.refreshed_paths == ["running-job.json"]
    assert workflow.errors == [("Voice Training", "Trainer failed.")]


def test_voice_training_dry_run_success_preserves_worker_output_after_refresh() -> None:
    workflow = FakeVoiceTrainingWorkflow()
    workflow.voice_training_running_config_path = "running-job.json"
    workflow.voice_training_job_status.setPlainText("Starting dry run...\nSTATUS: Dry run OK.")

    workflow.voice_training_succeeded(dry_run=True)

    status_text = workflow.voice_training_job_status.toPlainText()
    assert "STATUS: Dry run OK." in status_text
    assert "Dry run completed." in status_text
    assert "Selected job config" not in status_text
    assert workflow.refreshed_paths == ["running-job.json"]


def test_voice_training_success_records_completed_model_in_job_history(tmp_path, monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()
    config_path = tmp_path / "job_config.json"
    output_dir = tmp_path / "voice-model"
    model_path = output_dir / "inference_model" / "model.pth"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"model")
    workflow.voice_training_running_config_path = str(config_path)
    monkeypatch.setattr(voice_training_page, "prune_previous_voice_modeling_outputs", lambda _path: [])
    monkeypatch.setattr(
        voice_training_page,
        "load_voice_modeling_job_config",
        lambda _path: {
            "dataset_dir": "dataset-export",
            "output_dir": str(output_dir),
            "dataset": {"name": "Voice A"},
        },
    )

    workflow.voice_training_succeeded(dry_run=False)

    assert workflow.recorded_jobs == [
        ("TRAIN", "Voice training completed", "dataset-export", str(model_path), "Voice A")
    ]


def test_voice_training_cuda_retry_uses_running_config_path(monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()
    workflow.voice_training_selected_job_path = "current-job.json"
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


def test_voice_training_cuda_oom_error_is_actionable_when_retry_cancelled(monkeypatch) -> None:
    workflow = FakeVoiceTrainingWorkflow()
    workflow.question_result = False
    workflow.voice_training_running_config_path = "running-job.json"
    monkeypatch.setattr(
        voice_training_page,
        "cleanup_incomplete_voice_modeling_job",
        lambda _config_path, *, reason: {"archive_dir": "", "deleted_output_dir": ""},
    )

    workflow.voice_training_failed("torch.AcceleratorError: CUDA error: out of memory")

    assert workflow.errors == [
        (
            "Voice Training",
            "Voice training ran out of CUDA VRAM.\n\n"
            "Close other GPU apps, reduce batch size to 1, or switch this job to CPU and retry.",
        )
    ]
