from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def hidden_process_startupinfo() -> Any:
    startupinfo_class = getattr(subprocess, "STARTUPINFO", None)
    startf_use_show_window = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    sw_hide = getattr(subprocess, "SW_HIDE", 0)
    if startupinfo_class is None or not startf_use_show_window:
        return None
    startupinfo = startupinfo_class()
    startupinfo.dwFlags |= startf_use_show_window
    startupinfo.wShowWindow = sw_hide
    return startupinfo


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
    stdin: Any = subprocess.DEVNULL,
    on_output: Callable[[WorkerProcessOutput], None] | None = None,
    on_process_start: Callable[[subprocess.Popen[str]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    include_in_recent_output: Callable[[WorkerProcessOutput], bool] | None = None,
    recent_output_limit: int = 16,
    popen_factory: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> WorkerProcessResult:
    recent_output: list[str] = []
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = popen_factory(
        list(command),
        cwd=str(cwd) if cwd is not None else None,
        stdin=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        startupinfo=hidden_process_startupinfo(),
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
        include_output = (
            include_in_recent_output(output) if include_in_recent_output is not None else not output.is_progress
        )
        if include_output:
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
