import warnings

import pytest

from stt_worker import (
    allocate_text_to_segments,
    expected_output_suffixes,
    format_srt_timestamp,
    load_optional_module,
    normalize_stt_language,
    write_docx,
)


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


def test_expected_output_suffixes_for_transcript_docx() -> None:
    assert expected_output_suffixes("transcript") == {".md"}
    assert expected_output_suffixes("transcript_docx") == {".docx"}
    assert expected_output_suffixes("auto_srt") == {".srt"}


def test_load_optional_module_filters_torchcodec_audio_decoding_warning(monkeypatch) -> None:
    def fake_import_module(module_name: str):
        warnings.warn_explicit(
            "\ntorchcodec is not installed correctly so built-in audio decoding will fail. Solutions are:",
            UserWarning,
            filename="pyannote/audio/core/io.py",
            lineno=47,
            module="pyannote.audio.core.io",
        )
        return module_name

    monkeypatch.setattr("stt_worker.importlib.import_module", fake_import_module)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert load_optional_module("whisperx") == "whisperx"

    assert caught == []


def test_write_docx_transcript(tmp_path) -> None:
    from docx import Document

    output_path = tmp_path / "transcript.docx"
    media_path = tmp_path / "sample.wav"
    media_path.write_bytes(b"RIFF")
    result = {
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 1.25, "text": "Hello world."},
            {"start": 1.25, "end": 2.5, "text": "Second line."},
        ],
    }

    write_docx(result, media_path, output_path, "large-v3")

    paragraphs = [paragraph.text for paragraph in Document(output_path).paragraphs]
    assert "Transcript" in paragraphs
    assert "Source: sample.wav" in paragraphs
    assert "Hello world. Second line." in paragraphs
    assert "00:00:00.000 - 00:00:01.250 Hello world." in paragraphs
