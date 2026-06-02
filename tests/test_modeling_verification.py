from pathlib import Path

from voicebridge.modeling_datasets import (
    MODELING_VERIFICATION_MATCH_OK,
    MODELING_VERIFICATION_NEEDS_REVIEW,
)
from voicebridge.modeling_verification import compare_transcript_to_expected, read_whisper_markdown_text


def test_read_whisper_markdown_text_extracts_text_section(tmp_path: Path) -> None:
    markdown_path = tmp_path / "transcript.md"
    markdown_path.write_text(
        "\n".join(
            [
                "# Transcript",
                "",
                "## Text",
                "",
                "Hello world from the clip.",
                "",
                "## Timed Segments",
                "",
                "- `00:00 - 00:01` Hello world",
            ]
        ),
        encoding="utf-8",
    )

    assert read_whisper_markdown_text(markdown_path) == "Hello world from the clip."


def test_compare_transcript_to_expected_scores_match_and_review() -> None:
    match = compare_transcript_to_expected(
        "The quick brown fox asks a clear question.",
        "The quick brown fox asks a clear question.",
    )
    review = compare_transcript_to_expected(
        "The quick brown fox asks a clear question.",
        "A completely different sentence was spoken.",
    )

    assert match["status"] == MODELING_VERIFICATION_MATCH_OK
    assert match["score"] > 95.0
    assert review["status"] == MODELING_VERIFICATION_NEEDS_REVIEW
    assert review["score"] < 70.0
