import difflib
import re
from pathlib import Path
from typing import TypedDict

from voicebridge.modeling_datasets import (
    MODELING_VERIFICATION_MATCH_OK,
    MODELING_VERIFICATION_NEEDS_REVIEW,
)

MODELING_VERIFICATION_MIN_SIMILARITY = 0.86
MODELING_VERIFICATION_MAX_WER = 0.30


class TranscriptVerificationResult(TypedDict):
    status: str
    score: float
    detected_text: str
    details: str


def read_whisper_markdown_text(path: str | Path) -> str:
    text = Path(path).read_text(encoding="utf-8")
    text_match = re.search(r"(?ms)^## Text\s+(.+?)(?:\n## |\Z)", text)
    if text_match:
        return clean_verification_text(text_match.group(1))
    body_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "-", "`"))
    ]
    return clean_verification_text(" ".join(body_lines))


def compare_transcript_to_expected(expected_text: str, detected_text: str) -> TranscriptVerificationResult:
    expected_clean = clean_verification_text(expected_text)
    detected_clean = clean_verification_text(detected_text)
    expected_words = verification_words(expected_clean)
    detected_words = verification_words(detected_clean)
    if not expected_words or not detected_words:
        return {
            "status": MODELING_VERIFICATION_NEEDS_REVIEW,
            "score": 0.0,
            "detected_text": detected_clean,
            "details": "Transcript verification failed: expected or detected text is empty.",
        }

    similarity = difflib.SequenceMatcher(None, expected_words, detected_words, autojunk=False).ratio()
    wer = word_error_rate(expected_words, detected_words)
    score = round(max(0.0, min(1.0, (similarity + (1.0 - min(1.0, wer))) / 2.0)) * 100, 1)
    status = (
        MODELING_VERIFICATION_MATCH_OK
        if similarity >= MODELING_VERIFICATION_MIN_SIMILARITY and wer <= MODELING_VERIFICATION_MAX_WER
        else MODELING_VERIFICATION_NEEDS_REVIEW
    )
    details = "\n".join(
        [
            f"Similarity: {similarity * 100:.1f}%",
            f"Word error rate: {wer * 100:.1f}%",
            f"Expected words: {len(expected_words)}",
            f"Detected words: {len(detected_words)}",
            "",
            "Detected text:",
            detected_clean or "(empty)",
        ]
    )
    return {
        "status": status,
        "score": score,
        "detected_text": detected_clean,
        "details": details,
    }


def clean_verification_text(text: str) -> str:
    return " ".join(text.replace("\r\n", "\n").replace("\r", "\n").split())


def verification_words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def word_error_rate(expected_words: list[str], detected_words: list[str]) -> float:
    rows = len(expected_words) + 1
    cols = len(detected_words) + 1
    previous = list(range(cols))
    for row in range(1, rows):
        current = [row] + [0] * (cols - 1)
        expected_word = expected_words[row - 1]
        for col in range(1, cols):
            cost = 0 if expected_word == detected_words[col - 1] else 1
            current[col] = min(
                previous[col] + 1,
                current[col - 1] + 1,
                previous[col - 1] + cost,
            )
        previous = current
    return previous[-1] / max(1, len(expected_words))
