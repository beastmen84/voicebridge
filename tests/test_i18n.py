from voicebridge.i18n import (
    DEFAULT_UI_LANGUAGE,
    normalize_ui_language,
    translate_static_ui_text,
    translate_ui,
    ui_language_name,
)


def test_normalize_ui_language_falls_back_to_default() -> None:
    assert normalize_ui_language("it") == "it"
    assert normalize_ui_language("unknown") == DEFAULT_UI_LANGUAGE
    assert normalize_ui_language(None) == DEFAULT_UI_LANGUAGE


def test_translate_ui_uses_selected_language_and_formats_values() -> None:
    assert translate_ui("sidebar.status", "it") == "STATO"
    assert translate_ui("voice_profiles.status.saved", "it", name="Marco", status="Pronto") == (
        "Salvato: Marco | Pronto"
    )


def test_translate_ui_falls_back_to_english_then_key() -> None:
    assert translate_ui("sidebar.status", "unknown") == "STATUS"
    assert translate_ui("missing.key", "it") == "missing.key"


def test_ui_language_name_uses_normalized_code() -> None:
    assert ui_language_name("it") == "Italiano"
    assert ui_language_name("bad") == "English"


def test_translate_static_ui_text_keeps_technical_terms_precise() -> None:
    assert translate_static_ui_text("Reference audio", "it") == "Audio di riferimento"
    assert translate_static_ui_text("Download Whisper large-v3", "it") == "Scarica Whisper large-v3"
    assert translate_static_ui_text("Yes", "it") == "Sì"
    assert translate_static_ui_text("Unknown text", "it") == "Unknown text"
    assert translate_static_ui_text("Reference audio", "en") == "Reference audio"
