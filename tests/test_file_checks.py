from pathlib import Path

import pytest

from voicebridge.file_checks import (
    RequiredFileSpec,
    partial_download_files,
    required_file_issue,
    required_file_issues,
    required_files_ready,
    validate_output_path,
)
from voicebridge.runtime_errors import is_cuda_runtime_failure


def test_required_files_detect_missing_and_small_files(tmp_path: Path) -> None:
    root = tmp_path / "model"
    root.mkdir()
    (root / "config.json").write_bytes(b"{}")
    specs = (
        RequiredFileSpec("config.json", 8),
        RequiredFileSpec("model.bin", 16),
    )

    assert not required_files_ready(root, specs)
    assert required_file_issue(root / "config.json", min_bytes=8).startswith("incomplete")
    assert required_file_issues(root, specs) == [
        "config.json: incomplete (2 B < 8 B)",
        "model.bin: missing",
    ]


def test_partial_download_files_find_common_suffixes(tmp_path: Path) -> None:
    root = tmp_path / "models"
    nested = root / "nested"
    nested.mkdir(parents=True)
    complete = nested / "model.bin"
    partial = nested / "model.bin.part"
    complete.write_bytes(b"x")
    partial.write_bytes(b"x")

    assert partial_download_files(root) == [partial]


def test_validate_output_path_rejects_source_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "audio.mp3"
    source.write_bytes(b"x")

    with pytest.raises(ValueError, match="different from the source"):
        validate_output_path(source, source_path=source, expected_suffixes={".mp3"})


def test_validate_output_path_creates_parent_and_checks_suffix(tmp_path: Path) -> None:
    output = tmp_path / "new" / "audio.mp3"

    assert validate_output_path(output, expected_suffixes={".mp3"}) == output
    assert output.parent.is_dir()

    with pytest.raises(ValueError, match="extensions"):
        validate_output_path(tmp_path / "audio.wav", expected_suffixes={".mp3"})


def test_cuda_runtime_failure_detection() -> None:
    assert is_cuda_runtime_failure("RuntimeError: CUDA out of memory")
    assert is_cuda_runtime_failure("CUDA was selected, but this runtime cannot access an NVIDIA CUDA GPU.")
    assert not is_cuda_runtime_failure("The selected file does not exist.")
