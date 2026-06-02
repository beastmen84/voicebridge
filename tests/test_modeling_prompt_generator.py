import pytest

import voicebridge.modeling_prompt_generator as prompt_generator
from voicebridge.modeling_prompt_generator import (
    MODELING_PROMPT_SOURCE_GENERATED,
    NO_UNUSED_MODELING_PROMPTS_MESSAGE,
    NoUnusedModelingPromptError,
    generate_modeling_prompt,
    generated_prompt_source,
    modeling_prompt_available_count,
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
        assert modeling_prompt_available_count(language_code) == 262_144
        corpus = prompt_generator.MODELING_PROMPT_CORPUS[prompt.language_code]
        assert all(len(corpus[slot_name]) == 8 for slot_name in prompt_generator.PROMPT_SLOT_ORDER)
        assert "?" in prompt.text or "؟" in prompt.text or "？" in prompt.text or "か" in prompt.text
        assert any(character.isdigit() for character in prompt.text)


def test_prompt_generation_avoids_recent_duplicates() -> None:
    prompts: list[str] = []
    for _index in range(20):
        prompt = generate_modeling_prompt("it", used_texts=tuple(prompts))
        prompts.append(prompt.text)

    assert len(set(prompts)) == len(prompts)


def test_prompt_generation_avoids_duplicates_across_languages() -> None:
    for language_code in VOICE_PROFILE_LANGUAGES:
        prompts: list[str] = []
        for _index in range(12):
            prompt = generate_modeling_prompt(language_code, used_texts=tuple(prompts))
            prompts.append(prompt.text)

        assert len(set(prompts)) == len(prompts), language_code


def test_prompt_generation_raises_when_pool_is_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    tiny_corpus = {
        "en": {
            "short": ("Tiny short.",),
            "medium": ("Tiny medium phrase for the prompt.",),
            "question": ("Tiny question?",),
            "numbers": ("Tiny numbers 1 and 2.",),
            "names": ("Tiny Nora and Leo.",),
            "punctuation": ("Tiny ending: clear and calm.",),
        }
    }
    monkeypatch.setattr(prompt_generator, "MODELING_PROMPT_CORPUS", tiny_corpus)
    prompts: list[str] = []
    for _index in range(modeling_prompt_available_count("en")):
        prompt = generate_modeling_prompt("en", used_texts=tuple(prompts))
        prompts.append(prompt.text)

    with pytest.raises(NoUnusedModelingPromptError, match=NO_UNUSED_MODELING_PROMPTS_MESSAGE):
        generate_modeling_prompt("en", used_texts=tuple(prompts))


def test_prompt_generation_falls_back_to_english() -> None:
    prompt = generate_modeling_prompt("unknown")

    assert prompt.language_code == "en"
    assert len(prompt.text) <= 450


def test_generated_prompt_source_detection() -> None:
    assert generated_prompt_source(MODELING_PROMPT_SOURCE_GENERATED)
    assert not generated_prompt_source("provided_text")
