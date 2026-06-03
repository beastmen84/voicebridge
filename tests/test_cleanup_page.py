import subprocess
from typing import Any

import voicebridge.pages.cleanup as cleanup_page
from voicebridge.pages.cleanup import (
    VideoCleanupWorkflowMixin,
    conflicting_video_cleanup_change_frames,
    normalize_video_cleanup_change_plan,
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


class FakeVideoCleanupWorkflow(VideoCleanupWorkflowMixin):
    def __init__(self) -> None:
        self.cleanup_cancel_requested = False
        self.cleanup_process = None
        self.progress_values: list[float] = []
        self.logs: list[str] = []

    def post(self, callback, *args):
        callback(*args)

    def update_cleanup_progress_percent(self, percent: float) -> None:
        self.progress_values.append(percent)

    def append_cleanup_log(self, message: str) -> None:
        self.logs.append(message)


def test_run_cleanup_ffmpeg_process_maps_staged_progress_and_filters_progress_lines(monkeypatch) -> None:
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

    monkeypatch.setattr(cleanup_page.subprocess, "Popen", fake_popen)

    workflow = FakeVideoCleanupWorkflow()
    return_code, recent_output = workflow.run_cleanup_ffmpeg_process(
        ["ffmpeg", "-progress", "pipe:1"],
        10.0,
        progress_start=25.0,
        progress_end=75.0,
    )

    assert return_code == 0
    assert recent_output == ["encoder warning", "final warning"]
    assert workflow.progress_values == [50.0, 55.0]
    assert workflow.logs == ["encoder warning", "final warning"]
    assert workflow.cleanup_process is process
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


def test_run_cleanup_ffmpeg_process_preserves_cancel_termination(monkeypatch) -> None:
    process = FakeFfmpegProcess(["encoder warning\n"], return_code=-15)

    def fake_popen(command: list[str], **kwargs: Any) -> FakeFfmpegProcess:
        return process

    monkeypatch.setattr(cleanup_page.subprocess, "Popen", fake_popen)

    workflow = FakeVideoCleanupWorkflow()
    workflow.cleanup_cancel_requested = True
    return_code, recent_output = workflow.run_cleanup_ffmpeg_process(["ffmpeg"], 10.0)

    assert return_code == -15
    assert recent_output == ["encoder warning"]
    assert process.terminated is True


def test_cleanup_filmstrip_batches_do_not_mix_wrapped_frame_ranges() -> None:
    batches = VideoCleanupWorkflowMixin.cleanup_filmstrip_batches([8018, 8019, 8020, 8021, 0, 1, 2])

    assert batches == [[8018, 8019, 8020, 8021], [0, 1, 2]]


def test_pending_cleanup_action_requires_explicit_target() -> None:
    workflow = FakeVideoCleanupWorkflow()
    workflow.cleanup_marked_frame_numbers = {10, 20}
    workflow.cleanup_filmstrip_selected_frames = lambda: []

    assert workflow.cleanup_pending_action_frames() == []


def test_pending_cleanup_action_uses_selected_marked_frame() -> None:
    workflow = FakeVideoCleanupWorkflow()
    workflow.cleanup_marked_frame_numbers = {10, 20}
    workflow.cleanup_filmstrip_selected_frames = lambda: [20, 30]

    assert workflow.cleanup_pending_action_frames() == [20]


def test_normalize_video_cleanup_change_plan_sorts_by_original_frame() -> None:
    changes = [
        {"action": "freeze", "frames": [30, 10]},
        {"action": "remove", "frames": [20]},
    ]

    assert normalize_video_cleanup_change_plan(changes) == [
        {"action": "freeze", "frames": [10]},
        {"action": "remove", "frames": [20]},
        {"action": "freeze", "frames": [30]},
    ]


def test_normalize_video_cleanup_change_plan_deduplicates_same_action_only() -> None:
    changes = [
        {"action": "freeze", "frames": [12, 14]},
        {"action": "freeze", "frames": [12]},
        {"action": "freeze", "frames": ["bad", 0, -1]},
    ]

    assert normalize_video_cleanup_change_plan(changes) == [
        {"action": "freeze", "frames": [12]},
        {"action": "freeze", "frames": [14]},
    ]


def test_conflicting_video_cleanup_change_frames_detects_mixed_actions() -> None:
    changes = [
        {"action": "freeze", "frames": [12, 14]},
        {"action": "remove", "frames": [12]},
        {"action": "remove", "frames": [14]},
        {"action": "remove", "frames": [14]},
    ]

    assert conflicting_video_cleanup_change_frames(changes) == {
        12: {"freeze", "remove"},
        14: {"freeze", "remove"},
    }


def test_selected_cleanup_frame_numbers_excludes_queued_frames() -> None:
    workflow = FakeVideoCleanupWorkflow()
    workflow.cleanup_marked_frame_numbers = {10, 20}
    workflow.cleanup_changes = [{"action": "freeze", "frames": ["10"]}]

    assert workflow.selected_cleanup_frame_numbers() == [20]


def test_cleanup_queued_actions_for_frame_handles_string_and_int_frames() -> None:
    workflow = FakeVideoCleanupWorkflow()
    workflow.cleanup_changes = [
        {"action": "freeze", "frames": ["10"]},
        {"action": "remove", "frames": [20]},
    ]

    assert workflow.cleanup_queued_actions_for_frame(10) == ["freeze"]
    assert workflow.cleanup_queued_actions_for_frame(20) == ["remove"]
    assert workflow.cleanup_queued_actions_for_frame(30) == []
