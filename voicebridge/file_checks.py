import shutil
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RequiredFileSpec:
    filename: str
    min_bytes: int = 1


def format_bytes(value: int) -> str:
    size = max(0.0, float(value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


def required_file_issue(path: str | Path, *, min_bytes: int = 1) -> str:
    file_path = Path(path)
    if not file_path.is_file():
        return "missing"
    try:
        size = file_path.stat().st_size
    except OSError as exc:
        return f"unreadable ({exc})"
    if size < min_bytes:
        return f"incomplete ({format_bytes(size)} < {format_bytes(min_bytes)})"
    return ""


def required_file_issues(root: str | Path, specs: tuple[RequiredFileSpec, ...]) -> list[str]:
    base = Path(root)
    issues = []
    for spec in specs:
        path = base / spec.filename
        issue = required_file_issue(path, min_bytes=spec.min_bytes)
        if issue:
            issues.append(f"{spec.filename}: {issue}")
    return issues


def required_files_ready(root: str | Path, specs: tuple[RequiredFileSpec, ...]) -> bool:
    return not required_file_issues(root, specs)


def partial_download_files(root: str | Path) -> list[Path]:
    base = Path(root)
    if not base.is_dir():
        return []
    patterns = ("*.part", "*.tmp", "*.download", "*.incomplete")
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(path for path in base.rglob(pattern) if path.is_file())
    return sorted(matches)


def existing_parent(path: str | Path) -> Path:
    current = Path(path).expanduser()
    if current.suffix or not str(current).endswith(("/", "\\")):
        current = current.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def available_disk_bytes(path: str | Path) -> int:
    parent = existing_parent(path)
    try:
        return shutil.disk_usage(parent).free
    except OSError:
        return 0


def ensure_free_space(path: str | Path, required_bytes: int, label: str = "operation") -> None:
    if required_bytes <= 0:
        return
    free_bytes = available_disk_bytes(path)
    if free_bytes and free_bytes < required_bytes:
        raise ValueError(
            f"Not enough free disk space for {label}. "
            f"Required: {format_bytes(required_bytes)}; available: {format_bytes(free_bytes)}."
        )


def validate_existing_file(path: str | Path, label: str, *, min_bytes: int = 1) -> Path:
    file_path = Path(path).expanduser()
    issue = required_file_issue(file_path, min_bytes=min_bytes)
    if issue:
        raise ValueError(f"{label} is {issue}: {file_path}")
    return file_path


def validate_output_path(
    output_path: str | Path,
    *,
    source_path: str | Path | None = None,
    expected_suffixes: set[str] | None = None,
    create_parent: bool = True,
) -> Path:
    path = Path(output_path).expanduser()
    if not str(path).strip():
        raise ValueError("Choose an output path.")
    if path.exists() and path.is_dir():
        raise ValueError(f"Output path points to a folder, not a file: {path}")
    if expected_suffixes and path.suffix.lower() not in expected_suffixes:
        allowed = ", ".join(sorted(expected_suffixes))
        raise ValueError(f"Output file must use one of these extensions: {allowed}")
    if source_path:
        source = Path(source_path).expanduser()
        try:
            if path.resolve() == source.resolve():
                raise ValueError("Choose an output path different from the source file.")
        except OSError:
            pass

    parent = path.parent
    try:
        if create_parent:
            parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Could not create the output folder:\n{parent}\n\n{exc}") from exc
    if not parent.is_dir():
        raise ValueError(f"The output folder does not exist: {parent}")

    test_path = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".voicebridge-write-test-",
            suffix=".tmp",
            dir=str(parent),
            delete=False,
        ) as temp_file:
            test_path = Path(temp_file.name)
            temp_file.write(b"ok")
    except OSError as exc:
        raise ValueError(f"The output folder is not writable:\n{parent}\n\n{exc}") from exc
    finally:
        if test_path is not None:
            with suppress(OSError):
                test_path.unlink(missing_ok=True)
    return path
