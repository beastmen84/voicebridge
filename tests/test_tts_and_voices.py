import voicebridge.pages.tts as tts_page
from voicebridge.pages.tts import TtsWorkflowMixin
from voicebridge.process_jobs import WorkerProcessOutput, WorkerProcessResult
from voicebridge.tts_engine import ensure_mp3_suffix, suggested_output_path
from voicebridge.voice_profiles import VoiceProfile
from voicebridge.voices import (
    VOICE_SECTION_OTHER,
    VOICE_SECTION_PREFERRED,
    build_voice_options,
    filter_voices_by_language,
    voice_display_label,
    voice_short_display_name,
)


def test_tts_output_path_helpers() -> None:
    assert suggested_output_path(r"C:\work\document.docx") == r"C:\work\document.mp3"
    assert ensure_mp3_suffix(r"C:\work\audio") == r"C:\work\audio.mp3"
    assert ensure_mp3_suffix(r"C:\work\audio.MP3") == r"C:\work\audio.MP3"


def test_voice_display_label_includes_locale_name_gender_and_tags() -> None:
    voice = {
        "ShortName": "it-IT-IsabellaNeural",
        "Locale": "it-IT",
        "Gender": "Female",
        "VoiceTag": {"ContentCategories": ["News"], "VoicePersonalities": ["Warm"]},
    }

    assert voice_short_display_name("it-IT-IsabellaNeural") == "Isabella"
    assert voice_display_label(voice) == "it-IT | Isabella (Female) - News; Warm"


def test_build_voice_options_groups_preferred_voices() -> None:
    voices = [
        {"ShortName": "en-US-AriaNeural", "Locale": "en-US", "Gender": "Female"},
        {"ShortName": "it-IT-DiegoNeural", "Locale": "it-IT", "Gender": "Male"},
    ]

    values, voice_map = build_voice_options(voices, preferred_short_names={"it-IT-DiegoNeural"})

    assert VOICE_SECTION_PREFERRED in values
    assert VOICE_SECTION_OTHER in values
    assert voice_map["  it-IT | Diego (Male)"] == "it-IT-DiegoNeural"


def test_filter_voices_by_language_matches_locale_base_code() -> None:
    voices = [
        {"ShortName": "en-US-AriaNeural", "Locale": "en-US"},
        {"ShortName": "it-IT-DiegoNeural", "Locale": "it-IT"},
    ]

    assert filter_voices_by_language(voices, "it") == [voices[1]]


def test_expand_multi_voice_segments_keeps_voice_and_rate_on_internal_chunks() -> None:
    segments = [
        {
            "text": (
                "1. Introduzione. "
                "Questa frase è volutamente molto lunga, con diverse pause morbide, con altro contenuto descrittivo, "
                "con ulteriori parole per superare il limite del chunk, e con una chiusura che obbliga il backend "
                "a dividere internamente il blocco senza cambiare voce o velocità."
            ),
            "voice_short_name": "it-IT-IsabellaNeural",
            "rate": "+0%",
        }
    ]

    expanded = TtsWorkflowMixin.expand_multi_voice_segments(segments)

    assert len(expanded) > 1
    assert all(segment["voice_short_name"] == "it-IT-IsabellaNeural" for segment in expanded)
    assert all(segment["rate"] == "+0%" for segment in expanded)
    assert all(segment["source_block_index"] == 1 for segment in expanded)
    assert [segment["chunk_index"] for segment in expanded] == list(range(1, len(expanded) + 1))
    assert expanded[0]["text"].startswith("1, Introduzione.")


def test_local_tts_segment_fields_keep_profile_language() -> None:
    profile: VoiceProfile = {
        "id": "profile-1",
        "name": "Marco",
        "language_code": "it",
        "profile_type": "reference",
        "reference_paths": [r"C:\voices\marco.wav"],
        "consent_confirmed": True,
        "notes": "",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }

    fields = TtsWorkflowMixin.local_tts_segment_voice_fields(profile)
    summary = TtsWorkflowMixin.tts_segment_summary(0, {"text": "Ciao", "voice_label": "Marco", **fields})

    assert fields["voice_profile_id"] == "profile-1"
    assert fields["language_code"] == "it"
    assert "Marco (Italian)" in summary
    assert "+0%" not in summary


class FakeTtsStatus:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def setText(self, message: str) -> None:
        self.messages.append(message)


class FakeTtsWorkflow(TtsWorkflowMixin):
    def __init__(self) -> None:
        self.tts_cancel_requested = False
        self.tts_process = None
        self.tts_status = FakeTtsStatus()
        self.progress_values: list[float] = []
        self.events: list[tuple[str, str]] = []

    def post(self, callback, *args):
        callback(*args)

    def update_tts_progress_percent(self, percent: float) -> None:
        self.progress_values.append(percent)

    def conversion_cancelled(self) -> None:
        self.events.append(("cancelled", ""))

    def conversion_failed(self, message: str) -> None:
        self.events.append(("failed", message))

    def finish_tts_conversion(self) -> None:
        self.events.append(("finished", ""))

    def local_tts_model_download_succeeded(self) -> None:
        self.events.append(("download_succeeded", ""))


class FakeVoiceLoadWorkflow(TtsWorkflowMixin):
    def __init__(self) -> None:
        self.loaded_voices = None
        self.loaded_error = None

    def post(self, callback, *args):
        callback(*args)

    def voices_loaded(self, voices, error_message):
        self.loaded_voices = voices
        self.loaded_error = error_message


class FakeButton:
    def __init__(self) -> None:
        self.enabled = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakeButtonStateWorkflow(TtsWorkflowMixin):
    def __init__(self) -> None:
        self.engine = "edge"
        self.is_detecting_language = False
        self.is_converting = False
        self.is_stt_running = False
        self.is_video_running = False
        self.is_audio_cleanup_running = False
        self.is_cleanup_running = False
        self.input_file_error_message = ""
        self.is_loading_voices = False
        self.voice_load_error_message = ""
        self.current_voice_map = {"it-IT | Elsa (Female)": "it-IT-ElsaNeural"}
        self.tts_cancel_requested = False
        self.tts_last_output_path = ""
        self.tts_generate_button = FakeButton()
        self.tts_cancel_button = FakeButton()
        self.tts_open_output_button = FakeButton()
        self.tts_open_folder_button = FakeButton()

    def tts_engine_key(self):
        return self.engine

    def update_navigation_state(self) -> None:
        return


class FakeEngineSwitchWorkflow(TtsWorkflowMixin):
    def __init__(self) -> None:
        self.engine = "edge"
        self.edge_tts_auto_switched_to_local = False
        self.saved = False

    def tts_engine_key(self):
        return self.engine

    def set_tts_engine_key_without_saving(self, engine: str) -> None:
        self.engine = engine

    def save_user_settings(self) -> None:
        self.saved = True


class FakeEdgeUnavailableWorkflow(FakeButtonStateWorkflow):
    def __init__(self) -> None:
        super().__init__()
        self.all_voices = [{"ShortName": "it-IT-ElsaNeural", "Locale": "it-IT"}]
        self.voice_status = FakeTtsStatus()
        self.edge_tts_auto_switched_to_local = False
        self.retry_timer_updates = 0
        self.home_refreshes = 0

    def populate_voice_combo(self, voices, preferred_short_name=None):
        self.current_voice_candidates = list(voices)
        self.current_voice_map = {}

    def set_tts_engine_key_without_saving(self, engine: str) -> None:
        self.engine = engine

    def update_edge_tts_retry_timer(self) -> None:
        self.retry_timer_updates += 1

    def refresh_home_diagnostics(self) -> None:
        self.home_refreshes += 1

    def tts_text(self, text: str, **kwargs) -> str:
        return text.format(**kwargs) if kwargs else text

    def selected_tts_voice_profile(self):
        return None


def test_edge_voice_load_failure_returns_no_fallback_voices(monkeypatch) -> None:
    async def fail_voice_load():
        raise OSError("offline")

    monkeypatch.setattr(tts_page.edge_tts, "list_voices", fail_voice_load)

    workflow = FakeVoiceLoadWorkflow()
    workflow.load_voices_worker()

    assert workflow.loaded_voices == []
    assert workflow.loaded_error == "offline"


def test_edge_tts_generate_button_is_disabled_when_voice_list_failed() -> None:
    workflow = FakeButtonStateWorkflow()
    workflow.voice_load_error_message = "offline"

    workflow.update_tts_button_state()

    assert workflow.tts_generate_button.enabled is False


def test_edge_tts_generate_button_can_enable_when_real_voice_list_loaded() -> None:
    workflow = FakeButtonStateWorkflow()

    workflow.update_tts_button_state()

    assert workflow.tts_generate_button.enabled is True


def test_edge_voice_load_failure_switches_to_local_without_saving_settings() -> None:
    workflow = FakeEngineSwitchWorkflow()

    workflow.switch_to_local_tts_after_edge_failure()

    assert workflow.engine == "local"
    assert workflow.edge_tts_auto_switched_to_local is True
    assert workflow.saved is False


def test_edge_tts_runtime_failure_marks_edge_unavailable_and_switches_to_local() -> None:
    workflow = FakeEdgeUnavailableWorkflow()

    workflow.handle_edge_tts_unavailable("connection lost")

    assert workflow.voice_load_error_message == "connection lost"
    assert workflow.all_voices == []
    assert workflow.current_voice_map == {}
    assert workflow.engine == "local"
    assert workflow.edge_tts_auto_switched_to_local is True
    assert workflow.tts_generate_button.enabled is False
    assert workflow.retry_timer_updates == 1
    assert workflow.home_refreshes == 1
    assert "requires internet" in workflow.voice_status.messages[-1]


def test_run_local_tts_worker_command_uses_process_runner_for_worker_output(monkeypatch, tmp_path) -> None:
    calls = {}

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
                line="STATUS: Synthesizing",
                is_status=True,
                status="Synthesizing",
            )
        )
        return WorkerProcessResult(return_code=0, cancelled=False, recent_output=())

    monkeypatch.setattr(tts_page, "external_base_dir", lambda: tmp_path)
    monkeypatch.setattr(tts_page, "run_worker_process_job", fake_run_worker_process_job)

    workflow = FakeTtsWorkflow()
    workflow.run_local_tts_worker_command(["python", "local_tts_worker.py"], progress_start=20, progress_end=60)

    assert calls["command"] == ["python", "local_tts_worker.py"]
    assert calls["kwargs"]["cwd"] == str(tmp_path)
    assert calls["kwargs"]["recent_output_limit"] == 12
    assert calls["kwargs"]["should_cancel"]() is False
    assert workflow.progress_values == [40.0]
    assert workflow.tts_status.messages == ["Synthesizing"]
    assert workflow.tts_process is None


def test_local_tts_model_download_worker_uses_process_runner_for_worker_output(monkeypatch, tmp_path) -> None:
    calls = {}
    model_dir = tmp_path / "models"

    def fake_run_worker_process_job(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        kwargs["on_process_start"]("process")
        kwargs["on_output"](
            WorkerProcessOutput(
                line="PROGRESS: 25",
                is_progress=True,
                progress_percent=25.0,
            )
        )
        kwargs["on_output"](
            WorkerProcessOutput(
                line="STATUS: Downloading XTTS-v2",
                is_status=True,
                status="Downloading XTTS-v2",
            )
        )
        return WorkerProcessResult(return_code=0, cancelled=False, recent_output=())

    monkeypatch.setattr(tts_page, "external_base_dir", lambda: tmp_path)
    monkeypatch.setattr(tts_page, "local_tts_model_dir", lambda: model_dir)
    monkeypatch.setattr(tts_page, "run_worker_process_job", fake_run_worker_process_job)

    workflow = FakeTtsWorkflow()
    workflow.local_tts_model_download_worker(tmp_path / "python.exe", tmp_path / "local_tts_worker.py")

    assert calls["command"] == [
        str(tmp_path / "python.exe"),
        "-u",
        str(tmp_path / "local_tts_worker.py"),
        "--download-model",
        "--accept-license",
        "--model-dir",
        str(model_dir),
    ]
    assert calls["kwargs"]["cwd"] == str(tmp_path)
    assert calls["kwargs"]["recent_output_limit"] == 12
    assert calls["kwargs"]["should_cancel"]() is False
    assert workflow.progress_values == [25.0]
    assert workflow.tts_status.messages == ["Downloading XTTS-v2"]
    assert workflow.events == [("download_succeeded", ""), ("finished", "")]
    assert workflow.tts_process is None
