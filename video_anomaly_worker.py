from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from voicebridge.video_anomalies import detect_video_anomalies

RESULT_PREFIX = "ANOMALY_RESULT_JSON: "


def emit_status(message: str) -> None:
    print(f"STATUS: {message}", flush=True)


def emit_progress(percent: float) -> None:
    print(f"PROGRESS: {max(0.0, min(100.0, float(percent))):.1f}", flush=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect suspicious single-frame video anomalies.")
    parser.add_argument("--input", required=True, help="Input video file.")
    parser.add_argument("--sample-width", type=int, default=160)
    parser.add_argument("--max-results", type=int, default=300)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    input_path = Path(args.input)
    if not input_path.is_file():
        emit_status(f"Input video not found: {input_path}")
        return 2

    emit_status("Detecting suspicious frame anomalies...")
    try:
        anomalies = detect_video_anomalies(
            str(input_path),
            sample_width=args.sample_width,
            max_results=args.max_results,
            on_progress=emit_progress,
        )
    except ImportError:
        emit_status("OpenCV is not installed in the ML runtime.")
        return 3
    except Exception as exc:
        emit_status(str(exc))
        return 1

    print(
        RESULT_PREFIX + json.dumps({"anomalies": anomalies}, ensure_ascii=False, separators=(",", ":")),
        flush=True,
    )
    emit_status(f"Detected {len(anomalies)} suspicious frame(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
