import re

TTS_MAX_CHUNK_CHARS = 240
TTS_MIN_STANDALONE_CHARS = 40
TTS_TERMINAL_FULL_STOP = "."

NON_SENTENCE_ABBREVIATIONS = {
    "arch.",
    "art.",
    "avv.",
    "cap.",
    "dott.",
    "dr.",
    "ecc.",
    "es.",
    "fig.",
    "ing.",
    "n.",
    "pag.",
    "prof.",
    "sig.",
    "sig.ra",
    "sig.na",
}


def readable_email(match: re.Match[str]) -> str:
    return match.group(0).replace("@", " at ").replace(".", " ")


def normalize_tts_text(text: str) -> str:
    text = text.replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = text.replace("\u2026", ", ").replace("...", ", ")
    text = re.sub(r"https?://\S+|www\.\S+", " link ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", readable_email, text)
    text = re.sub(
        r"\b([A-Za-z0-9_-]+)\.(txt|pdf|docx?|mp4|mp3|wav|m4a|aac|flac|ogg|srt|md)\b",
        r"\1 \2",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(?m)^\s*(\d{1,3})[.)]\s+", r"\1, ", text)
    text = re.sub(r"(?m)^\s*(?:[-*]|\u2022)\s+", "", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:!?])([^\s,.;:!?])", r"\1 \2", text)
    text = re.sub(r"(?<!\d)\.([^\s,.;:!?\d])", r". \1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_sentence_boundary(text: str, punctuation_index: int) -> bool:
    if text[punctuation_index] == ".":
        previous_char = text[punctuation_index - 1] if punctuation_index > 0 else ""
        next_char = text[punctuation_index + 1] if punctuation_index + 1 < len(text) else ""
        if previous_char.isdigit() and next_char.isdigit():
            return False

    prefix = text[: punctuation_index + 1].rstrip()
    token = prefix.split()[-1].casefold() if prefix.split() else ""
    return token not in NON_SENTENCE_ABBREVIATIONS


def sentence_fragments_for_tts(text: str) -> list[str]:
    fragments = []
    start = 0
    for match in re.finditer(r"[.!?](?:[\"')\]]+)?(?=\s+|$)", text):
        if not is_sentence_boundary(text, match.start()):
            continue
        end = match.end()
        fragment = text[start:end].strip()
        if fragment:
            fragments.append(fragment)
        start = end
        while start < len(text) and text[start].isspace():
            start += 1
    tail = text[start:].strip()
    if tail:
        fragments.append(tail)
    return fragments


def split_words_for_tts(text: str, max_chars: int = TTS_MAX_CHUNK_CHARS) -> list[str]:
    chunks = []
    current = []
    current_length = 0
    for word in text.split():
        candidate_length = len(word) if not current else current_length + 1 + len(word)
        if current and candidate_length > max_chars:
            chunks.append(" ".join(current))
            current = [word]
            current_length = len(word)
        else:
            current.append(word)
            current_length = candidate_length
    if current:
        chunks.append(" ".join(current))
    return chunks


def pack_text_fragments_for_tts(fragments: list[str], max_chars: int = TTS_MAX_CHUNK_CHARS) -> list[str]:
    chunks = []
    current = ""
    for fragment in fragments:
        clean_fragment = fragment.strip()
        if not clean_fragment:
            continue
        if len(clean_fragment) <= max_chars:
            candidates = [clean_fragment]
        else:
            candidates = split_words_for_tts(clean_fragment, max_chars)
        for candidate in candidates:
            joined = candidate if not current else f"{current} {candidate}"
            if current and len(joined) > max_chars:
                chunks.append(current)
                current = candidate
            else:
                current = joined
    if current:
        chunks.append(current)
    return chunks


def merge_short_tts_chunks(
    chunks: list[str],
    min_chars: int = TTS_MIN_STANDALONE_CHARS,
    max_chars: int = TTS_MAX_CHUNK_CHARS,
) -> list[str]:
    merged_chunks = []
    current = ""
    for chunk in chunks:
        if not current:
            current = chunk
            continue
        joined = f"{current} {chunk}"
        if len(joined) <= max_chars and (len(current) < min_chars or len(chunk) < min_chars):
            current = joined
            continue
        merged_chunks.append(current)
        current = chunk
    if current:
        merged_chunks.append(current)
    return merged_chunks


def split_tts_text_for_tts(text: str, max_chars: int = TTS_MAX_CHUNK_CHARS) -> list[str]:
    text = normalize_tts_text(text)
    if not text:
        return []
    chunks = []
    for sentence in sentence_fragments_for_tts(text):
        if len(sentence) <= max_chars:
            chunks.append(sentence)
        else:
            chunks.extend(pack_text_fragments_for_tts(re.split(r"(?<=[,;:])\s+", sentence), max_chars))
    return merge_short_tts_chunks(chunks, max_chars=max_chars)


def prepare_tts_chunk_for_generation(text: str) -> str:
    text = text.strip()
    text = re.sub(r"!\s+(?=\S)", "; ", text)
    if text.endswith(TTS_TERMINAL_FULL_STOP):
        return f"{text[:-1].rstrip()};"
    return text
