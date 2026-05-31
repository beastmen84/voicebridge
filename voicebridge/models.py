from typing import NotRequired, TypedDict


class TtsSegment(TypedDict):
    text: str
    voice_label: str
    voice_short_name: NotRequired[str]
    rate: NotRequired[str]
    voice_profile_id: NotRequired[str]
    language_code: NotRequired[str]


class JobHistoryEntry(TypedDict):
    timestamp: str
    kind: str
    title: str
    detail: str
    input_path: str
    output_path: str
