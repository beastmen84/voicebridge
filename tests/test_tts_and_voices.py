from voicebridge.pages.tts import TtsWorkflowMixin
from voicebridge.tts_engine import ensure_mp3_suffix, suggested_output_path
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
    assert expanded[0]["text"].startswith("1, Introduzione.")


def test_local_tts_segment_fields_keep_profile_language() -> None:
    profile = {
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
    summary = TtsWorkflowMixin.tts_segment_summary(0, {"text": "Ciao", **fields})

    assert fields["voice_profile_id"] == "profile-1"
    assert fields["language_code"] == "it"
    assert "Marco (Italian)" in summary
    assert "+0%" not in summary
