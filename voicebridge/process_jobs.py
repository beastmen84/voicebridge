from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

STATUS_PREFIX = "STATUS: "
PROGRESS_PREFIX = "PROGRESS: "


@dataclass(frozen=True)
class WorkerProcessOutput:
    line: str
    is_status: bool = False
    status: str | None = None
    is_progress: bool = False
    progress_percent: float | None = None


@dataclass(frozen=True)
class WorkerProcessResult:
    return_code: int
    cancelled: bool
    recent_output: tuple[str, ...]


def parse_worker_process_output(line: str) -> WorkerProcessOutput:
    stripped_line = line.strip()
    is_status = stripped_line.startswith(STATUS_PREFIX)
    is_progress = stripped_line.startswith(PROGRESS_PREFIX)
    status = stripped_line.removeprefix(STATUS_PREFIX).strip() if is_status else None
    progress_percent = None
    if is_progress:
        try:
            progress_percent = float(stripped_line.removeprefix(PROGRESS_PREFIX).strip())
        except ValueError:
            progress_percent = None
    return WorkerProcessOutput(
        line=stripped_line,
        is_status=is_status,
        status=status,
        is_progress=is_progress,
        progress_percent=progress_percent,
    )


def run_worker_process_job(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    on_output: Callable[[WorkerProcessOutput], None] | None = None,
    on_process_start: Callable[[subprocess.Popen[str]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    recent_output_limit: int = 16,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> WorkerProcessResult:
    recent_output: list[str] = []
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = popen_factory(
        list(command),
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    if on_process_start is not None:
        on_process_start(process)
    if process.stdout is None:
        raise AssertionError

    for raw_line in process.stdout:
        line = raw_line.strip()
        if not line:
            continue
        output = parse_worker_process_output(line)
        if on_output is not None:
            on_output(output)
        if not output.is_progress:
            recent_output.append(line)
            if recent_output_limit > 0:
                recent_output = recent_output[-recent_output_limit:]
            else:
                recent_output.clear()
        if should_cancel is not None and should_cancel() and process.poll() is None:
            process.terminate()

    return_code = process.wait()
    return WorkerProcessResult(
        return_code=return_code,
        cancelled=should_cancel() if should_cancel is not None else False,
        recent_output=tuple(recent_output),
    )
