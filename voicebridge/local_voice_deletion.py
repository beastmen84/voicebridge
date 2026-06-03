import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from voicebridge.json_schemas import (
    MODELING_DATASET_EXPORT_JSON_KIND,
    VOICE_MODELING_JOB_CONFIG_JSON_KIND,
    app_json_version_supported,
)
from voicebridge.modeling_datasets import (
    ModelingDataset,
    modeling_dataset_dir,
    modeling_dataset_exports_root,
    modeling_datasets_for_profile_id,
    modeling_datasets_root,
)
from voicebridge.voice_modeling import VOICE_MODELING_JOB_CONFIG, voice_modeling_outputs_root
from voicebridge.voice_profiles import (
    VOICE_PROFILE_MODELING,
    VoiceProfile,
    delete_voice_profile_audio_files,
)


@dataclass(frozen=True)
class LinkedDeletionAsset:
    kind: str
    label: str
    path: Path


@dataclass(frozen=True)
class VoiceProfileDeletionPlan:
    profile_id: str
    profile_name: str
    linked_datasets: tuple[ModelingDataset, ...]
    safe_assets: tuple[LinkedDeletionAsset, ...]
    unsafe_assets: tuple[LinkedDeletionAsset, ...]
    recorded_clip_count: int
    guided_prompt_history_count: int
    exported_dataset_count: int
    trained_model_output_count: int

    @property
    def has_linked_modeling_work(self) -> bool:
        return bool(self.linked_datasets or self.safe_assets or self.unsafe_assets)


@dataclass(frozen=True)
class VoiceProfileDeletionResult:
    voice_profiles: list[VoiceProfile]
    modeling_datasets: list[ModelingDataset]
    removed_modeling_dataset_count: int
    deleted_paths: tuple[Path, ...]
    failed_paths: tuple[Path, ...]
    unsafe_assets: tuple[LinkedDeletionAsset, ...]

    @property
    def modeling_datasets_changed(self) -> bool:
        return self.removed_modeling_dataset_count > 0


def build_voice_profile_deletion_plan(
    profile: VoiceProfile,
    modeling_datasets: list[ModelingDataset],
) -> VoiceProfileDeletionPlan:
    linked_datasets = (
        tuple(modeling_datasets_for_profile_id(modeling_datasets, profile["id"]))
        if profile.get("profile_type") == VOICE_PROFILE_MODELING
        else ()
    )
    dataset_ids = {dataset["id"] for dataset in linked_datasets}
    recorded_clip_count = sum(len(dataset["clips"]) for dataset in linked_datasets)
    guided_prompt_history_count = sum(len(dataset.get("guided_prompt_history", [])) for dataset in linked_datasets)

    safe_assets: list[LinkedDeletionAsset] = []
    unsafe_assets: list[LinkedDeletionAsset] = []
    dataset_root = modeling_datasets_root()
    for dataset in linked_datasets:
        dataset_path = modeling_dataset_dir(dataset)
        if dataset_path.exists():
            if _is_managed_path(dataset_path, dataset_root):
                safe_assets.append(LinkedDeletionAsset("dataset_dir", "managed modeling dataset folder", dataset_path))
            else:
                unsafe_assets.append(
                    LinkedDeletionAsset("dataset_dir", "unmanaged modeling dataset folder", dataset_path)
                )
        unsafe_assets.extend(_unsafe_clip_assets(dataset, dataset_path))

    export_assets = _linked_export_assets(profile["id"], dataset_ids)
    safe_assets.extend(export_assets)
    training_safe_assets, training_unsafe_assets = _linked_training_output_assets(
        profile["id"],
        dataset_ids,
        export_assets,
    )
    safe_assets.extend(training_safe_assets)
    unsafe_assets.extend(training_unsafe_assets)

    safe_assets = _dedupe_assets(safe_assets)
    unsafe_assets = _dedupe_assets(unsafe_assets)
    return VoiceProfileDeletionPlan(
        profile_id=profile["id"],
        profile_name=profile["name"],
        linked_datasets=linked_datasets,
        safe_assets=tuple(safe_assets),
        unsafe_assets=tuple(unsafe_assets),
        recorded_clip_count=recorded_clip_count,
        guided_prompt_history_count=guided_prompt_history_count,
        exported_dataset_count=sum(1 for asset in safe_assets if asset.kind == "export_dir"),
        trained_model_output_count=sum(1 for asset in safe_assets if asset.kind == "training_output_dir"),
    )


def voice_profile_deletion_confirmation_text(plan: VoiceProfileDeletionPlan) -> str:
    lines = [
        f"Delete voice profile '{plan.profile_name}' and all linked modeling work?",
        "",
        "This will delete:",
    ]
    if plan.linked_datasets:
        lines.append(_count_line(len(plan.linked_datasets), "modeling dataset entry", "modeling dataset entries"))
    if plan.recorded_clip_count:
        lines.append(_count_line(plan.recorded_clip_count, "recorded clip", "recorded clips"))
    if plan.guided_prompt_history_count:
        lines.append(
            _count_line(
                plan.guided_prompt_history_count,
                "guided prompt history entry",
                "guided prompt history entries",
            )
        )
    if plan.exported_dataset_count:
        lines.append(
            _count_line(plan.exported_dataset_count, "exported dataset folder", "exported dataset folders")
        )
    if plan.trained_model_output_count:
        lines.append(
            _count_line(
                plan.trained_model_output_count,
                "trained model / training output folder",
                "trained model / training output folders",
            )
        )
    if any(asset.kind == "dataset_dir" for asset in plan.safe_assets):
        lines.append("- other generated artifacts inside managed modeling dataset folders")
    if any(asset.kind == "training_output_dir" for asset in plan.safe_assets):
        lines.append("- other generated artifacts inside linked training output folders")
    if plan.unsafe_assets:
        lines.extend(
            [
                "",
                "These linked paths are not under a safe VoiceBridge-managed location and will NOT be deleted:",
            ]
        )
        lines.extend(f"- {asset.label}: {asset.path}" for asset in plan.unsafe_assets)
    lines.extend(["", "This cannot be undone."])
    return "\n".join(lines)


def delete_voice_profile_and_linked_modeling_assets(
    profile: VoiceProfile,
    voice_profiles: list[VoiceProfile],
    modeling_datasets: list[ModelingDataset],
    *,
    plan: VoiceProfileDeletionPlan | None = None,
) -> VoiceProfileDeletionResult:
    deletion_plan = plan or build_voice_profile_deletion_plan(profile, modeling_datasets)
    deleted_paths: list[Path] = []
    failed_paths: list[Path] = []
    for asset in deletion_plan.safe_assets:
        deleted, failed = _delete_managed_path(asset.path)
        if deleted:
            deleted_paths.append(deleted)
        if failed:
            failed_paths.append(failed)

    audio_deleted, audio_failed = delete_voice_profile_audio_files(profile)
    deleted_paths.extend(audio_deleted)
    failed_paths.extend(audio_failed)

    linked_dataset_ids = {dataset["id"] for dataset in deletion_plan.linked_datasets}
    return VoiceProfileDeletionResult(
        voice_profiles=[entry for entry in voice_profiles if entry["id"] != profile["id"]],
        modeling_datasets=[dataset for dataset in modeling_datasets if dataset["id"] not in linked_dataset_ids],
        removed_modeling_dataset_count=len(linked_dataset_ids),
        deleted_paths=tuple(deleted_paths),
        failed_paths=tuple(failed_paths),
        unsafe_assets=deletion_plan.unsafe_assets,
    )


def voice_profile_deletion_result_message(result: VoiceProfileDeletionResult) -> str:
    if result.failed_paths:
        return f"Deleted profile. Could not delete {len(result.failed_paths)} linked file/folder(s)."
    if result.unsafe_assets:
        return (
            "Deleted profile and linked modeling work. "
            f"{len(result.unsafe_assets)} linked path(s) were left because they were not safely identifiable."
        )
    if result.removed_modeling_dataset_count:
        return "Deleted profile and linked modeling work."
    if result.deleted_paths:
        return f"Deleted profile and {len(result.deleted_paths)} linked audio file(s)."
    return "Deleted profile."


def _linked_export_assets(profile_id: str, dataset_ids: set[str]) -> list[LinkedDeletionAsset]:
    root = modeling_dataset_exports_root()
    if not root.is_dir():
        return []
    assets: list[LinkedDeletionAsset] = []
    for dataset_json_path in root.rglob("dataset.json"):
        data = _read_json_object(dataset_json_path)
        if not data or not app_json_version_supported(data, kind=MODELING_DATASET_EXPORT_JSON_KIND):
            continue
        if data.get("profile_id") != profile_id and data.get("dataset_id") not in dataset_ids:
            continue
        export_dir = dataset_json_path.parent
        if _is_managed_path(export_dir, root):
            assets.append(LinkedDeletionAsset("export_dir", "exported dataset files", export_dir))
    return assets


def _linked_training_output_assets(
    profile_id: str,
    dataset_ids: set[str],
    export_assets: list[LinkedDeletionAsset],
) -> tuple[list[LinkedDeletionAsset], list[LinkedDeletionAsset]]:
    root = voice_modeling_outputs_root()
    if not root.is_dir():
        return [], []
    export_dirs = {_resolve(asset.path) for asset in export_assets}
    export_json_paths = {_resolve(asset.path / "dataset.json") for asset in export_assets}
    safe_assets: list[LinkedDeletionAsset] = []
    unsafe_assets: list[LinkedDeletionAsset] = []
    for config_path in root.rglob(VOICE_MODELING_JOB_CONFIG):
        data = _read_json_object(config_path)
        if not data or not app_json_version_supported(data, kind=VOICE_MODELING_JOB_CONFIG_JSON_KIND):
            continue
        dataset = data.get("dataset")
        if not isinstance(dataset, dict):
            continue
        dataset_dir = _path_from_string(data.get("dataset_dir") or dataset.get("dataset_dir"))
        dataset_json_path = _path_from_string(dataset.get("dataset_json_path"))
        linked = _job_config_matches_linked_dataset(
            profile_id,
            dataset_ids,
            dataset_dir,
            dataset_json_path,
            export_dirs,
            export_json_paths,
        )
        if not linked:
            continue
        unmanaged_export_asset = _unmanaged_linked_export_asset(
            dataset_dir,
            dataset_json_path,
            export_dirs,
        )
        if unmanaged_export_asset:
            unsafe_assets.append(unmanaged_export_asset)
        output_dir = _path_from_string(data.get("output_dir")) or config_path.parent
        if _is_managed_path(output_dir, root):
            safe_assets.append(
                LinkedDeletionAsset("training_output_dir", "trained model / training output files", output_dir)
            )
        else:
            unsafe_assets.append(
                LinkedDeletionAsset(
                    "training_output_dir",
                    "unmanaged trained model / training output files",
                    output_dir,
                )
            )
    return safe_assets, unsafe_assets


def _unmanaged_linked_export_asset(
    dataset_dir: Path | None,
    dataset_json_path: Path | None,
    export_dirs: set[Path],
) -> LinkedDeletionAsset | None:
    export_root = modeling_dataset_exports_root()
    candidates: list[Path] = []
    if dataset_json_path and dataset_json_path.is_file():
        candidates.append(dataset_json_path.parent)
    if dataset_dir and dataset_dir.exists():
        candidates.append(dataset_dir)
    for candidate in candidates:
        resolved = _resolve(candidate)
        if resolved in export_dirs or _is_managed_path(resolved, export_root):
            continue
        return LinkedDeletionAsset("export_dir", "unmanaged exported dataset files", candidate)
    return None


def _job_config_matches_linked_dataset(
    profile_id: str,
    dataset_ids: set[str],
    dataset_dir: Path | None,
    dataset_json_path: Path | None,
    export_dirs: set[Path],
    export_json_paths: set[Path],
) -> bool:
    if dataset_dir and _resolve(dataset_dir) in export_dirs:
        return True
    if dataset_json_path and _resolve(dataset_json_path) in export_json_paths:
        return True
    if not dataset_json_path or not dataset_json_path.is_file():
        return False
    data = _read_json_object(dataset_json_path)
    return bool(
        data
        and app_json_version_supported(data, kind=MODELING_DATASET_EXPORT_JSON_KIND)
        and (data.get("profile_id") == profile_id or data.get("dataset_id") in dataset_ids)
    )


def _unsafe_clip_assets(dataset: ModelingDataset, dataset_path: Path) -> list[LinkedDeletionAsset]:
    assets: list[LinkedDeletionAsset] = []
    for clip in dataset["clips"]:
        audio_path = _path_from_string(clip.get("audio_path"))
        transcript_path = _path_from_string(clip.get("transcript_path"))
        if audio_path and audio_path.exists() and not _is_managed_path(audio_path, dataset_path):
            assets.append(LinkedDeletionAsset("clip_audio", "unmanaged recorded clip", audio_path))
        if transcript_path and transcript_path.exists() and not _is_managed_path(transcript_path, dataset_path):
            assets.append(LinkedDeletionAsset("clip_transcript", "unmanaged transcript sidecar", transcript_path))
    return assets


def _delete_managed_path(path: Path) -> tuple[Path | None, Path | None]:
    try:
        resolved = path.resolve()
        if not resolved.exists():
            return None, None
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
    except OSError:
        return None, path
    return resolved, None


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _path_from_string(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value).expanduser()


def _is_managed_path(path: Path, root: Path) -> bool:
    resolved_path = _resolve(path)
    resolved_root = _resolve(root)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return False
    return resolved_path != resolved_root


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve()


def _dedupe_assets(assets: list[LinkedDeletionAsset]) -> list[LinkedDeletionAsset]:
    deduped: list[LinkedDeletionAsset] = []
    seen: set[tuple[str, Path]] = set()
    for asset in assets:
        key = (asset.kind, _resolve(asset.path))
        if key in seen:
            continue
        deduped.append(asset)
        seen.add(key)
    return deduped


def _count_line(count: int, singular: str, plural: str) -> str:
    label = singular if count == 1 else plural
    return f"- {count} {label}"
