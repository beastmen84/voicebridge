import re
from typing import Any

from voicebridge.app_settings import (
    load_preferred_voice_short_names as _load_preferred_voice_short_names,
)
from voicebridge.app_settings import (
    save_preferred_voice_short_names as _save_preferred_voice_short_names,
)
from voicebridge.languages import normalize_language_code

Voice = dict[str, Any]
VoiceMap = dict[str, str]

FALLBACK_VOICES: list[Voice] = [
    {"ShortName": "en-US-AriaNeural", "Locale": "en-US", "Gender": "Female"},
    {"ShortName": "en-US-JennyNeural", "Locale": "en-US", "Gender": "Female"},
    {"ShortName": "en-US-GuyNeural", "Locale": "en-US", "Gender": "Male"},
    {"ShortName": "en-GB-SoniaNeural", "Locale": "en-GB", "Gender": "Female"},
    {"ShortName": "en-GB-RyanNeural", "Locale": "en-GB", "Gender": "Male"},
    {"ShortName": "en-AU-NatashaNeural", "Locale": "en-AU", "Gender": "Female"},
    {"ShortName": "en-AU-WilliamNeural", "Locale": "en-AU", "Gender": "Male"},
    {"ShortName": "it-IT-ElsaNeural", "Locale": "it-IT", "Gender": "Female"},
    {"ShortName": "it-IT-IsabellaNeural", "Locale": "it-IT", "Gender": "Female"},
    {"ShortName": "it-IT-DiegoNeural", "Locale": "it-IT", "Gender": "Male"},
]

MAX_RECOMMENDED_VOICES = 8
RECOMMENDED_MIN_TOTAL_VOICES = 9
RECOMMENDED_VOICE_LOCALES = 4
RECOMMENDED_VOICES_PER_LOCALE = 2
VOICE_SECTION_RECOMMENDED = "Recommended voices"
VOICE_SECTION_PREFERRED = "Preferred voices"
VOICE_SECTION_OTHER = "Other voices"
VOICE_SECTION_SPACER = " "


def load_preferred_voice_short_names() -> set[str]:
    return _load_preferred_voice_short_names()


def save_preferred_voice_short_names(short_names: set[str]) -> None:
    _save_preferred_voice_short_names(short_names)


def voice_language_code(voice: Voice) -> str | None:
    locale = voice.get("Locale", "")
    return normalize_language_code(locale)


def voice_tag_summary(voice: Voice) -> str:
    voice_tags = voice.get("VoiceTag") or {}
    categories = voice_tags.get("ContentCategories") or []
    personalities = voice_tags.get("VoicePersonalities") or []

    parts = []
    if categories:
        parts.append(" / ".join(categories[:2]))
    if personalities:
        parts.append(" / ".join(personalities[:2]))

    return "; ".join(parts)


def voice_short_display_name(short_name: str) -> str:
    parts = short_name.split("-")
    voice_name = parts[-1] if parts else short_name
    voice_name = voice_name.replace("Neural", "")
    voice_name = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", voice_name)
    return voice_name.strip() or short_name


def is_multilingual_voice(voice: Voice) -> bool:
    return "Multilingual" in voice.get("ShortName", "")


def voice_display_label(voice: Voice) -> str:
    short_name = voice.get("ShortName", "")
    locale = voice.get("Locale", "")
    gender = voice.get("Gender", "")

    voice_name = voice_short_display_name(short_name)

    label = f"{locale} | {voice_name}"
    if gender:
        label = f"{label} ({gender})"

    tag_summary = voice_tag_summary(voice)
    if is_multilingual_voice(voice):
        tag_summary = "auto language" if not tag_summary else f"{tag_summary}; auto language"
    if tag_summary:
        label = f"{label} - {tag_summary}"

    return label


def voice_search_haystack(voice: Voice) -> str:
    voice_tags = voice.get("VoiceTag") or {}
    searchable_parts = [
        voice_display_label(voice),
        voice.get("ShortName", ""),
        voice.get("Locale", ""),
        voice.get("Gender", ""),
        " ".join(voice_tags.get("ContentCategories") or []),
        " ".join(voice_tags.get("VoicePersonalities") or []),
    ]
    return " ".join(searchable_parts).lower()


def filter_voices_by_query(voices: list[Voice], query: str) -> list[Voice]:
    tokens = [token.lower() for token in query.split() if token.strip()]
    if not tokens:
        return list(voices)

    return [
        voice for voice in voices
        if all(token in voice_search_haystack(voice) for token in tokens)
    ]


def sorted_voices(voices: list[Voice]) -> list[Voice]:
    return sorted(voices, key=lambda item: (
        item.get("Locale", ""),
        item.get("Gender", ""),
        is_multilingual_voice(item),
        item.get("ShortName", ""),
    ))


def build_voice_map(voices: list[Voice]) -> VoiceMap:
    voice_map: VoiceMap = {}

    for voice in sorted_voices(voices):
        label = voice_display_label(voice)
        if label in voice_map:
            label = f"{label} ({voice.get('ShortName', '')})"
        voice_map[label] = voice.get("ShortName", "")

    return voice_map


def voice_recommendation_key(voice: Voice) -> tuple[int, int, int, str, str]:
    voice_tags = voice.get("VoiceTag") or {}
    categories = set(voice_tags.get("ContentCategories") or [])
    short_name = voice.get("ShortName", "")

    status_rank = 0 if voice.get("Status") == "GA" else 1
    if categories.intersection({"News", "Novel"}):
        category_rank = 0
    elif "General" in categories:
        category_rank = 1
    elif "Conversation" in categories:
        category_rank = 2
    elif "Cartoon" in categories:
        category_rank = 9
    else:
        category_rank = 3

    multilingual_rank = 1 if "Multilingual" in short_name else 0
    return (
        status_rank,
        multilingual_rank,
        category_rank,
        voice.get("Gender", ""),
        short_name,
    )


def recommended_voices(voices: list[Voice]) -> list[Voice]:
    if len(voices) < RECOMMENDED_MIN_TOTAL_VOICES:
        return []

    voices_by_locale = {}
    for voice in voices:
        voices_by_locale.setdefault(voice.get("Locale", ""), []).append(voice)

    locale_codes = sorted(
        voices_by_locale,
        key=lambda locale_code: (-len(voices_by_locale[locale_code]), locale_code),
    )[:RECOMMENDED_VOICE_LOCALES]

    recommended = []
    used_short_names = set()
    for locale_code in locale_codes:
        locale_voices = sorted(voices_by_locale[locale_code], key=voice_recommendation_key)
        voices_added_for_locale = 0
        for gender in ("Female", "Male"):
            gender_voice = next(
                (
                    voice for voice in locale_voices
                    if voice.get("Gender") == gender
                    and voice.get("ShortName") not in used_short_names
                ),
                None,
            )
            if gender_voice:
                recommended.append(gender_voice)
                used_short_names.add(gender_voice.get("ShortName"))
                voices_added_for_locale += 1
                if len(recommended) >= MAX_RECOMMENDED_VOICES:
                    return recommended
                if voices_added_for_locale >= RECOMMENDED_VOICES_PER_LOCALE:
                    break

    return recommended


def build_voice_options(
    voices: list[Voice],
    include_recommendations: bool = True,
    preferred_short_names: set[str] | None = None,
) -> tuple[list[str], VoiceMap]:
    voices = sorted_voices(voices)
    preferred_short_names = set(preferred_short_names or [])
    preferred = [
        voice for voice in voices
        if voice.get("ShortName") in preferred_short_names
    ]
    recommended = recommended_voices(voices) if include_recommendations else []
    preferred_short_names_in_list = {
        voice.get("ShortName") for voice in preferred
    }
    recommended = [
        voice for voice in recommended
        if voice.get("ShortName") not in preferred_short_names_in_list
    ]
    recommended_short_names = {
        voice.get("ShortName") for voice in recommended
    }

    if not preferred and not recommended:
        voice_map = build_voice_map(voices)
        return list(voice_map.keys()), voice_map

    values: list[str] = []
    voice_map: VoiceMap = {}

    def add_voice(voice: Voice, prefix: str = "") -> None:
        label = f"{prefix}{voice_display_label(voice)}"
        if label in voice_map:
            label = f"{label} ({voice.get('ShortName', '')})"
        values.append(label)
        voice_map[label] = voice.get("ShortName", "")

    def add_section(section_title: str, section_voices: list[Voice]) -> None:
        if not section_voices:
            return
        if values:
            values.append(VOICE_SECTION_SPACER)
        values.append(section_title)
        for voice in section_voices:
            add_voice(voice, prefix="  ")

    add_section(VOICE_SECTION_PREFERRED, preferred)
    add_section(VOICE_SECTION_RECOMMENDED, recommended)

    other_voices = [
        voice for voice in voices
        if voice.get("ShortName") not in recommended_short_names
        and voice.get("ShortName") not in preferred_short_names_in_list
    ]
    if other_voices:
        add_section(VOICE_SECTION_OTHER, other_voices)

    return values, voice_map


def find_voice_label(voice_map: VoiceMap, short_name: str | None) -> str:
    if not short_name:
        return ""

    return next(
        (
            label for label, mapped_short_name in voice_map.items()
            if mapped_short_name == short_name
        ),
        "",
    )


def filter_voices_by_language(voices: list[Voice], language_code: str | None) -> list[Voice]:
    language_code = normalize_language_code(language_code)
    return [
        voice for voice in voices
        if voice_language_code(voice) == language_code
    ]
