from typing import TypedDict


class TtsSegment(TypedDict):
    text: str
    voice_label: str
    voice_short_name: str
    rate: str


class JobHistoryEntry(TypedDict):
    timestamp: str
    kind: str
    title: str
    detail: str
    input_path: str
    output_path: str
