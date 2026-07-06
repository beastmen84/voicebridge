from voicebridge.tts_text import (
    EDGE_TTS_MAX_CHUNK_CHARS,
    normalize_tts_text,
    prepare_tts_chunk_for_generation,
    sentence_fragments_for_tts,
    split_edge_tts_text_for_tts,
    split_tts_text_for_tts,
)


def test_normalize_tts_text_handles_numbered_lists_and_file_extensions() -> None:
    text = "1. Primo punto\n2) Secondo punto\nApri file.txt ... poi video.mp4"

    assert normalize_tts_text(text) == "1, Primo punto 2, Secondo punto Apri file txt, poi video mp4"


def test_sentence_fragments_keep_common_abbreviations_together() -> None:
    text = normalize_tts_text("Il Dott. Rossi parla. Poi continua.")

    assert sentence_fragments_for_tts(text) == ["Il Dott. Rossi parla.", "Poi continua."]


def test_split_tts_text_for_tts_preserves_short_sentences() -> None:
    text = "Ciao mondo. Questa frase resta intera."

    assert split_tts_text_for_tts(text, max_chars=80) == ["Ciao mondo. Questa frase resta intera."]


def test_split_tts_text_for_tts_splits_long_sentences_on_soft_punctuation() -> None:
    text = (
        "Questa frase è lunga, contiene una pausa morbida, e deve essere divisa senza spezzare "
        "bruscamente ogni parola."
    )

    chunks = split_tts_text_for_tts(text, max_chars=55)

    assert len(chunks) > 1
    assert all(len(chunk) <= 55 for chunk in chunks)


def test_prepare_tts_chunk_for_generation_softens_terminal_punctuation() -> None:
    assert prepare_tts_chunk_for_generation("Ciao mondo.") == "Ciao mondo;"
    assert prepare_tts_chunk_for_generation("Attenzione!") == "Attenzione!"
    assert prepare_tts_chunk_for_generation("Bro! Fra! Venite qui!") == "Bro; Fra; Venite qui!"
    assert prepare_tts_chunk_for_generation("Davvero?") == "Davvero?"
    assert prepare_tts_chunk_for_generation("file txt") == "file txt"


def test_split_tts_text_for_tts_merges_short_exclamation_chunks() -> None:
    assert split_tts_text_for_tts("Bro!\nFra!\nVenite qui!") == ["Bro! Fra! Venite qui!"]


def test_split_edge_tts_text_for_tts_packs_clean_sentence_blocks() -> None:
    text = " ".join(
        f"Frase numero {index} con contenuto sufficiente per riempire il blocco senza tagli bruschi."
        for index in range(1, 16)
    )

    chunks = split_edge_tts_text_for_tts(text, target_chars=210, max_chars=300)

    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)
    assert all(chunk.endswith(".") for chunk in chunks)


def test_split_edge_tts_text_for_tts_keeps_realistic_chunks_under_maximum() -> None:
    paragraph = " ".join(
        f"Questo e' il periodo {index}, con parole aggiuntive per simulare un documento lungo."
        for index in range(1, 900)
    )

    chunks = split_edge_tts_text_for_tts(paragraph)

    assert len(chunks) > 1
    assert all(len(chunk) <= EDGE_TTS_MAX_CHUNK_CHARS for chunk in chunks)
