from pathlib import Path

from voicebridge.tts_timeline import (
    load_local_tts_chunk_timeline,
    load_tts_timeline_for_audio,
    remove_tts_timeline,
    transform_tts_timeline_blocks_for_cleanup,
    tts_timeline_path,
    write_audio_cleanup_timeline,
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


def test_cut_timeline_shifts_following_blocks_and_marks_partial_cut() -> None:
    blocks = [
        {"start_seconds": 0.0, "end_seconds": 2.0, "text": "A"},
        {"start_seconds": 2.0, "end_seconds": 5.0, "text": "B"},
        {"start_seconds": 5.0, "end_seconds": 7.0, "text": "C"},
    ]

    updated, removed = transform_tts_timeline_blocks_for_cleanup(
        blocks,
        action="remove",
        start_seconds=3.0,
        end_seconds=4.0,
    )

    assert removed == []
    assert updated[0]["start_seconds"] == 0.0
    assert updated[0]["end_seconds"] == 2.0
    assert updated[1]["start_seconds"] == 2.0
    assert updated[1]["end_seconds"] == 4.0
    assert updated[1]["contains_cut"] is True
    assert updated[2]["start_seconds"] == 4.0
    assert updated[2]["end_seconds"] == 6.0


def test_cut_timeline_removes_fully_cut_blocks() -> None:
    blocks = [
        {"start_seconds": 0.0, "end_seconds": 1.0, "text": "A"},
        {"start_seconds": 1.0, "end_seconds": 2.0, "text": "B"},
        {"start_seconds": 2.0, "end_seconds": 3.0, "text": "C"},
    ]

    updated, removed = transform_tts_timeline_blocks_for_cleanup(
        blocks,
        action="remove",
        start_seconds=1.0,
        end_seconds=2.0,
    )

    assert [block["text"] for block in updated] == ["A", "C"]
    assert updated[1]["start_seconds"] == 1.0
    assert updated[1]["end_seconds"] == 2.0
    assert [block["text"] for block in removed] == ["B"]


def test_write_audio_cleanup_timeline_preserves_text_and_records_edit(tmp_path: Path) -> None:
    input_audio = tmp_path / "input.mp3"
    output_audio = tmp_path / "output.mp3"
    input_audio.write_bytes(b"input")
    output_audio.write_bytes(b"output")
    write_tts_timeline(
        input_audio,
        engine="local",
        mode="single",
        total_duration_seconds=3.0,
        blocks=[
            {
                "start_seconds": 0.0,
                "end_seconds": 3.0,
                "text": "Testo originale da non riscrivere",
            }
        ],
    )

    timeline_path = write_audio_cleanup_timeline(
        input_audio,
        output_audio,
        action="remove",
        start_seconds=1.0,
        end_seconds=1.5,
        total_duration_seconds=2.5,
    )
    loaded = load_tts_timeline_for_audio(output_audio)

    assert timeline_path == tts_timeline_path(output_audio)
    assert loaded is not None
    assert loaded["total_duration_seconds"] == 2.5
    assert loaded["blocks"][0]["text"] == "Testo originale da non riscrivere"
    assert loaded["blocks"][0]["contains_cut"] is True
    assert loaded["edits"][0]["action"] == "remove"
    assert loaded["edits"][0]["text_policy"].startswith("Block text is preserved")
