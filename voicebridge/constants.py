from pathlib import Path

from languages import LANGUAGE_NAMES
from media_tools import (
    BURN_QUALITY_AUTO,
    BURN_QUALITY_HIGH,
    BURN_QUALITY_MAXIMUM,
    BURN_QUALITY_ORIGINAL_BITRATE,
    BURN_QUALITY_STANDARD,
    VIDEO_CLEANUP_METHOD_FREEZE,
    VIDEO_CLEANUP_METHOD_REMOVE,
)
from media_tools import BURN_QUALITY_CRF_VALUES as _BURN_QUALITY_CRF_VALUES

APP_NAME = "VoiceBridge"
APP_ATTRIBUTION = "© Davide Marchi"
APP_ICON = Path("images") / "file_to_mp3.ico"
APP_ICON_PNG = Path("images") / "file_to_mp3.png"
DEFAULT_VOICE_SHORT_NAME = "en-US-AriaNeural"
DEFAULT_RATE = "-5%"
RATE_CHOICES = ["-20%", "-15%", "-10%", "-5%", "+0%", "+5%", "+10%"]
TTS_SPLIT_PARAGRAPHS = "Paragraphs"
TTS_SPLIT_LINES = "Lines"
STT_MODEL = "large-v3"
UI_QUEUE_POLL_MS = 50

STT_MODE_LABELS = {
    "Transcript Markdown (.md)": "transcript",
    "Auto subtitles (.srt)": "auto_srt",
    "Subtitles from provided text (.srt)": "align_text",
}
STT_SRT_MODES = {"auto_srt", "align_text"}
STT_ALIGNMENT_READY_LANGUAGES = {"en", "it"}
STT_LANGUAGE_AUTO_LABEL = "Auto detect"
STT_LANGUAGE_CODES = [
    "auto",
    "en",
    "it",
    *[
        code for code in sorted(LANGUAGE_NAMES, key=lambda language_code: LANGUAGE_NAMES[language_code])
        if code not in STT_ALIGNMENT_READY_LANGUAGES
    ],
]
STT_LANGUAGE_LEGACY_LABELS = {STT_LANGUAGE_AUTO_LABEL: "auto"} | {
    LANGUAGE_NAMES[code]: code for code in LANGUAGE_NAMES
}
STT_CPU_ONLY_STATUS = "CPU-only STT runtime included."
MISSING_ALIGNMENT_PREFIX = "MISSING_ALIGNMENT_MODEL:"

BURN_QUALITY_AUTO_LABEL = "Auto (recommended)"
BURN_QUALITY_STANDARD_LABEL = "Standard (CRF 20)"
BURN_QUALITY_HIGH_LABEL = "High quality (CRF 18)"
BURN_QUALITY_MAXIMUM_LABEL = "Maximum quality (CRF 16)"
BURN_QUALITY_ORIGINAL_LABEL = "Original bitrate"
BURN_QUALITY_LABELS = [
    BURN_QUALITY_AUTO_LABEL,
    BURN_QUALITY_STANDARD_LABEL,
    BURN_QUALITY_HIGH_LABEL,
    BURN_QUALITY_MAXIMUM_LABEL,
    BURN_QUALITY_ORIGINAL_LABEL,
]
BURN_QUALITY_BY_LABEL = {
    BURN_QUALITY_AUTO_LABEL: BURN_QUALITY_AUTO,
    BURN_QUALITY_STANDARD_LABEL: BURN_QUALITY_STANDARD,
    BURN_QUALITY_HIGH_LABEL: BURN_QUALITY_HIGH,
    BURN_QUALITY_MAXIMUM_LABEL: BURN_QUALITY_MAXIMUM,
    BURN_QUALITY_ORIGINAL_LABEL: BURN_QUALITY_ORIGINAL_BITRATE,
}
BURN_QUALITY_CRF_VALUES = _BURN_QUALITY_CRF_VALUES
BURN_QUALITY_DESCRIPTIONS = {
    BURN_QUALITY_AUTO_LABEL: (
        "Chooses CRF 20 for most 1080p videos, CRF 18 "
        "for 4K or high-bitrate 1080p sources."
    ),
    BURN_QUALITY_STANDARD_LABEL: "CRF 20: high quality for 1080p, usually smaller files.",
    BURN_QUALITY_HIGH_LABEL: "CRF 18: closer to the source, larger files.",
    BURN_QUALITY_MAXIMUM_LABEL: "CRF 16: very high quality, much larger files.",
    BURN_QUALITY_ORIGINAL_LABEL: "Targets the source video bitrate; still re-encodes, so it is not lossless.",
}
VIDEO_SUBTITLE_EMBED_LABEL = "Embed SRT track"
VIDEO_SUBTITLE_BURN_LABEL = "Burn in SRT"
VIDEO_SUBTITLE_MODE_LABELS = [VIDEO_SUBTITLE_EMBED_LABEL, VIDEO_SUBTITLE_BURN_LABEL]
VIDEO_SUBTITLE_MODE_BY_LABEL = {
    VIDEO_SUBTITLE_EMBED_LABEL: "embed",
    VIDEO_SUBTITLE_BURN_LABEL: "burn",
}
VIDEO_SUBTITLE_MODE_DESCRIPTIONS = {
    VIDEO_SUBTITLE_EMBED_LABEL: "Adds the SRT as a subtitle track. Video and audio streams are copied when possible.",
    VIDEO_SUBTITLE_BURN_LABEL: "Draws subtitles into the video frames. The video must be re-encoded.",
}
VIDEO_SUBTITLE_POSITION_LABELS = {
    "Bottom center": 2,
    "Middle center": 5,
    "Top center": 8,
}
VIDEO_CLEANUP_QUALITY_LABELS = [
    BURN_QUALITY_AUTO_LABEL,
    BURN_QUALITY_STANDARD_LABEL,
    BURN_QUALITY_HIGH_LABEL,
    BURN_QUALITY_MAXIMUM_LABEL,
    BURN_QUALITY_ORIGINAL_LABEL,
]
VIDEO_CLEANUP_QUALITY_BY_LABEL = {
    BURN_QUALITY_AUTO_LABEL: BURN_QUALITY_AUTO,
    BURN_QUALITY_ORIGINAL_LABEL: BURN_QUALITY_ORIGINAL_BITRATE,
    BURN_QUALITY_HIGH_LABEL: BURN_QUALITY_HIGH,
    BURN_QUALITY_MAXIMUM_LABEL: BURN_QUALITY_MAXIMUM,
    BURN_QUALITY_STANDARD_LABEL: BURN_QUALITY_STANDARD,
}
VIDEO_CLEANUP_QUALITY_DESCRIPTIONS = {
    BURN_QUALITY_AUTO_LABEL: BURN_QUALITY_DESCRIPTIONS[BURN_QUALITY_AUTO_LABEL],
    BURN_QUALITY_ORIGINAL_LABEL: "Targets the source video bitrate; still re-encodes, so it is not lossless.",
    BURN_QUALITY_HIGH_LABEL: "CRF 18: high visual quality, bitrate may differ from the source.",
    BURN_QUALITY_MAXIMUM_LABEL: "CRF 16: very high quality, larger output files.",
    BURN_QUALITY_STANDARD_LABEL: "CRF 20: good quality and smaller files, but less conservative.",
}
VIDEO_CLEANUP_FREEZE_LABEL = "Freeze previous frame"
VIDEO_CLEANUP_REMOVE_LABEL = "Remove selected frames"
VIDEO_CLEANUP_METHOD_LABELS = [
    VIDEO_CLEANUP_FREEZE_LABEL,
    VIDEO_CLEANUP_REMOVE_LABEL,
]
VIDEO_CLEANUP_METHOD_BY_LABEL = {
    VIDEO_CLEANUP_FREEZE_LABEL: VIDEO_CLEANUP_METHOD_FREEZE,
    VIDEO_CLEANUP_REMOVE_LABEL: VIDEO_CLEANUP_METHOD_REMOVE,
}
VIDEO_CLEANUP_METHOD_DESCRIPTIONS = {
    VIDEO_CLEANUP_FREEZE_LABEL: (
        "Replaces each selected black frame with the previous frame. Keeps video duration and timing unchanged."
    ),
    VIDEO_CLEANUP_REMOVE_LABEL: (
        "Deletes selected black frames and the matching audio slices. Useful before creating subtitles, "
        "but it shortens the timeline."
    ),
}
