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

    def post(self, callback, *args):
        callback(*args)

    def update_tts_progress_percent(self, percent: float) -> None:
        self.progress_values.append(percent)


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
