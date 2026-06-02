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


def test_prompt_generation_varies_all_slots_in_short_runs() -> None:
    prompts: list[str] = []
    corpus = prompt_generator.MODELING_PROMPT_CORPUS["it"]
    slot_values = {slot_name: set() for slot_name in prompt_generator.PROMPT_SLOT_ORDER}

    for _index in range(10):
        prompt = generate_modeling_prompt("it", used_texts=tuple(prompts))
        prompts.append(prompt.text)
        for slot_name in prompt_generator.PROMPT_SLOT_ORDER:
            sentence = next((entry for entry in corpus[slot_name] if entry in prompt.text), None)
            assert sentence is not None, slot_name
            slot_values[slot_name].add(sentence)

    assert all(len(values) > 1 for values in slot_values.values())


def test_prompt_generation_avoids_duplicates_across_languages() -> None:
    for language_code in VOICE_PROFILE_LANGUAGES:
        prompts: list[str] = []
        for _index in range(12):
            prompt = generate_modeling_prompt(language_code, used_texts=tuple(prompts))
            prompts.append(prompt.text)

        assert len(set(prompts)) == len(prompts), language_code


def test_latin_prompt_corpus_uses_native_orthography() -> None:
    required_characters = {
        "it": "èù",
        "es": "áéíóúñ¿¡",
        "fr": "àçèéêîô",
        "de": "äöüß",
        "pt": "áâãçéêíóõú",
        "pl": "ąćęłóśźż",
        "nl": "é",
        "cs": "áčéěíóřšůýž",
        "hu": "áéíóöőúüű",
    }
    forbidden_ascii_fragments = {
        "it": ("e'", "piu'"),
        "es": ("microfono", "lapices", "despues", "puntuacion", "está frase"),
        "fr": ("verifie", "verifier", "repeter", "idee", "etre"),
        "de": ("gleichmaessig", "oeffne", "Blaetter", "fuer"),
        "pt": ("Voce", "audio", "nao", "pontuacao"),
        "pl": ("glos", "mozemy", "odleglosc", "krot", "podnosic", "poruszac", "taką sama"),
        "cs": ("Muzeme", "zustava", "prirozene", "punč", "že stejné", "Pokracuj", "nema"),
        "hu": ("szoveg", "termeszet", "rovid", "elott", "szobat", "állj még", "Mateot"),
    }

    for language_code, characters in required_characters.items():
        corpus = prompt_generator.MODELING_PROMPT_CORPUS[language_code]
        corpus_text = " ".join(text for slot_name in prompt_generator.PROMPT_SLOT_ORDER for text in corpus[slot_name])

        missing = [character for character in characters if character not in corpus_text]
        assert not missing, (language_code, missing)
        assert not any(fragment in corpus_text for fragment in forbidden_ascii_fragments.get(language_code, ()))

    assert all(text.startswith("¿") for text in prompt_generator.MODELING_PROMPT_CORPUS["es"]["question"])


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
