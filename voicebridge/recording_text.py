RECORDING_TEXT_BREAK_MARKS = ".!?;؟؛。！？।"


def format_recording_text_for_display(text: str) -> str:
    normalized_text = " ".join(text.split())
    lines: list[str] = []
    current: list[str] = []
    for character in normalized_text:
        current.append(character)
        if character in RECORDING_TEXT_BREAK_MARKS:
            line = "".join(current).strip()
            if line:
                lines.append(line)
            current = []

    remainder = "".join(current).strip()
    if remainder:
        lines.append(remainder)
    return "\n\n".join(lines)
