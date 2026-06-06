import subprocess
from typing import Any

import voicebridge.pages.subtitles as subtitles_page
from voicebridge.pages.subtitles import SubtitlesWorkflowMixin


class FakeFfmpegProcess:
    def __init__(self, lines: list[str], return_code: int = 0) -> None:
        self.stdout = iter(lines)
        self.return_code = return_code
        self.terminated = False
        self.waited = False

    def poll(self) -> int | None:
        return self.return_code if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self) -> int:
        self.waited = True
        return self.return_code


class FakeWidget:
    def __init__(self) -> None:
        self.enabled = None

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakeButton(FakeWidget):
    def __init__(self, object_name: str = "PrimaryButton") -> None:
        super().__init__()
        self.name = object_name

    def objectName(self) -> str:
        return self.name

    def setObjectName(self, name: str) -> None:
        self.name = name

    def style(self):
        return self

    def unpolish(self, _widget) -> None:
        return

    def polish(self, _widget) -> None:
        return


class FakePicker(FakeWidget):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._text = text

    def text(self) -> str:
        return self._text


class FakeCheckBox(FakeWidget):
    def __init__(self, checked: bool = False) -> None:
        super().__init__()
        self.checked = checked

    def isChecked(self) -> bool:
        return self.checked


class FakeSubtitlesWorkflow(SubtitlesWorkflowMixin):
    def __init__(self) -> None:
        self.video_cancel_requested = False
        self.video_process = None
        self.progress_values: list[int] = []
        self.logs: list[str] = []

    def post(self, callback, *args):
        callback(*args)

    def update_video_progress_percent(self, percent: int) -> None:
        self.progress_values.append(percent)

    def append_video_log(self, message: str) -> None:
        self.logs.append(message)


class FakeSubtitleButtonWorkflow(SubtitlesWorkflowMixin):
    def __init__(self, media_path: str = "", srt_path: str = "") -> None:
        self.is_converting = False
        self.is_stt_running = False
        self.is_audio_cleanup_running = False
        self.is_cleanup_running = False
        self.is_video_running = False
        self.video_cancel_requested = False
        self.video_last_output_path = ""
        self.video_start_button = FakeButton()
        self.video_preview_button = FakeButton("")
        self.video_cancel_button = FakeButton("")
        self.video_open_output_button = FakeButton("")
        self.video_open_folder_button = FakeButton("")
        self.video_media_picker = FakePicker(media_path)
        self.video_srt_picker = FakePicker(srt_path)
        self.video_output_picker = FakePicker("")
        self.video_embed_mode_button = FakeWidget()
        self.video_burn_mode_button = FakeWidget()
        self.video_quality_combo = FakeWidget()
        self.video_font_size_spin = FakeWidget()
        self.video_outline_spin = FakeWidget()
        self.video_shadow_spin = FakeWidget()
        self.video_margin_spin = FakeWidget()
        self.video_position_combo = FakeWidget()
        self.video_text_color_combo = FakeWidget()
        self.video_outline_color_combo = FakeWidget()
        self.video_background_box_check = FakeCheckBox(False)
        self.video_box_color_combo = FakeWidget()

    def video_subtitle_mode_key(self) -> str:
        return "embed"

    def update_navigation_state(self) -> None:
        return


def test_run_ffmpeg_process_uses_ffmpeg_progress_helpers(monkeypatch) -> None:
    process = FakeFfmpegProcess(
        [
            "out_time_us=5000000\n",
            "progress=continue\n",
            "encoder warning\n",
            "out_time=00:00:06.000000\n",
            "final warning\n",
        ],
        return_code=0,
    )
    popen_calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_popen(command: list[str], **kwargs: Any) -> FakeFfmpegProcess:
        popen_calls.append((command, kwargs))
        return process

    monkeypatch.setattr(subtitles_page.subprocess, "Popen", fake_popen)

    workflow = FakeSubtitlesWorkflow()
    return_code, recent_output = workflow.run_ffmpeg_process(["ffmpeg", "-progress", "pipe:1"], 10.0)

    assert return_code == 0
    assert recent_output == ["encoder warning", "final warning"]
    assert workflow.progress_values == [50, 60]
    assert workflow.logs == ["encoder warning", "final warning"]
    assert workflow.video_process is process
    assert process.waited is True
    assert popen_calls == [
        (
            ["ffmpeg", "-progress", "pipe:1"],
            {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
            },
        )
    ]


def test_run_ffmpeg_process_preserves_cancel_termination(monkeypatch) -> None:
    process = FakeFfmpegProcess(["encoder warning\n"], return_code=-15)

    def fake_popen(command: list[str], **kwargs: Any) -> FakeFfmpegProcess:
        return process

    monkeypatch.setattr(subtitles_page.subprocess, "Popen", fake_popen)

    workflow = FakeSubtitlesWorkflow()
    workflow.video_cancel_requested = True
    return_code, recent_output = workflow.run_ffmpeg_process(["ffmpeg"], 10.0)

    assert return_code == -15
    assert recent_output == ["encoder warning"]
    assert process.terminated is True


def test_create_video_button_requires_video_and_srt_files(tmp_path) -> None:
    workflow = FakeSubtitleButtonWorkflow()

    workflow.update_video_subtitle_button_state()

    assert workflow.video_start_button.enabled is False
    assert workflow.video_start_button.objectName() == ""

    media_path = tmp_path / "input.mp4"
    srt_path = tmp_path / "input.srt"
    media_path.write_bytes(b"video")
    srt_path.write_text("1\n00:00:00,000 --> 00:00:01,000\nText\n", encoding="utf-8")
    workflow = FakeSubtitleButtonWorkflow(str(media_path), str(srt_path))

    workflow.update_video_subtitle_button_state()

    assert workflow.video_start_button.enabled is True
    assert workflow.video_start_button.objectName() == "PrimaryButton"
