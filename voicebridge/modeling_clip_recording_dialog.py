from __future__ import annotations

import math
import time
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl
from PySide6.QtGui import QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
)

from voicebridge.audio_recorder import AudioRecorderError, SoundDevicePcmRecorder, select_input_settings
from voicebridge.wav_writer import (
    Pcm16ProcessingResult,
    prepare_voice_reference_pcm,
    trim_pcm16_to_frames,
    write_pcm16_wav,
)

MODELING_CLIP_RECORD_SAMPLE_RATE = 24_000
MODELING_CLIP_RECORD_CHANNELS = 1
MODELING_CLIP_START_COUNTDOWN_SECONDS = 3
MODELING_CLIP_TICK_MS = 200
MODELING_CLIP_DEFAULT_MAX_SECONDS = 60


class ModelingClipRecordingDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        output_path: Path,
        device_index: int,
        prompt_text: str = "",
        max_seconds: int = MODELING_CLIP_DEFAULT_MAX_SECONDS,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.output_path = output_path
        self.device_index = device_index
        self.prompt_text = prompt_text.strip()
        self.max_seconds = max(1, int(max_seconds))
        self.recording_path: Path | None = None
        self.status_message = ""
        self.quality_details = ""
        self.duration_seconds = 0.0
        self._preview_path: Path | None = None
        self._kept_recording = False
        self._recorder: SoundDevicePcmRecorder | None = None
        self._record_started_at = 0.0
        self._phase = "idle"
        self._target_seconds = self.estimated_target_seconds(self.prompt_text, self.max_seconds)
        self._countdown_remaining = MODELING_CLIP_START_COUNTDOWN_SECONDS

        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(760, 640)
        self.setStyleSheet(
            """
            QDialog { background: #f8fafc; }
            QLabel { background: transparent; color: #111827; }
            #RecordingCounter { font-size: 36pt; font-weight: 800; color: #2f6fed; }
            #RecordingStatus { color: #617083; }
            #RecordingScript {
                border-radius: 8px;
                border: 1px solid #ead8b8;
                background: #fff8e8;
            }
            #RecordingScriptText {
                font-size: 15pt;
                padding: 14px;
                background: #fff8e8;
            }
            #RecordingDetails {
                font-size: 10pt;
                padding: 10px;
                border-radius: 8px;
                border: 1px solid #cfd6e2;
                background: #ffffff;
            }
            QPushButton {
                min-width: 92px;
                min-height: 34px;
                padding: 7px 14px;
                border-radius: 6px;
                border: 1px solid #cfd6e2;
                background: #ffffff;
            }
            QPushButton:hover { background: #f1f5fb; border-color: #aeb9c8; }
            QPushButton:disabled { color: #98a2b3; background: #eef1f5; }
            #PrimaryButton { color: white; background: #2f6fed; border-color: #2f6fed; font-weight: 600; }
            #DangerButton { color: white; background: #b42318; border-color: #b42318; font-weight: 600; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("CardTitle")
        layout.addWidget(self.title_label)

        self.counter_label = QLabel("Ready")
        self.counter_label.setObjectName("RecordingCounter")
        self.counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.counter_label)

        self.status_label = QLabel("Press Start when you are ready.")
        self.status_label.setObjectName("RecordingStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.max_seconds * 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)

        self.script_box = QScrollArea()
        self.script_box.setObjectName("RecordingScript")
        self.script_box.setWidgetResizable(True)
        self.script_box.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.script_box.setMinimumHeight(300)
        display_text = self.prompt_text or (
            f"Free recording. Speak naturally, then press Stop. Maximum length: {format_duration(self.max_seconds)}."
        )
        self.script_text = QLabel(display_text)
        self.script_text.setObjectName("RecordingScriptText")
        self.script_text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.script_text.setFont(QFont("Segoe UI", 15))
        self.script_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.script_text.setTextFormat(Qt.TextFormat.PlainText)
        self.script_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.script_text.setWordWrap(True)
        self.script_box.setWidget(self.script_text)
        layout.addWidget(self.script_box, 1)
        self.script_scroll_animation = QPropertyAnimation(self.script_box.verticalScrollBar(), b"value", self)
        self.script_scroll_animation.setEasingCurve(QEasingCurve.Type.Linear)

        self.details_box = QPlainTextEdit()
        self.details_box.setObjectName("RecordingDetails")
        self.details_box.setReadOnly(True)
        self.details_box.setFont(QFont("Segoe UI", 10))
        self.details_box.setMinimumHeight(110)
        self.details_box.setMaximumHeight(150)
        self.details_box.setVisible(False)
        layout.addWidget(self.details_box)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.start_stop_button = QPushButton("Start")
        self.listen_button = QPushButton("Ascolta")
        self.keep_button = QPushButton("Mantieni")
        self.retry_button = QPushButton("Ritenta")
        self.cancel_button = QPushButton("Annulla")
        self.start_stop_button.setObjectName("PrimaryButton")
        self.keep_button.setObjectName("PrimaryButton")
        self.cancel_button.setObjectName("DangerButton")
        self.listen_button.setEnabled(False)
        self.keep_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.start_stop_button.clicked.connect(self.start_or_stop)
        self.listen_button.clicked.connect(self.play_clean_recording)
        self.keep_button.clicked.connect(self.keep_recording)
        self.retry_button.clicked.connect(self.retry_recording)
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.start_stop_button)
        button_row.addWidget(self.listen_button)
        button_row.addWidget(self.keep_button)
        button_row.addWidget(self.retry_button)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.audio_output = QAudioOutput(self)
        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)

    @staticmethod
    def estimated_target_seconds(text: str, max_seconds: int = MODELING_CLIP_DEFAULT_MAX_SECONDS) -> int:
        if not text.strip():
            return max(1, int(max_seconds))
        word_count = max(1, len(text.split()))
        return min(max(1, int(max_seconds)), max(12, math.ceil(word_count / 2.2) + 5))

    @staticmethod
    def preview_recording_path(output_path: Path) -> Path:
        return output_path.with_name(f".{output_path.stem}.preview-{uuid4().hex}{output_path.suffix}")

    def start_or_stop(self) -> None:
        if self._phase == "idle":
            self.start_countdown()
            return
        if self._phase == "recording":
            self.complete_recording()

    def start_countdown(self) -> None:
        self.cleanup_preview_file()
        self._phase = "countdown"
        self._countdown_remaining = MODELING_CLIP_START_COUNTDOWN_SECONDS
        self.counter_label.setText(str(self._countdown_remaining))
        if self.prompt_text:
            self.status_label.setText("Prepare to read at a natural pace.")
        else:
            self.status_label.setText("Prepare to speak naturally.")
        self.progress_bar.setValue(0)
        self.scroll_script_to_percent(0.0, animated=False)
        self.details_box.setVisible(False)
        self.listen_button.setEnabled(False)
        self.keep_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.start_stop_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.timer.start(1000)

    def tick(self) -> None:
        if self._phase == "countdown":
            self._countdown_remaining -= 1
            if self._countdown_remaining <= 0:
                self.start_recording()
                return
            self.counter_label.setText(str(self._countdown_remaining))
            return

        if self._phase != "recording":
            return
        elapsed = max(0.0, time.monotonic() - self._record_started_at)
        self.progress_bar.setValue(min(self.progress_bar.maximum(), int(elapsed * 1000)))
        self.counter_label.setText("REC")
        self.status_label.setText(f"Recording... {format_duration(elapsed)} / {format_duration(self.max_seconds)}")
        if elapsed >= self.max_seconds:
            self.complete_recording(auto_stopped=True)

    def start_recording(self) -> None:
        self.timer.stop()
        try:
            settings = select_input_settings(
                self.device_index,
                preferred_sample_rate=MODELING_CLIP_RECORD_SAMPLE_RATE,
                channel_count=MODELING_CLIP_RECORD_CHANNELS,
            )
            recorder = SoundDevicePcmRecorder(self.device_index, settings)
            recorder.start()
            self._recorder = recorder
        except AudioRecorderError as exc:
            self.show_recording_error(str(exc))
            return

        self._phase = "recording"
        self._record_started_at = time.monotonic()
        self.counter_label.setText("REC")
        self.status_label.setText("Recording... 00:00")
        self.start_stop_button.setText("Stop")
        self.start_stop_button.setEnabled(True)
        self.start_stop_button.setObjectName("DangerButton")
        self.start_stop_button.style().unpolish(self.start_stop_button)
        self.start_stop_button.style().polish(self.start_stop_button)
        self.scroll_script_to_percent(0.0, animated=False)
        self.start_script_scroll_animation()
        self.timer.start(MODELING_CLIP_TICK_MS)

    def complete_recording(self, auto_stopped: bool = False) -> None:
        self.timer.stop()
        self.script_scroll_animation.stop()
        self.scroll_script_to_percent(1.0, animated=False)
        self._phase = "processing"
        self.start_stop_button.setEnabled(False)
        recorder = self._recorder
        self._recorder = None
        if recorder is None:
            self.show_recording_error("Recording was not started.")
            return
        try:
            recorder.stop()
        except AudioRecorderError as exc:
            self.show_recording_error(str(exc))
            return

        settings = recorder.settings
        pcm_data = trim_pcm16_to_frames(recorder.read_pcm(), settings.channel_count)
        recording = prepare_voice_reference_pcm(pcm_data, settings.sample_rate, settings.channel_count)
        recorder_messages = recorder.status_messages
        try:
            if recording.duration_seconds < 1:
                reason = " ".join(recording.messages) or "Recording is too short."
                raise ValueError(reason)
            preview_path = self.preview_recording_path(self.output_path)
            write_pcm16_wav(preview_path, recording.pcm_data, settings.sample_rate, settings.channel_count)
            self._preview_path = preview_path
        except (OSError, ValueError) as exc:
            self.show_recording_error(str(exc))
            return

        self.duration_seconds = recording.duration_seconds
        self.status_message = build_recording_status_message(recording, recorder_messages, auto_stopped=auto_stopped)
        self.quality_details = build_recording_quality_details(
            recording,
            sample_rate=settings.sample_rate,
            channel_count=settings.channel_count,
            recorder_messages=recorder_messages,
        )
        self._phase = "review"
        self.counter_label.setText("Done")
        self.status_label.setText(self.status_message)
        self.details_box.setPlainText(self.quality_details)
        self.details_box.setVisible(True)
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.start_stop_button.setText("Start")
        self.start_stop_button.setEnabled(False)
        self.listen_button.setEnabled(True)
        self.keep_button.setEnabled(True)
        self.retry_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def show_recording_error(self, message: str) -> None:
        self._phase = "error"
        self.script_scroll_animation.stop()
        self.counter_label.setText("Error")
        self.status_label.setText(message)
        self.details_box.setPlainText(message)
        self.details_box.setVisible(True)
        self.start_stop_button.setText("Start")
        self.start_stop_button.setObjectName("PrimaryButton")
        self.start_stop_button.style().unpolish(self.start_stop_button)
        self.start_stop_button.style().polish(self.start_stop_button)
        self.start_stop_button.setEnabled(False)
        self.listen_button.setEnabled(False)
        self.keep_button.setEnabled(False)
        self.retry_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def play_clean_recording(self) -> None:
        if not self._preview_path or not self._preview_path.is_file():
            return
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.stop()
            return
        self.media_player.setSource(QUrl.fromLocalFile(str(self._preview_path.resolve())))
        self.media_player.play()

    def keep_recording(self) -> None:
        if not self._preview_path or not self._preview_path.is_file():
            return
        ModelingClipRecordingDialog.release_preview_player(self)
        try:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            self._preview_path.replace(self.output_path)
        except OSError as exc:
            self.show_recording_error(str(exc))
            return
        self._preview_path = self.output_path
        self.recording_path = self.output_path
        self._kept_recording = True
        self.accept()

    def retry_recording(self) -> None:
        self.stop_recording_if_needed()
        ModelingClipRecordingDialog.release_preview_player(self)
        self.cleanup_preview_file()
        self.recording_path = None
        self.status_message = ""
        self.quality_details = ""
        self.duration_seconds = 0.0
        self._phase = "idle"
        self.counter_label.setText("Ready")
        self.status_label.setText("Press Start when you are ready.")
        self.progress_bar.setValue(0)
        self.start_stop_button.setText("Start")
        self.start_stop_button.setObjectName("PrimaryButton")
        self.start_stop_button.style().unpolish(self.start_stop_button)
        self.start_stop_button.style().polish(self.start_stop_button)
        self.start_stop_button.setEnabled(True)
        self.listen_button.setEnabled(False)
        self.keep_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

    def reject(self) -> None:
        self.stop_recording_if_needed()
        ModelingClipRecordingDialog.release_preview_player(self)
        if not self._kept_recording:
            self.cleanup_preview_file()
        super().reject()

    def closeEvent(self, event) -> None:
        self.stop_recording_if_needed()
        ModelingClipRecordingDialog.release_preview_player(self)
        if not self._kept_recording:
            self.cleanup_preview_file()
        super().closeEvent(event)

    def stop_recording_if_needed(self) -> None:
        self.timer.stop()
        self.script_scroll_animation.stop()
        recorder = self._recorder
        self._recorder = None
        if recorder is None:
            return
        with suppress(AudioRecorderError):
            recorder.stop()

    def release_preview_player(self) -> None:
        media_player = getattr(self, "media_player", None)
        if media_player is None:
            return
        media_player.stop()
        media_player.setSource(QUrl())

    def cleanup_preview_file(self) -> None:
        if not self._preview_path or self._kept_recording:
            return
        ModelingClipRecordingDialog.release_preview_player(self)
        with suppress(OSError):
            self._preview_path.unlink(missing_ok=True)
        self._preview_path = None

    def scroll_script_to_percent(self, percent: float, *, animated: bool = True) -> None:
        scrollbar = self.script_box.verticalScrollBar()
        scroll_range = scrollbar.maximum() - scrollbar.minimum()
        if scroll_range <= 0:
            return
        clamped_percent = max(0.0, min(1.0, percent))
        target_value = scrollbar.minimum() + round(scroll_range * clamped_percent)
        if target_value == scrollbar.value():
            return
        self.script_scroll_animation.stop()
        if not animated:
            scrollbar.setValue(target_value)
            return
        self.script_scroll_animation.setDuration(MODELING_CLIP_TICK_MS)
        self.script_scroll_animation.setStartValue(scrollbar.value())
        self.script_scroll_animation.setEndValue(target_value)
        self.script_scroll_animation.start()

    def start_script_scroll_animation(self) -> None:
        if not self.prompt_text:
            return
        scrollbar = self.script_box.verticalScrollBar()
        scroll_range = scrollbar.maximum() - scrollbar.minimum()
        self.script_scroll_animation.stop()
        if scroll_range <= 0:
            return
        self.script_scroll_animation.setDuration(self._target_seconds * 1000)
        self.script_scroll_animation.setStartValue(scrollbar.minimum())
        self.script_scroll_animation.setEndValue(scrollbar.maximum())
        self.script_scroll_animation.start()


def build_recording_status_message(
    recording: Pcm16ProcessingResult,
    recorder_messages: tuple[str, ...] = (),
    *,
    auto_stopped: bool = False,
) -> str:
    cleanup_messages = (*recording.messages, *recorder_messages)
    cleanup_message = f" {' '.join(cleanup_messages)}" if cleanup_messages else ""
    if recording.duration_seconds < 5:
        return (
            f"Recorded {recording.duration_seconds:.1f}s. "
            f"Usable speech is short; retry if possible.{cleanup_message}"
        )
    if auto_stopped:
        return f"Recorded {recording.duration_seconds:.1f}s. Maximum clip length reached.{cleanup_message}"
    return f"Recorded {recording.duration_seconds:.1f}s.{cleanup_message}"


def build_recording_quality_details(
    recording: Pcm16ProcessingResult,
    *,
    sample_rate: int,
    channel_count: int,
    recorder_messages: tuple[str, ...] = (),
) -> str:
    source = recording.source_analysis
    cleaned = recording.analysis
    lines = [
        f"Sample rate: {sample_rate} Hz",
        f"Channels: {channel_count}",
        f"Raw duration: {recording.original_duration_seconds:.1f}s",
        f"Cleaned duration: {recording.duration_seconds:.1f}s",
        f"Trimmed silence: {recording.trimmed_seconds:.1f}s",
        f"Peak level: {cleaned.peak_percent * 100:.0f}%",
        f"RMS level: {cleaned.rms_percent * 100:.0f}%",
        f"Estimated SNR: {_format_snr(recording.snr_db)}",
        f"Input clipping: {source.clipped_percent:.2f}%",
    ]
    messages = (*recording.messages, *recorder_messages)
    if messages:
        lines.append("Notes: " + " ".join(messages))
    return "\n".join(lines)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _format_snr(snr_db: float | None) -> str:
    if snr_db is None:
        return "not measurable"
    return f"{snr_db:.1f} dB"
