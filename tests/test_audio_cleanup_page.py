import subprocess
from pathlib import Path
from typing import Any

import voicebridge.pages.audio_cleanup as audio_cleanup_page
from voicebridge.media_tools import AUDIO_CLEANUP_FADE, AUDIO_CLEANUP_SILENCE
from voicebridge.pages.audio_cleanup import (
    AudioCleanupWorkflowMixin,
    audio_cleanup_ranges_overlap,
    audio_cleanup_stage_output_path,
    conflicting_audio_cleanup_change_indexes,
)


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
        self.succeeded_jobs: list[tuple[str, int, str]] = []
        self.failed_jobs: list[str] = []
        self.finished = False

    def post(self, callback, *args):
        callback(*args)

    def update_audio_cleanup_progress_percent(self, percent: int) -> None:
        self.progress_values.append(percent)

    def append_audio_cleanup_log(self, message: str) -> None:
        self.logs.append(message)

    def audio_cleanup_job_succeeded(self, output_path: str, change_count: int, timeline_path: str = "") -> None:
        self.succeeded_jobs.append((output_path, change_count, timeline_path))

    def audio_cleanup_job_failed(self, message: str) -> None:
        self.failed_jobs.append(message)

    def finish_audio_cleanup_job(self) -> None:
        self.finished = True


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


def test_run_audio_cleanup_ffmpeg_process_terminates_cancelled_progress_only_process(monkeypatch) -> None:
    process = FakeFfmpegProcess(["out_time_us=1000000\n", "progress=continue\n"], return_code=-15)

    def fake_popen(command: list[str], **kwargs: Any) -> FakeFfmpegProcess:
        return process

    monkeypatch.setattr(audio_cleanup_page.subprocess, "Popen", fake_popen)

    workflow = FakeAudioCleanupWorkflow()
    workflow.audio_cleanup_cancel_requested = True
    return_code, recent_output = workflow.run_audio_cleanup_ffmpeg_process(["ffmpeg"], 10.0)

    assert return_code == -15
    assert recent_output == []
    assert process.terminated is True


def test_audio_cleanup_stage_output_path_uses_lossless_flac(tmp_path: Path) -> None:
    assert audio_cleanup_stage_output_path(tmp_path, 3) == tmp_path / "stage-0003.flac"


def test_audio_cleanup_ranges_overlap_allows_adjacent_ranges() -> None:
    assert audio_cleanup_ranges_overlap(1.0, 2.0, 1.5, 2.5) is True
    assert audio_cleanup_ranges_overlap(1.0, 2.0, 2.0, 3.0) is False
    assert audio_cleanup_ranges_overlap(2.0, 3.0, 1.0, 2.0) is False


def test_conflicting_audio_cleanup_change_indexes_detects_any_overlapping_action() -> None:
    changes = [
        {
            "action": AUDIO_CLEANUP_SILENCE,
            "source_start_seconds": 1.0,
            "source_end_seconds": 2.0,
        },
        {
            "action": AUDIO_CLEANUP_FADE,
            "source_start_seconds": 1.8,
            "source_end_seconds": 2.5,
        },
    ]

    assert conflicting_audio_cleanup_change_indexes(changes) == (0, 1)


def test_conflicting_audio_cleanup_change_indexes_allows_adjacent_ranges() -> None:
    changes = [
        {
            "action": AUDIO_CLEANUP_SILENCE,
            "source_start_seconds": 1.0,
            "source_end_seconds": 2.0,
        },
        {
            "action": AUDIO_CLEANUP_FADE,
            "source_start_seconds": 2.0,
            "source_end_seconds": 2.5,
        },
    ]

    assert conflicting_audio_cleanup_change_indexes(changes) is None


def test_audio_cleanup_change_overlapping_range_uses_source_ranges() -> None:
    workflow = FakeAudioCleanupWorkflow()
    workflow.audio_cleanup_changes = [
        {
            "action": AUDIO_CLEANUP_SILENCE,
            "source_start_seconds": 3.0,
            "source_end_seconds": 4.0,
        }
    ]

    overlap = workflow.audio_cleanup_change_overlapping_range(3.5, 4.5)

    assert overlap == (1, workflow.audio_cleanup_changes[0])
    assert workflow.audio_cleanup_change_overlapping_range(4.0, 4.5) is None


def test_audio_cleanup_worker_uses_lossless_intermediate_stage(tmp_path: Path) -> None:
    input_path = tmp_path / "input.mp3"
    output_path = tmp_path / "output.mp3"
    input_path.write_bytes(b"input")
    commands: list[list[str]] = []

    workflow = FakeAudioCleanupWorkflow()

    def fake_run(command, duration_seconds=None, *, progress_start=0.0, progress_end=99.0):
        commands.append([str(part) for part in command])
        Path(command[-1]).write_bytes(b"stage")
        return 0, []

    workflow.run_audio_cleanup_ffmpeg_process = fake_run
    workflow.audio_cleanup_worker(
        "ffmpeg",
        str(input_path),
        str(output_path),
        [
            {
                "action": AUDIO_CLEANUP_SILENCE,
                "source_start_seconds": 0.2,
                "source_end_seconds": 0.4,
                "start_seconds": 0.2,
                "end_seconds": 0.4,
            },
            {
                "action": AUDIO_CLEANUP_FADE,
                "source_start_seconds": 0.6,
                "source_end_seconds": 0.8,
                "start_seconds": 0.6,
                "end_seconds": 0.8,
            },
        ],
        1.0,
    )

    assert [Path(command[-1]).suffix for command in commands] == [".flac", ".mp3"]
    assert output_path.read_bytes() == b"stage"
    assert workflow.succeeded_jobs == [(str(output_path), 2, "")]
    assert workflow.failed_jobs == []
    assert workflow.finished is True
