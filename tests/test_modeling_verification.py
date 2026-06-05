from pathlib import Path

from voicebridge.modeling_datasets import (
    MODELING_VERIFICATION_MATCH_OK,
    MODELING_VERIFICATION_NEEDS_REVIEW,
)
from voicebridge.modeling_verification import (
    compare_transcript_to_expected,
    read_whisper_markdown_text,
    verification_words,
)


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


def test_verification_words_normalize_italian_digit_words() -> None:
    assert verification_words("3 matite, 12 fogli e 24 etichette") == [
        "num_3",
        "matite",
        "num_12",
        "fogli",
        "e",
        "num_24",
        "etichette",
    ]
    assert verification_words("tre matite, dodici fogli e ventiquattro etichette") == [
        "num_3",
        "matite",
        "num_12",
        "fogli",
        "e",
        "num_24",
        "etichette",
    ]


def test_verification_words_normalize_italian_half_hour() -> None:
    assert verification_words("Alle 9:30 registro 3 frasi.") == [
        "alle",
        "time_9_30",
        "registro",
        "num_3",
        "frasi",
    ]
    assert verification_words("Alle nove e mezza registro tre frasi.") == [
        "alle",
        "time_9_30",
        "registro",
        "num_3",
        "frasi",
    ]


def test_compare_transcript_ignores_italian_digit_word_variants() -> None:
    result = compare_transcript_to_expected(
        "Alle 9:30 registro 3 frasi brevi e 2 frasi piu lunghe.",
        "Alle nove e mezza registro tre frasi brevi e due frasi piu lunghe.",
    )

    assert result["status"] == MODELING_VERIFICATION_MATCH_OK
    assert result["score"] == 100.0
    assert "Word error rate: 0.0%" in result["details"]


def test_compare_transcript_still_counts_real_word_errors() -> None:
    result = compare_transcript_to_expected(
        "La seconda clip dura 42 secondi e contiene 6 pause naturali.",
        "La seconda clip dura 42 secondi e contiene sei pasi naturali.",
    )

    assert result["status"] == MODELING_VERIFICATION_MATCH_OK
    assert result["score"] < 100.0
    assert "Word error rate: 9.1%" in result["details"]
