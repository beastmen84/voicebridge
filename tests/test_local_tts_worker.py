import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_tts_worker import (
    XTTS_MODEL_REQUIRED_FILES,
    XTTS_STABLE_INFERENCE_SETTINGS,
    load_xtts_model,
    merge_wav_files,
    normalize_tts_language,
    normalize_tts_text,
    read_text,
    reference_audio_paths,
    split_tts_text_for_xtts,
    synthesize_text_chunks,
    write_xtts_terms_agreement,
    xtts_model_cache_dir,
    xtts_model_ready,
    xtts_terms_agreed,
)
from voicebridge.local_tts_presets import local_tts_preset_settings, normalize_local_tts_preset_key


def write_sized_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


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


def test_normalize_tts_text_cleans_spacing_and_line_breaks() -> None:
    text = " Ciao   ,  mondo .\n\nNuova   frase!Seconda frase "

    assert normalize_tts_text(text) == "Ciao, mondo. Nuova frase! Seconda frase"


def test_split_tts_text_for_xtts_keeps_chunks_short() -> None:
    text = (
        "Prima frase completa. "
        "Seconda frase con molte parole da dividere in modo prevedibile, senza lasciare un blocco troppo lungo. "
        "Terza frase."
    )

    chunks = split_tts_text_for_xtts(text, max_chars=55)

    assert len(chunks) > 1
    assert all(len(chunk) <= 55 for chunk in chunks)
    assert " ".join(chunks) == normalize_tts_text(text)


def test_xtts_model_ready_checks_required_files(tmp_path: Path) -> None:
    model_dir = xtts_model_cache_dir(tmp_path)
    model_dir.mkdir(parents=True)

    assert not xtts_model_ready(tmp_path)

    sizes = {
        "config.json": 32,
        "model.pth": 1024 * 1024,
        "speakers_xtts.pth": 1024,
        "vocab.json": 32,
    }
    for filename in XTTS_MODEL_REQUIRED_FILES:
        write_sized_file(model_dir / filename, sizes[filename])

    assert xtts_model_ready(tmp_path)


def test_xtts_terms_agreement_writes_marker(tmp_path: Path) -> None:
    assert not xtts_terms_agreed(tmp_path)

    write_xtts_terms_agreement(tmp_path)

    assert xtts_terms_agreed(tmp_path)


def test_load_xtts_model_uses_trained_model_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_path = tmp_path / "model.pth"
    config_path = tmp_path / "config.json"
    vocab_path = tmp_path / "vocab.json"
    model_path.write_text("model", encoding="utf-8")
    config_path.write_text("config", encoding="utf-8")
    vocab_path.write_text("vocab", encoding="utf-8")
    calls = []

    class FakeTts:
        def __init__(self, *init_args, **kwargs) -> None:
            calls.append((init_args, kwargs))
            self.device = ""

        def to(self, device: str):
            self.device = device
            return self

    monkeypatch.setattr("local_tts_worker.load_tts_api", lambda: FakeTts)
    args = SimpleNamespace(
        model_path=str(model_path),
        config_path=str(config_path),
        model_dir=str(tmp_path / "unused"),
        model="tts_models/multilingual/multi-dataset/xtts_v2",
    )

    tts = load_xtts_model(args, "cpu")

    assert tts.device == "cpu"
    assert calls == [
        (
            (),
            {
                "model_path": str(model_path.parent.resolve()),
                "config_path": str(config_path.resolve()),
                "progress_bar": False,
            },
        )
    ]


def test_merge_wav_files_inserts_short_silence_between_chunks(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "merged.wav"
    for path, byte in ((first, b"\x01"), (second, b"\x02")):
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(1)
            wav_file.setframerate(4)
            wav_file.writeframes(byte * 2)

    merge_wav_files([first, second], output)

    with wave.open(str(output), "rb") as wav_file:
        assert wav_file.getnframes() == 5
        assert wav_file.readframes(5) == b"\x01\x01\x00\x02\x02"


def write_fake_tts_wav(path: str | Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(4)
        wav_file.writeframes(b"\x01" * 4)


def test_synthesize_text_chunks_passes_stable_xtts_settings(tmp_path: Path) -> None:
    class FakeTts:
        def __init__(self) -> None:
            self.calls = []

        def tts_to_file(self, **kwargs) -> None:
            self.calls.append(kwargs)
            write_fake_tts_wav(kwargs["file_path"])

    tts = FakeTts()

    timeline = synthesize_text_chunks(tts, ["Ciao mondo."], ["voice.wav"], "it", tmp_path / "output.wav")

    assert tts.calls[0]["text"] == "Ciao mondo;"
    assert timeline[0]["duration_seconds"] == 1.0
    for key, value in XTTS_STABLE_INFERENCE_SETTINGS.items():
        assert tts.calls[0][key] == value


def test_synthesize_text_chunks_accepts_selected_xtts_settings(tmp_path: Path) -> None:
    class FakeTts:
        def __init__(self) -> None:
            self.calls = []

        def tts_to_file(self, **kwargs) -> None:
            self.calls.append(kwargs)
            write_fake_tts_wav(kwargs["file_path"])

    tts = FakeTts()
    settings = local_tts_preset_settings("balanced")

    synthesize_text_chunks(tts, ["Ciao mondo."], ["voice.wav"], "it", tmp_path / "output.wav", settings)

    for key, value in settings.items():
        assert tts.calls[0][key] == value


def test_unknown_local_tts_preset_falls_back_to_stable() -> None:
    assert normalize_local_tts_preset_key("unknown") == "stable"
    assert local_tts_preset_settings("unknown") == XTTS_STABLE_INFERENCE_SETTINGS
