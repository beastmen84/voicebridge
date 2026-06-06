import voicebridge.pages.voice_modeling as voice_modeling_page
from voicebridge.pages.voice_modeling import VoiceModelingWorkflowMixin


class FakeStyle:
    def unpolish(self, _widget) -> None:
        return

    def polish(self, _widget) -> None:
        return


class FakeBox:
    def __init__(self) -> None:
        self.object_name = ""
        self._style = FakeStyle()

    def setObjectName(self, name: str) -> None:
        self.object_name = name

    def style(self) -> FakeStyle:
        return self._style


class FakeButton:
    def __init__(self) -> None:
        self.enabled = None
        self.visible = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled

    def setVisible(self, visible: bool) -> None:
        self.visible = visible


class FakeLabel:
    def __init__(self) -> None:
        self.text_value = ""

    def setText(self, text: str) -> None:
        self.text_value = text


class FakeTextBox:
    def __init__(self) -> None:
        self.value = ""

    def setPlainText(self, text: str) -> None:
        self.value = text


class FakeProgress:
    def __init__(self) -> None:
        self.visible = None

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False


class FakePicker:
    def __init__(self, value: str) -> None:
        self.value = value

    def text(self) -> str:
        return self.value


class FakeVoiceModelingWorkflow(VoiceModelingWorkflowMixin):
    def __init__(self) -> None:
        self.voice_modeling_export_info = {"export_dir": "export-a", "name": "Voice A"}
        self.voice_modeling_output_picker = FakePicker("output-a")
        self.voice_modeling_resume_picker = FakePicker("")
        self.voice_modeling_preflight_label = FakeLabel()
        self.voice_modeling_preflight_box = FakeBox()
        self.voice_modeling_preflight_details_box = FakeTextBox()
        self.voice_modeling_preflight_refresh_button = FakeButton()
        self.voice_modeling_save_config_button = FakeButton()
        self.voice_modeling_open_output_button = FakeButton()
        self.voice_modeling_dvae_progress = FakeProgress()
        self.voice_modeling_preflight_ok = False
        self._voice_modeling_preflight_refreshing = True
        self._voice_modeling_preflight_stale = False
        self.home_refreshes = 0
        self.dvae_refreshes = 0

    def voice_modeling_text(self, text: str, **kwargs) -> str:
        return text.format(**kwargs) if kwargs else text

    def voice_modeling_device_key(self) -> str:
        return "cuda"

    def refresh_home_diagnostics(self) -> None:
        self.home_refreshes += 1

    def update_voice_modeling_dvae_status(self) -> None:
        self.dvae_refreshes += 1


def test_voice_modeling_preflight_discards_stale_result() -> None:
    workflow = FakeVoiceModelingWorkflow()
    snapshot = workflow.current_voice_modeling_preflight_snapshot()
    workflow.voice_modeling_output_picker.value = "changed-output"

    workflow.voice_modeling_preflight_finished(
        snapshot,
        {"ok": True, "summary": "Ready", "details": ["ready"]},
    )

    assert workflow.voice_modeling_preflight_ok is False
    assert workflow.voice_modeling_preflight_label.text_value == (
        "Preflight needs refresh after configuration changes."
    )
    assert workflow.voice_modeling_preflight_refresh_button.enabled is True
    assert workflow.voice_modeling_preflight_box.object_name == "WarningBox"
    assert workflow.home_refreshes == 1
    assert workflow.dvae_refreshes == 1


def test_voice_modeling_stale_preflight_enables_refresh_button() -> None:
    workflow = FakeVoiceModelingWorkflow()
    workflow._voice_modeling_preflight_refreshing = False
    workflow.voice_modeling_preflight_ok = True

    workflow.mark_voice_modeling_preflight_stale()

    assert workflow.voice_modeling_preflight_ok is False
    assert workflow.voice_modeling_preflight_refresh_button.enabled is True
    assert workflow.voice_modeling_save_config_button.enabled is True
    assert workflow.voice_modeling_open_output_button.enabled is True


def test_voice_modeling_dvae_cancel_button_reflects_cancel_requested(monkeypatch) -> None:
    monkeypatch.setattr(voice_modeling_page, "local_tts_dvae_ready", lambda: False)
    monkeypatch.setattr(voice_modeling_page, "local_tts_mel_stats_ready", lambda: False)

    workflow = FakeVoiceModelingWorkflow()
    workflow.voice_modeling_download_dvae_button = FakeButton()
    workflow.voice_modeling_cancel_dvae_button = FakeButton()
    workflow.voice_modeling_dvae_download_running = True
    workflow.voice_modeling_dvae_cancel_requested = True

    VoiceModelingWorkflowMixin.update_voice_modeling_dvae_status(workflow)

    assert workflow.voice_modeling_download_dvae_button.enabled is False
    assert workflow.voice_modeling_download_dvae_button.visible is True
    assert workflow.voice_modeling_cancel_dvae_button.enabled is False
    assert workflow.voice_modeling_cancel_dvae_button.visible is True


def test_cancel_xtts_dvae_download_marks_download_as_cancelling() -> None:
    workflow = FakeVoiceModelingWorkflow()
    workflow.voice_modeling_download_dvae_button = FakeButton()
    workflow.voice_modeling_cancel_dvae_button = FakeButton()
    workflow.voice_modeling_dvae_download_running = True
    workflow.voice_modeling_dvae_cancel_requested = False
    workflow.voice_modeling_status = FakeLabel()

    workflow.cancel_xtts_dvae_download()

    assert workflow.voice_modeling_dvae_cancel_requested is True
    assert workflow.voice_modeling_status.text_value == "Cancelling training assets download..."
    assert workflow.voice_modeling_preflight_label.text_value == "Cancelling training assets download..."
