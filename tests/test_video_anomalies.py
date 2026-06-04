from voicebridge.video_anomalies import (
    CUT_BOUNDARY_ANOMALY,
    ISOLATED_TRANSITION_FRAME,
    SINGLE_FRAME_INTERRUPTION,
    classify_frame_anomaly,
    classify_isolated_transition_frame,
)


def test_classify_frame_anomaly_detects_single_frame_interruption() -> None:
    anomaly = classify_frame_anomaly(
        frame_number=42,
        time_seconds=1.4,
        diff_prev=38.0,
        diff_next=35.0,
        diff_skip=3.0,
        luma=70.0,
    )

    assert anomaly is not None
    assert anomaly["frame"] == 42
    assert anomaly["kind"] == SINGLE_FRAME_INTERRUPTION
    assert anomaly["score"] > 35


def test_classify_frame_anomaly_detects_cut_boundary_anomaly() -> None:
    anomaly = classify_frame_anomaly(
        frame_number=43,
        time_seconds=1.433,
        diff_prev=46.0,
        diff_next=51.0,
        diff_skip=44.0,
        luma=60.0,
    )

    assert anomaly is not None
    assert anomaly["frame"] == 43
    assert anomaly["kind"] == CUT_BOUNDARY_ANOMALY


def test_classify_frame_anomaly_ignores_normal_scene_cut() -> None:
    anomaly = classify_frame_anomaly(
        frame_number=44,
        time_seconds=1.466,
        diff_prev=55.0,
        diff_next=4.0,
        diff_skip=52.0,
        luma=60.0,
    )

    assert anomaly is None


def test_classify_frame_anomaly_requires_balanced_neighbor_differences() -> None:
    anomaly = classify_frame_anomaly(
        frame_number=45,
        time_seconds=1.5,
        diff_prev=50.0,
        diff_next=20.0,
        diff_skip=3.0,
        luma=60.0,
    )

    assert anomaly is None


def test_classify_frame_anomaly_ignores_black_frames() -> None:
    anomaly = classify_frame_anomaly(
        frame_number=46,
        time_seconds=1.533,
        diff_prev=45.0,
        diff_next=42.0,
        diff_skip=2.0,
        luma=3.0,
    )

    assert anomaly is None


def test_classify_isolated_transition_frame_detects_intruder_between_stable_contexts() -> None:
    anomaly = classify_isolated_transition_frame(
        frame_number=3024,
        time_seconds=100.901,
        diff_left_context=3.0,
        diff_right_context=4.0,
        diff_prev=36.0,
        diff_next=28.0,
        diff_skip=42.0,
        luma=65.0,
    )

    assert anomaly is not None
    assert anomaly["frame"] == 3024
    assert anomaly["kind"] == ISOLATED_TRANSITION_FRAME


def test_classify_isolated_transition_frame_ignores_normal_cut() -> None:
    anomaly = classify_isolated_transition_frame(
        frame_number=3024,
        time_seconds=100.901,
        diff_left_context=3.0,
        diff_right_context=4.0,
        diff_prev=42.0,
        diff_next=5.0,
        diff_skip=44.0,
        luma=65.0,
    )

    assert anomaly is None


def test_classify_isolated_transition_frame_requires_stable_contexts() -> None:
    anomaly = classify_isolated_transition_frame(
        frame_number=3024,
        time_seconds=100.901,
        diff_left_context=18.0,
        diff_right_context=4.0,
        diff_prev=36.0,
        diff_next=28.0,
        diff_skip=42.0,
        luma=65.0,
    )

    assert anomaly is None
