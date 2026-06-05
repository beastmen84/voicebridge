from voicebridge.recording_text import format_recording_text_for_display


def test_format_recording_text_for_display_breaks_reading_sentences() -> None:
    text = "  Prima frase.   Seconda domanda? Terza frase; poi chiudo.  "

    assert format_recording_text_for_display(text) == "\n\n".join(
        [
            "Prima frase.",
            "Seconda domanda?",
            "Terza frase; poi chiudo.",
        ]
    )


def test_format_recording_text_for_display_preserves_text_without_break_marks() -> None:
    assert format_recording_text_for_display("  Nessuna pausa   interna  ") == "Nessuna pausa interna"
