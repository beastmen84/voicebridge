from voicebridge.modeling_prompt_generator import (
    MODELING_PROMPT_SOURCE_GENERATED,
    generate_modeling_prompt,
    generated_prompt_source,
    modeling_prompt_language_key,
    prompt_corpus_languages_complete,
)
from voicebridge.voice_profiles import VOICE_PROFILE_LANGUAGES


def test_prompt_corpus_covers_voice_profile_languages() -> None:
    assert prompt_corpus_languages_complete()
    for language_code in VOICE_PROFILE_LANGUAGES:
        prompt = generate_modeling_prompt(language_code)

        assert prompt.language_code == modeling_prompt_language_key(language_code)
        assert prompt.source == MODELING_PROMPT_SOURCE_GENERATED
        assert len(prompt.text) <= 450
        assert "?" in prompt.text or "؟" in prompt.text or "？" in prompt.text or "か" in prompt.text
        assert any(character.isdigit() for character in prompt.text)


def test_prompt_generation_avoids_recent_duplicates() -> None:
    first = generate_modeling_prompt("it", used_texts=())
    second = generate_modeling_prompt("it", used_texts=(first.text,))
    third = generate_modeling_prompt("it", used_texts=(first.text, second.text))

    assert len({first.text, second.text, third.text}) == 3


def test_prompt_generation_falls_back_to_english() -> None:
    prompt = generate_modeling_prompt("unknown")

    assert prompt.language_code == "en"
    assert len(prompt.text) <= 450


def test_generated_prompt_source_detection() -> None:
    assert generated_prompt_source(MODELING_PROMPT_SOURCE_GENERATED)
    assert not generated_prompt_source("provided_text")
