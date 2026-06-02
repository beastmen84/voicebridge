from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from voicebridge.process_jobs import parse_worker_process_output, run_worker_process_job


class FakeProcess:
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


def test_parse_worker_process_output_detects_status_and_progress() -> None:
    status = parse_worker_process_output("STATUS: Loading model ")
    progress = parse_worker_process_output("PROGRESS: 42.5")
    invalid_progress = parse_worker_process_output("PROGRESS: unknown")
    plain = parse_worker_process_output("Training started")

    assert status.is_status is True
    assert status.status == "Loading model"
    assert status.progress_percent is None
    assert progress.is_progress is True
    assert progress.progress_percent == 42.5
    assert invalid_progress.is_progress is True
    assert invalid_progress.progress_percent is None
    assert plain.is_status is False
    assert plain.is_progress is False


def test_run_worker_process_job_reads_output_and_returns_recent_non_progress_lines(tmp_path: Path) -> None:
    process = FakeProcess(
        [
            "STATUS: Loading\n",
            "PROGRESS: 25\n",
            "\n",
            "Training step 1\n",
            "PROGRESS: invalid\n",
            "Training step 2\n",
        ],
        return_code=0,
    )
    popen_calls: list[tuple[list[str], dict[str, Any]]] = []
    events = []
    started_processes = []

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        popen_calls.append((command, kwargs))
        return process

    result = run_worker_process_job(
        ["python", "worker.py"],
        cwd=tmp_path,
        on_process_start=started_processes.append,
        on_output=events.append,
        popen_factory=fake_popen,
    )

    assert result.return_code == 0
    assert result.cancelled is False
    assert result.recent_output == ("STATUS: Loading", "Training step 1", "Training step 2")
    assert process.waited is True
    assert started_processes == [process]
    assert [event.line for event in events] == [
        "STATUS: Loading",
        "PROGRESS: 25",
        "Training step 1",
        "PROGRESS: invalid",
        "Training step 2",
    ]
    assert events[0].status == "Loading"
    assert events[1].progress_percent == 25.0
    assert events[3].is_progress is True
    assert events[3].progress_percent is None
    assert popen_calls == [
        (
            ["python", "worker.py"],
            {
                "cwd": str(tmp_path),
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
            },
        )
    ]


def test_run_worker_process_job_terminates_when_cancel_requested() -> None:
    process = FakeProcess(["Training step 1\n"], return_code=-15)
    events = []

    def fake_popen(command: list[str], **kwargs: Any) -> FakeProcess:
        return process

    result = run_worker_process_job(
        ["python", "worker.py"],
        on_output=events.append,
        should_cancel=lambda: bool(events),
        popen_factory=fake_popen,
    )

    assert result.cancelled is True
    assert result.return_code == -15
    assert result.recent_output == ("Training step 1",)
    assert process.terminated is True
