from pathlib import Path

from voicebridge.tts_timeline import (
    load_local_tts_chunk_timeline,
    load_tts_timeline_for_audio,
    remove_tts_timeline,
    tts_timeline_path,
    write_local_tts_chunk_timeline,
    write_tts_timeline,
)


def test_write_and_load_tts_timeline(tmp_path: Path) -> None:
    audio_path = tmp_path / "output.mp3"
    audio_path.write_bytes(b"mp3")

    metadata_path = write_tts_timeline(
        audio_path,
        engine="edge",
        mode="multi",
        source_path=tmp_path / "input.txt",
        total_duration_seconds=2.0,
        blocks=[
            {
                "source_block_index": 1,
                "chunk_index": 1,
                "start_seconds": 0.0,
                "end_seconds": 2.0,
                "text": "Ciao mondo",
                "voice_short_name": "it-IT-IsabellaNeural",
            }
        ],
    )

    assert metadata_path == tts_timeline_path(audio_path)
    loaded = load_tts_timeline_for_audio(audio_path)

    assert loaded is not None
    assert loaded["engine"] == "edge"
    assert loaded["blocks"][0]["duration_seconds"] == 2.0
    assert loaded["blocks"][0]["voice_short_name"] == "it-IT-IsabellaNeural"


def test_remove_tts_timeline_deletes_sidecar(tmp_path: Path) -> None:
    audio_path = tmp_path / "output.mp3"
    sidecar = tts_timeline_path(audio_path)
    sidecar.write_text("{}", encoding="utf-8")

    remove_tts_timeline(audio_path)

    assert not sidecar.exists()


def test_write_and_load_local_tts_chunk_timeline(tmp_path: Path) -> None:
    metadata_path = tmp_path / "chunks.json"

    write_local_tts_chunk_timeline(
        metadata_path,
        audio_path=tmp_path / "output.wav",
        total_duration_seconds=1.5,
        chunks=[
            {
                "chunk_index": 2,
                "start_seconds": 0.25,
                "end_seconds": 1.5,
                "text": "Secondo chunk",
            }
        ],
    )

    chunks = load_local_tts_chunk_timeline(metadata_path)

    assert chunks == [
        {
            "id": "block-0001",
            "index": 1,
            "source_block_index": 1,
            "chunk_index": 2,
            "start_seconds": 0.25,
            "end_seconds": 1.5,
            "duration_seconds": 1.25,
            "text": "Secondo chunk",
        }
    ]
