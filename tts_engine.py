import os
from pathlib import Path

import edge_tts


class TtsCancelled(Exception):
    pass


async def generate_audio(text, voice, save_path, rate, should_cancel=None):
    tts = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
    )
    if should_cancel is None:
        await tts.save(save_path)
        return

    with open(save_path, "wb") as audio_file:
        async for chunk in tts.stream():
            if should_cancel():
                raise TtsCancelled()
            if chunk.get("type") == "audio":
                audio_file.write(chunk.get("data", b""))
        if should_cancel():
            raise TtsCancelled()


def suggested_output_path(input_path):
    return str(Path(input_path).with_suffix(".mp3"))


def ensure_mp3_suffix(path):
    root, ext = os.path.splitext(path)
    if ext.lower() == ".mp3":
        return path
    return f"{root or path}.mp3"
