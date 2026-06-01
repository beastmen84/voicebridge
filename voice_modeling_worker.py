import argparse
import gc
import json
import os
import shutil
import sys
from contextlib import nullcontext, suppress
from pathlib import Path

from voicebridge.app_paths import (
    local_tts_dvae_path,
    local_tts_mel_stats_path,
    local_tts_model_cache_dir,
    local_tts_model_dir,
    local_tts_model_required_files,
)
from voicebridge.voice_modeling import (
    VOICE_MODELING_DEFAULT_GRAD_ACCUM_STEPS,
    VOICE_MODELING_DEFAULT_MAX_AUDIO_SECONDS,
    VOICE_MODELING_LOG,
    load_voice_modeling_job_config,
    prepare_voice_modeling_training_job,
    update_voice_modeling_job_status,
    write_voice_modeling_training_state,
)


class TeeStream:
    def __init__(self, stream, log_file):
        self.stream = stream
        self.log_file = log_file

    def write(self, data):
        self.stream.write(data)
        self.log_file.write(data)

    def flush(self):
        self.stream.flush()
        self.log_file.flush()

    def isatty(self):
        return False


class WorkerLog:
    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.log_file = None
        self.previous_stdout = None
        self.previous_stderr = None

    def __enter__(self):
        config = load_voice_modeling_job_config(self.config_path)
        log_path = Path(config["output_dir"]).expanduser() / VOICE_MODELING_LOG
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_file = log_path.open("a", encoding="utf-8")
        self.previous_stdout = sys.stdout
        self.previous_stderr = sys.stderr
        sys.stdout = TeeStream(self.previous_stdout, self.log_file)
        sys.stderr = TeeStream(self.previous_stderr, self.log_file)
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.previous_stdout is not None:
            sys.stdout = self.previous_stdout
        if self.previous_stderr is not None:
            sys.stderr = self.previous_stderr
        if self.log_file is not None:
            self.log_file.close()
        return False


def worker_log_context(config_path):
    try:
        return WorkerLog(config_path)
    except (OSError, ValueError):
        return nullcontext()


def status(message):
    print(f"STATUS: {message}", flush=True)


def progress(percent):
    percent = max(0, min(100, int(round(percent))))
    print(f"PROGRESS: {percent}", flush=True)


def project_root():
    return Path(__file__).resolve().parent


def configure_model_cache(model_root):
    model_root = Path(model_root)
    tts_home = model_root
    huggingface_home = model_root / "huggingface"
    tts_home.mkdir(parents=True, exist_ok=True)
    huggingface_home.mkdir(parents=True, exist_ok=True)
    os.environ["TTS_HOME"] = str(tts_home)
    os.environ["COQUI_TTS_HOME"] = str(tts_home)
    os.environ["HF_HOME"] = str(huggingface_home)


def resolve_runtime_device(device):
    import torch

    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError(
            "CUDA was selected, but this ML runtime cannot access an NVIDIA CUDA GPU. "
            "Use Auto/CPU or install a CUDA-enabled PyTorch runtime."
        )
    return device


def configure_requested_device(device):
    if device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""


def require_training_assets():
    model_dir = local_tts_model_cache_dir()
    missing = [
        str(model_dir / filename)
        for filename in local_tts_model_required_files()
        if not (model_dir / filename).is_file()
    ]
    if not local_tts_dvae_path().is_file():
        missing.append(str(local_tts_dvae_path()))
    if not local_tts_mel_stats_path().is_file():
        missing.append(str(local_tts_mel_stats_path()))
    if missing:
        missing_text = "\n".join(f"- {path}" for path in missing)
        raise ValueError(f"XTTS-v2 training assets are incomplete. Missing:\n{missing_text}")


def import_training_dependencies():
    import torch
    from trainer import Trainer, TrainerArgs
    from TTS.config.shared_configs import BaseDatasetConfig
    from TTS.tts.datasets import load_tts_samples
    from TTS.tts.layers.xtts.trainer.gpt_trainer import GPTArgs, GPTTrainer, GPTTrainerConfig
    from TTS.tts.models.xtts import XttsAudioConfig

    return {
        "torch": torch,
        "Trainer": Trainer,
        "TrainerArgs": TrainerArgs,
        "BaseDatasetConfig": BaseDatasetConfig,
        "load_tts_samples": load_tts_samples,
        "GPTArgs": GPTArgs,
        "GPTTrainer": GPTTrainer,
        "GPTTrainerConfig": GPTTrainerConfig,
        "XttsAudioConfig": XttsAudioConfig,
    }


def latest_checkpoint(path):
    candidates = []
    for pattern in ("best_model.pth", "checkpoint*.pth", "*.pth"):
        candidates.extend(Path(path).glob(pattern))
    candidates = [candidate for candidate in candidates if candidate.is_file()]
    return max(candidates, key=lambda item: item.stat().st_mtime, default=None)


def export_inference_checkpoint(source_path, target_path, torch_module):
    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        checkpoint = torch_module.load(source_path, map_location=torch_module.device("cpu"), weights_only=False)
        if isinstance(checkpoint, dict):
            checkpoint.pop("optimizer", None)
            model_state = checkpoint.get("model")
            if isinstance(model_state, dict):
                for key in list(model_state):
                    if "dvae" in key:
                        del model_state[key]
        torch_module.save(checkpoint, target_path)
    except (OSError, RuntimeError, ValueError, TypeError):
        shutil.copy2(source_path, target_path)


def run_dry_run(config_path):
    configure_model_cache(local_tts_model_dir())
    plan = prepare_voice_modeling_training_job(config_path)
    config = load_voice_modeling_job_config(config_path)
    configure_requested_device(config["device"])
    progress(5)
    dependencies = import_training_dependencies()
    torch_module = dependencies["torch"]
    device = resolve_runtime_device(config["device"])
    require_training_assets()
    progress(80)
    detail = (
        f"Dry run OK. Torch {torch_module.__version__}; device={device}; "
        f"train_rows={plan['train_rows']}; eval_rows={plan['eval_rows']}."
    )
    update_voice_modeling_job_status(config_path, "dry_run_ok")
    write_voice_modeling_training_state(
        config_path,
        status="dry_run_ok",
        message=detail,
        extra={
            "prepared_dir": plan["prepared_dir"],
            "train_csv_path": plan["train_csv_path"],
            "eval_csv_path": plan["eval_csv_path"],
            "train_rows": plan["train_rows"],
            "eval_rows": plan["eval_rows"],
            "device": device,
        },
    )
    status(detail)
    progress(100)


def run_training(config_path):
    configure_model_cache(local_tts_model_dir())
    plan = prepare_voice_modeling_training_job(config_path)
    config = load_voice_modeling_job_config(config_path)
    configure_requested_device(config["device"])
    dependencies = import_training_dependencies()
    torch_module = dependencies["torch"]
    device = resolve_runtime_device(config["device"])
    require_training_assets()

    output_dir = Path(config["output_dir"]).expanduser()
    run_output_dir = output_dir / "run" / "training"
    run_output_dir.mkdir(parents=True, exist_ok=True)
    progress(5)
    status(f"Training runtime ready on {device}.")
    update_voice_modeling_job_status(config_path, "running")
    write_voice_modeling_training_state(
        config_path,
        status="running",
        message=f"Training started on {device}.",
        extra={"prepared_dir": plan["prepared_dir"], "log_path": plan["log_path"]},
    )

    dataset_config = dependencies["BaseDatasetConfig"](
        formatter="coqui",
        dataset_name="voicebridge_ft_dataset",
        path=plan["dataset_dir"],
        meta_file_train=plan["train_csv_path"],
        meta_file_val=plan["eval_csv_path"],
        language=config["dataset"]["language_code"],
    )
    max_audio_seconds = int(config.get("max_audio_seconds", VOICE_MODELING_DEFAULT_MAX_AUDIO_SECONDS))
    max_audio_length = max(1, max_audio_seconds) * 22050
    grad_accum_steps = int(config.get("grad_accum_steps", VOICE_MODELING_DEFAULT_GRAD_ACCUM_STEPS))
    model_cache_dir = local_tts_model_cache_dir()
    model_args = dependencies["GPTArgs"](
        max_conditioning_length=132300,
        min_conditioning_length=66150,
        debug_loading_failures=False,
        max_wav_length=max_audio_length,
        max_text_length=200,
        mel_norm_file=str(local_tts_mel_stats_path()),
        dvae_checkpoint=str(local_tts_dvae_path()),
        xtts_checkpoint=str(model_cache_dir / "model.pth"),
        tokenizer_file=str(model_cache_dir / "vocab.json"),
        gpt_num_audio_tokens=1026,
        gpt_start_audio_token=1024,
        gpt_stop_audio_token=1025,
        gpt_use_masking_gt_prompt_approach=True,
        gpt_use_perceiver_resampler=True,
    )
    audio_config = dependencies["XttsAudioConfig"](sample_rate=22050, dvae_sample_rate=22050, output_sample_rate=24000)
    trainer_config = dependencies["GPTTrainerConfig"](
        epochs=int(config["max_epochs"]),
        output_path=str(run_output_dir),
        model_args=model_args,
        run_name="GPT_XTTS_FT",
        project_name="VoiceBridge_XTTS_trainer",
        run_description="VoiceBridge XTTS-v2 GPT fine-tuning",
        dashboard_logger="tensorboard",
        logger_uri=None,
        audio=audio_config,
        batch_size=int(config["batch_size"]),
        batch_group_size=48,
        eval_batch_size=int(config["batch_size"]),
        num_loader_workers=0,
        eval_split_max_size=256,
        print_step=10,
        plot_step=100,
        log_model_step=100,
        save_step=1000,
        save_n_checkpoints=1,
        save_checkpoints=True,
        print_eval=False,
        optimizer="AdamW",
        optimizer_wd_only_on_weights=True,
        optimizer_params={"betas": [0.9, 0.96], "eps": 1e-8, "weight_decay": 1e-2},
        lr=5e-06,
        lr_scheduler="MultiStepLR",
        lr_scheduler_params={"milestones": [900000, 2700000, 5400000], "gamma": 0.5, "last_epoch": -1},
        test_sentences=[],
    )
    progress(15)
    status("Loading training samples...")
    train_samples, eval_samples = dependencies["load_tts_samples"](
        [dataset_config],
        eval_split=True,
        eval_split_max_size=trainer_config.eval_split_max_size,
        eval_split_size=trainer_config.eval_split_size,
    )
    status(f"Loaded {len(train_samples)} train sample(s), {len(eval_samples)} eval sample(s).")
    progress(25)

    model = dependencies["GPTTrainer"].init_from_config(trainer_config)
    trainer = dependencies["Trainer"](
        dependencies["TrainerArgs"](
            restore_path=config["resume_checkpoint"] or None,
            skip_train_epoch=False,
            start_with_eval=False,
            grad_accum_steps=grad_accum_steps,
        ),
        trainer_config,
        output_path=str(run_output_dir),
        model=model,
        train_samples=train_samples,
        eval_samples=eval_samples,
    )
    status("Training started. This can take a long time.")
    progress(30)
    trainer.fit()
    trainer_out_path = Path(trainer.output_path)
    status("Training finished. Preparing inference files...")
    progress(92)

    inference_dir = output_dir / "inference_model"
    checkpoint_path = latest_checkpoint(trainer_out_path)
    if checkpoint_path is None:
        raise RuntimeError(f"Training finished, but no checkpoint was found in {trainer_out_path}.")
    inference_model_path = inference_dir / "model.pth"
    export_inference_checkpoint(checkpoint_path, inference_model_path, torch_module)
    shutil.copy2(model_cache_dir / "config.json", inference_dir / "config.json")
    shutil.copy2(model_cache_dir / "vocab.json", inference_dir / "vocab.json")
    speaker_ref = ""
    if train_samples:
        speaker_ref = max(train_samples, key=lambda item: len(str(item.get("text", "")).split())).get("audio_file", "")
    result = {
        "status": "completed",
        "config_path": str(Path(config_path).expanduser().resolve()),
        "trainer_output_dir": str(trainer_out_path),
        "inference_dir": str(inference_dir),
        "model_path": str(inference_model_path),
        "config_path_for_inference": str(inference_dir / "config.json"),
        "vocab_path": str(inference_dir / "vocab.json"),
        "speaker_wav": speaker_ref,
    }
    (output_dir / "training_result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    del model, trainer, train_samples, eval_samples
    gc.collect()
    with suppress(Exception):
        if torch_module.cuda.is_available():
            torch_module.cuda.empty_cache()

    update_voice_modeling_job_status(config_path, "completed")
    write_voice_modeling_training_state(config_path, status="completed", message="Training completed.", extra=result)
    status(f"Training completed: {inference_dir}")
    progress(100)


def parse_args():
    parser = argparse.ArgumentParser(description="VoiceBridge XTTS-v2 voice modeling worker.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    try:
        with worker_log_context(config_path):
            if args.dry_run:
                run_dry_run(config_path)
            else:
                run_training(config_path)
    except (ImportError, OSError, RuntimeError, ValueError, AssertionError) as exc:
        with suppress(Exception):
            update_voice_modeling_job_status(config_path, "failed")
            write_voice_modeling_training_state(config_path, status="failed", message=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
