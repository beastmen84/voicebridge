import pytest

from stt_worker import allocate_text_to_segments, format_srt_timestamp, normalize_stt_language


def test_format_srt_timestamp_rounds_to_milliseconds() -> None:
    assert format_srt_timestamp(3723.4564) == "01:02:03,456"
    assert format_srt_timestamp(-1) == "00:00:00,000"


def test_normalize_stt_language() -> None:
    assert normalize_stt_language(None) == "auto"
    assert normalize_stt_language("auto") == "auto"
    assert normalize_stt_language("en_US") == "en"
    assert normalize_stt_language("IT-it") == "it"


def test_allocate_text_to_segments_uses_matching_boundaries() -> None:
    source_segments = [
        {"start": 0.0, "end": 1.0, "text": "hello world"},
        {"start": 1.0, "end": 2.0, "text": "from voicebridge"},
    ]

    allocated = allocate_text_to_segments("hello brave world from voicebridge", source_segments)

    assert allocated == [
        {"start": 0.0, "end": 1.0, "text": "hello brave world"},
        {"start": 1.0, "end": 2.0, "text": "from voicebridge"},
    ]


def test_allocate_text_to_segments_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="empty"):
        allocate_text_to_segments("   ", [{"start": 0.0, "end": 1.0, "text": "hello"}])
