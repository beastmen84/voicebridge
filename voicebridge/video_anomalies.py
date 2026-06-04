from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

SINGLE_FRAME_INTERRUPTION = "single_frame_interruption"
CUT_BOUNDARY_ANOMALY = "cut_boundary_anomaly"
ISOLATED_TRANSITION_FRAME = "isolated_transition_frame"


class FrameAnomaly(TypedDict):
    frame: int
    time: float
    kind: str
    score: float
    diff_prev: float
    diff_next: float
    diff_skip: float
    reason: str


def classify_frame_anomaly(
    *,
    frame_number: int,
    time_seconds: float,
    diff_prev: float,
    diff_next: float,
    diff_skip: float,
    luma: float | None = None,
    min_luma_percent: float = 12.0,
    strong_diff_threshold: float = 28.0,
    similar_context_threshold: float = 8.0,
    boundary_diff_threshold: float = 35.0,
    balance_ratio_threshold: float = 0.55,
) -> FrameAnomaly | None:
    if luma is not None and float(luma) < min_luma_percent:
        return None

    min_neighbor_diff = min(float(diff_prev), float(diff_next))
    max_neighbor_diff = max(float(diff_prev), float(diff_next))
    if max_neighbor_diff <= 0:
        return None
    balanced = (min_neighbor_diff / max_neighbor_diff) >= balance_ratio_threshold

    if (
        balanced
        and min_neighbor_diff >= strong_diff_threshold
        and float(diff_skip) <= similar_context_threshold
    ):
        score = min(100.0, min_neighbor_diff + (similar_context_threshold - float(diff_skip)))
        return {
            "frame": int(frame_number),
            "time": float(time_seconds),
            "kind": SINGLE_FRAME_INTERRUPTION,
            "score": round(score, 3),
            "diff_prev": round(float(diff_prev), 3),
            "diff_next": round(float(diff_next), 3),
            "diff_skip": round(float(diff_skip), 3),
            "reason": "Single frame differs strongly from similar neighboring frames.",
        }

    if balanced and min_neighbor_diff >= boundary_diff_threshold:
        score = min(100.0, min_neighbor_diff)
        return {
            "frame": int(frame_number),
            "time": float(time_seconds),
            "kind": CUT_BOUNDARY_ANOMALY,
            "score": round(score, 3),
            "diff_prev": round(float(diff_prev), 3),
            "diff_next": round(float(diff_next), 3),
            "diff_skip": round(float(diff_skip), 3),
            "reason": "Frame differs strongly from both neighbors; review around the cut boundary.",
        }

    return None


def classify_isolated_transition_frame(
    *,
    frame_number: int,
    time_seconds: float,
    diff_left_context: float,
    diff_right_context: float,
    diff_prev: float,
    diff_next: float,
    diff_skip: float,
    luma: float | None = None,
    min_luma_percent: float = 12.0,
    stable_context_threshold: float = 12.0,
    isolated_transition_threshold: float = 24.0,
    context_separation_threshold: float = 18.0,
    balance_ratio_threshold: float = 0.40,
) -> FrameAnomaly | None:
    if luma is not None and float(luma) < min_luma_percent:
        return None
    if float(diff_left_context) > stable_context_threshold:
        return None
    if float(diff_right_context) > stable_context_threshold:
        return None
    if float(diff_skip) < context_separation_threshold:
        return None

    min_neighbor_diff = min(float(diff_prev), float(diff_next))
    max_neighbor_diff = max(float(diff_prev), float(diff_next))
    if max_neighbor_diff <= 0:
        return None
    balanced = (min_neighbor_diff / max_neighbor_diff) >= balance_ratio_threshold
    if not balanced or min_neighbor_diff < isolated_transition_threshold:
        return None

    context_bonus = max(0.0, stable_context_threshold - float(diff_left_context))
    context_bonus += max(0.0, stable_context_threshold - float(diff_right_context))
    score = min(100.0, min_neighbor_diff + (context_bonus / 2.0))
    return {
        "frame": int(frame_number),
        "time": float(time_seconds),
        "kind": ISOLATED_TRANSITION_FRAME,
        "score": round(score, 3),
        "diff_prev": round(float(diff_prev), 3),
        "diff_next": round(float(diff_next), 3),
        "diff_skip": round(float(diff_skip), 3),
        "reason": "Frame is isolated between two stable but different neighboring contexts.",
    }


def detect_video_anomalies(
    video_path: str,
    *,
    sample_width: int = 160,
    max_results: int = 300,
    min_gap_frames: int = 2,
    on_progress: Callable[[float], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[FrameAnomaly]:
    import cv2  # noqa: PLC0415

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("OpenCV could not open the video file.")

    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame_buffer = []
        frame_number = -1
        anomalies: list[FrameAnomaly] = []
        last_reported_progress = -1
        last_added_frame = -10_000

        while True:
            if should_cancel is not None and should_cancel():
                break
            ok, frame = capture.read()
            if not ok:
                break
            frame_number += 1
            prepared = _prepare_frame(frame, sample_width=sample_width, cv2=cv2)
            frame_buffer.append((frame_number, prepared))
            if len(frame_buffer) > 5:
                frame_buffer.pop(0)

            if len(frame_buffer) == 5:
                _left_context_number, left_context = frame_buffer[0]
                _previous_number, previous = frame_buffer[1]
                current_frame_number, current = frame_buffer[2]
                _next_number, next_frame = frame_buffer[3]
                _right_context_number, right_context = frame_buffer[4]
                diff_left_context = _frame_distance(left_context, previous, cv2=cv2)
                diff_prev = _frame_distance(previous, current, cv2=cv2)
                diff_next = _frame_distance(current, next_frame, cv2=cv2)
                diff_right_context = _frame_distance(next_frame, right_context, cv2=cv2)
                diff_skip = _frame_distance(previous, next_frame, cv2=cv2)
                time_seconds = (current_frame_number / fps) if fps > 0 else 0.0
                anomaly = classify_frame_anomaly(
                    frame_number=current_frame_number,
                    time_seconds=time_seconds,
                    diff_prev=diff_prev,
                    diff_next=diff_next,
                    diff_skip=diff_skip,
                    luma=_frame_luma(current),
                )
                if anomaly is None:
                    anomaly = classify_isolated_transition_frame(
                        frame_number=current_frame_number,
                        time_seconds=time_seconds,
                        diff_left_context=diff_left_context,
                        diff_right_context=diff_right_context,
                        diff_prev=diff_prev,
                        diff_next=diff_next,
                        diff_skip=diff_skip,
                        luma=_frame_luma(current),
                    )
                if anomaly is not None and current_frame_number - last_added_frame >= min_gap_frames:
                    anomalies.append(anomaly)
                    last_added_frame = current_frame_number
                    if len(anomalies) >= max_results:
                        break

            if on_progress is not None and total_frames > 0:
                progress = int(min(99, max(0, (frame_number / total_frames) * 100)))
                if progress != last_reported_progress:
                    last_reported_progress = progress
                    on_progress(float(progress))

        if on_progress is not None:
            on_progress(100.0)
        return anomalies
    finally:
        capture.release()


def _prepare_frame(frame, *, sample_width: int, cv2):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    if width <= 0 or height <= 0:
        return gray
    target_width = max(16, int(sample_width))
    target_height = max(1, round(height * (target_width / width)))
    return cv2.resize(gray, (target_width, target_height), interpolation=cv2.INTER_AREA)


def _frame_distance(left, right, *, cv2) -> float:
    diff = cv2.absdiff(left, right)
    return float(diff.mean() / 255.0 * 100.0)


def _frame_luma(frame) -> float:
    return float(frame.mean() / 255.0 * 100.0)
