from pathlib import Path

import pytest

from local_tts_worker import (
    XTTS_MODEL_REQUIRED_FILES,
    normalize_tts_language,
    read_text,
    reference_audio_paths,
    write_xtts_terms_agreement,
    xtts_model_cache_dir,
    xtts_model_ready,
    xtts_terms_agreed,
)


def test_normalize_tts_language_keeps_xtts_chinese_code() -> None:
    assert normalize_tts_language("zh_CN") == "zh-cn"
    assert normalize_tts_language("en-US") == "en"
    assert normalize_tts_language("") == "it"


def test_reference_audio_paths_requires_existing_files(tmp_path: Path) -> None:
    reference = tmp_path / "voice.wav"
    reference.write_bytes(b"RIFF")

    assert reference_audio_paths([str(reference)]) == [str(reference.resolve())]
    with pytest.raises(ValueError, match="not found"):
        reference_audio_paths([str(tmp_path / "missing.wav")])


def test_read_text_strips_common_utf8_bom(tmp_path: Path) -> None:
    text_path = tmp_path / "input.txt"
    text_path.write_text("\ufeff Ciao mondo \n", encoding="utf-8")

    assert read_text(text_path) == "Ciao mondo"


def test_xtts_model_ready_checks_required_files(tmp_path: Path) -> None:
    model_dir = xtts_model_cache_dir(tmp_path)
    model_dir.mkdir(parents=True)

    assert not xtts_model_ready(tmp_path)

    for filename in XTTS_MODEL_REQUIRED_FILES:
        (model_dir / filename).write_text("x", encoding="utf-8")

    assert xtts_model_ready(tmp_path)


def test_xtts_terms_agreement_writes_marker(tmp_path: Path) -> None:
    assert not xtts_terms_agreed(tmp_path)

    write_xtts_terms_agreement(tmp_path)

    assert xtts_terms_agreed(tmp_path)
