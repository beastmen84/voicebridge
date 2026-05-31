from __future__ import annotations

from typing import Final, TypedDict


class LocalTtsPreset(TypedDict):
    label: str
    description: str
    settings: dict[str, float | int]


DEFAULT_LOCAL_TTS_PRESET_KEY: Final = "stable"

LOCAL_TTS_PRESETS: Final[dict[str, LocalTtsPreset]] = {
    "stable": {
        "label": "Stable",
        "description": "Conservative XTTS settings for punctuation glitches and short text.",
        "settings": {
            "temperature": 0.65,
            "top_k": 30,
            "top_p": 0.75,
            "repetition_penalty": 8.0,
            "length_penalty": 1.0,
        },
    },
    "balanced": {
        "label": "Balanced",
        "description": "Middle ground between stability and natural prosody.",
        "settings": {
            "temperature": 0.70,
            "top_k": 50,
            "top_p": 0.85,
            "repetition_penalty": 5.0,
            "length_penalty": 1.0,
        },
    },
    "natural": {
        "label": "Natural",
        "description": "Less restrictive XTTS settings for more expressive speech.",
        "settings": {
            "temperature": 0.75,
            "top_k": 50,
            "top_p": 0.85,
            "repetition_penalty": 4.5,
            "length_penalty": 1.0,
        },
    },
}


def normalize_local_tts_preset_key(value: str | None) -> str:
    if value in LOCAL_TTS_PRESETS:
        return value
    return DEFAULT_LOCAL_TTS_PRESET_KEY


def local_tts_preset_label(value: str | None) -> str:
    preset_key = normalize_local_tts_preset_key(value)
    return LOCAL_TTS_PRESETS[preset_key]["label"]


def local_tts_preset_description(value: str | None) -> str:
    preset_key = normalize_local_tts_preset_key(value)
    preset = LOCAL_TTS_PRESETS[preset_key]
    settings = preset["settings"]
    return (
        f"{preset['description']}\n"
        f"temperature={settings['temperature']}, top_k={settings['top_k']}, "
        f"top_p={settings['top_p']}, repetition_penalty={settings['repetition_penalty']}"
    )


def local_tts_preset_settings(value: str | None) -> dict[str, float | int]:
    preset_key = normalize_local_tts_preset_key(value)
    return dict(LOCAL_TTS_PRESETS[preset_key]["settings"])
