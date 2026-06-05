import struct
from pathlib import Path
from types import SimpleNamespace

from voicebridge.modeling_clip_recording_dialog import (
    ModelingClipRecordingDialog,
    build_recording_quality_details,
    build_recording_status_message,
)
from voicebridge.wav_writer import prepare_voice_reference_pcm


def pcm16_bytes(samples: list[int]) -> bytes:
    return b"".join(struct.pack("<h", sample) for sample in samples)


def test_estimated_target_seconds_caps_to_maximum() -> None:
    long_text = "word " * 400

    assert ModelingClipRecordingDialog.estimated_target_seconds("", 60) == 60
    assert ModelingClipRecordingDialog.estimated_target_seconds("short clip", 60) == 12
    assert ModelingClipRecordingDialog.estimated_target_seconds(long_text, 60) == 60


def test_modeling_prompt_display_uses_reading_breaks() -> None:
    display_text = ModelingClipRecordingDialog.display_prompt_text(
        "Prima frase. Seconda frase? Terza frase; poi chiudo.",
        60,
    )

    assert display_text.split("\n\n") == [
        "Prima frase.",
        "Seconda frase?",
        "Terza frase;",
        "poi chiudo.",
    ]


def test_modeling_recording_status_reports_auto_stop() -> None:
    recording = prepare_voice_reference_pcm(pcm16_bytes([5000] * 300), sample_rate=10, channel_count=1)

    status = build_recording_status_message(recording, auto_stopped=True)

    assert "Maximum clip length reached" in status


def test_modeling_recording_quality_details_include_snr() -> None:
    recording = prepare_voice_reference_pcm(pcm16_bytes([100] * 20 + [5000] * 30 + [100] * 20), 10, 1)

    details = build_recording_quality_details(recording, sample_rate=10, channel_count=1)

    assert "Estimated SNR:" in details


def test_modeling_preview_recording_path_is_not_final_clip_path(tmp_path: Path) -> None:
    output_path = tmp_path / "clips" / "clip-a.wav"

    preview_path = ModelingClipRecordingDialog.preview_recording_path(output_path)

    assert preview_path != output_path
    assert preview_path.parent == output_path.parent
    assert preview_path.suffix == output_path.suffix
    assert preview_path.name.startswith(".clip-a.preview-")


def test_modeling_cancel_removes_preview_without_touching_final_clip(tmp_path: Path) -> None:
    final_path = tmp_path / "clip.wav"
    preview_path = tmp_path / ".clip.preview-test.wav"
    final_path.write_bytes(b"final")
    preview_path.write_bytes(b"preview")
    dialog = SimpleNamespace(_preview_path=preview_path, _kept_recording=False)

    ModelingClipRecordingDialog.cleanup_preview_file(dialog)

    assert final_path.read_bytes() == b"final"
    assert not preview_path.exists()
    assert dialog._preview_path is None


def test_modeling_keep_moves_preview_to_final_clip(tmp_path: Path) -> None:
    final_path = tmp_path / "clips" / "clip.wav"
    preview_path = tmp_path / "clips" / ".clip.preview-test.wav"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_bytes(b"preview")
    accepted = []
    errors = []
    dialog = SimpleNamespace(
        output_path=final_path,
        _preview_path=preview_path,
        _kept_recording=False,
        recording_path=None,
        accept=lambda: accepted.append(True),
        show_recording_error=errors.append,
    )

    ModelingClipRecordingDialog.keep_recording(dialog)

    assert final_path.read_bytes() == b"preview"
    assert not preview_path.exists()
    assert dialog.recording_path == final_path
    assert dialog._preview_path == final_path
    assert dialog._kept_recording is True
    assert accepted == [True]
    assert errors == []


def test_modeling_keep_releases_preview_player_before_moving_clip() -> None:
    events = []

    class FakeMediaPlayer:
        def stop(self) -> None:
            events.append("stop")

        def setSource(self, _source) -> None:
            events.append("clear-source")

    class FakeParent:
        def mkdir(self, *, parents: bool, exist_ok: bool) -> None:
            assert parents is True
            assert exist_ok is True
            events.append("mkdir")

    class FakeOutputPath:
        parent = FakeParent()

    class FakePreviewPath:
        def is_file(self) -> bool:
            return True

        def replace(self, _target) -> None:
            events.append("replace")

    accepted = []
    errors = []
    output_path = FakeOutputPath()
    dialog = SimpleNamespace(
        output_path=output_path,
        _preview_path=FakePreviewPath(),
        _kept_recording=False,
        recording_path=None,
        media_player=FakeMediaPlayer(),
        accept=lambda: accepted.append(True),
        show_recording_error=errors.append,
    )

    ModelingClipRecordingDialog.keep_recording(dialog)

    assert events == ["stop", "clear-source", "mkdir", "replace"]
    assert dialog.recording_path is output_path
    assert dialog._preview_path is output_path
    assert dialog._kept_recording is True
    assert accepted == [True]
    assert errors == []
