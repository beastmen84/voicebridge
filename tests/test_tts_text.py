from voicebridge.tts_text import normalize_tts_text, sentence_fragments_for_tts, split_tts_text_for_tts


def test_normalize_tts_text_handles_numbered_lists_and_file_extensions() -> None:
    text = "1. Primo punto\n2) Secondo punto\nApri file.txt ... poi video.mp4"

    assert normalize_tts_text(text) == "1, Primo punto 2, Secondo punto Apri file txt, poi video mp4"


def test_sentence_fragments_keep_common_abbreviations_together() -> None:
    text = normalize_tts_text("Il Dott. Rossi parla. Poi continua.")

    assert sentence_fragments_for_tts(text) == ["Il Dott. Rossi parla.", "Poi continua."]


def test_split_tts_text_for_tts_preserves_short_sentences() -> None:
    text = "Ciao mondo. Questa frase resta intera."

    assert split_tts_text_for_tts(text, max_chars=80) == ["Ciao mondo.", "Questa frase resta intera."]


def test_split_tts_text_for_tts_splits_long_sentences_on_soft_punctuation() -> None:
    text = (
        "Questa frase è lunga, contiene una pausa morbida, e deve essere divisa senza spezzare "
        "bruscamente ogni parola."
    )

    chunks = split_tts_text_for_tts(text, max_chars=55)

    assert len(chunks) > 1
    assert all(len(chunk) <= 55 for chunk in chunks)
