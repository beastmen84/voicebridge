import subprocess
from typing import Any

import voicebridge.pages.audio_cleanup as audio_cleanup_page
from voicebridge.pages.audio_cleanup import AudioCleanupWorkflowMixin


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


class FakeAudioCleanupWorkflow(AudioCleanupWorkflowMixin):
    def __init__(self) -> None:
        self.audio_cleanup_cancel_requested = False
        self.audio_cleanup_process = None
        self.progress_values: list[int] = []
        self.logs: list[str] = []

    def post(self, callback, *args):
        callback(*args)

    def update_audio_cleanup_progress_percent(self, percent: int) -> None:
        self.progress_values.append(percent)

    def append_audio_cleanup_log(self, message: str) -> None:
        self.logs.append(message)


def test_run_audio_cleanup_ffmpeg_process_maps_staged_progress_and_filters_progress_lines(monkeypatch) -> None:
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

    monkeypatch.setattr(audio_cleanup_page.subprocess, "Popen", fake_popen)

    workflow = FakeAudioCleanupWorkflow()
    return_code, recent_output = workflow.run_audio_cleanup_ffmpeg_process(
        ["ffmpeg", "-progress", "pipe:1"],
        10.0,
        progress_start=20.0,
        progress_end=80.0,
    )

    assert return_code == 0
    assert recent_output == ["encoder warning", "final warning"]
    assert workflow.progress_values == [50, 56]
    assert workflow.logs == ["encoder warning", "final warning"]
    assert workflow.audio_cleanup_process is process
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


def test_run_audio_cleanup_ffmpeg_process_preserves_cancel_termination(monkeypatch) -> None:
    process = FakeFfmpegProcess(["encoder warning\n"], return_code=-15)

    def fake_popen(command: list[str], **kwargs: Any) -> FakeFfmpegProcess:
        return process

    monkeypatch.setattr(audio_cleanup_page.subprocess, "Popen", fake_popen)

    workflow = FakeAudioCleanupWorkflow()
    workflow.audio_cleanup_cancel_requested = True
    return_code, recent_output = workflow.run_audio_cleanup_ffmpeg_process(["ffmpeg"], 10.0)

    assert return_code == -15
    assert recent_output == ["encoder warning"]
    assert process.terminated is True
