from __future__ import annotations

import math
import time
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFont
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from voicebridge.audio_recorder import AudioRecorderError, SoundDevicePcmRecorder, select_input_settings
from voicebridge.languages import language_name
from voicebridge.voice_profile_scripts import voice_profile_recording_script_for_display
from voicebridge.voice_profiles import voice_profile_recording_path
from voicebridge.wav_writer import (
    Pcm16ProcessingResult,
    prepare_voice_reference_pcm,
    trim_pcm16_to_frames,
    write_pcm16_wav,
)

VOICE_PROFILE_RECORD_SAMPLE_RATE = 24_000
VOICE_PROFILE_RECORD_CHANNELS = 1
VOICE_PROFILE_RECORD_SECONDS = 30
VOICE_PROFILE_START_COUNTDOWN_SECONDS = 3
VOICE_PROFILE_END_COUNTDOWN_SECONDS = 3
VOICE_PROFILE_TICK_MS = 200


class VoiceProfileRecordingDialog(QDialog):
    def __init__(self, profile_name: str, language_code: str, device_index: int, parent=None) -> None:
        super().__init__(parent)
        self.profile_name = profile_name
        self.language_code = language_code
        self.device_index = device_index
        self.recording_path: Path | None = None
        self.status_message = ""
        self.quality_details = ""
        self._preview_path: Path | None = None
        self._kept_recording = False
        self._recorder: SoundDevicePcmRecorder | None = None
        self._record_started_at = 0.0
        self._phase = "idle"
        self._countdown_remaining = VOICE_PROFILE_START_COUNTDOWN_SECONDS

        self.setWindowTitle("Voice profile recording")
        self.setModal(True)
        self.setMinimumSize(760, 640)
        self.setStyleSheet(
            """
            QDialog { background: #f8fafc; }
            QLabel { background: transparent; color: #111827; }
            #RecordingCounter { font-size: 36pt; font-weight: 800; color: #2f6fed; }
            #RecordingStatus { color: #617083; }
            #RecordingScript {
                font-size: 15pt;
                padding: 14px;
                border-radius: 8px;
                border: 1px solid #ead8b8;
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

        title = QLabel(f"Read aloud - {language_name(language_code)}")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        self.counter_label = QLabel(str(VOICE_PROFILE_START_COUNTDOWN_SECONDS))
        self.counter_label.setObjectName("RecordingCounter")
        self.counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.counter_label)

        self.status_label = QLabel("Recording starts soon.")
        self.status_label.setObjectName("RecordingStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, VOICE_PROFILE_RECORD_SECONDS * 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        layout.addWidget(self.progress_bar)

        self.script_box = QPlainTextEdit()
        self.script_box.setObjectName("RecordingScript")
        self.script_box.setReadOnly(True)
        self.script_box.setFont(QFont("Segoe UI", 15))
        self.script_box.setPlainText(voice_profile_recording_script_for_display(language_code))
        self.script_box.setMinimumHeight(320)
        layout.addWidget(self.script_box, 1)

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
        self.listen_button = QPushButton("Ascolta")
        self.keep_button = QPushButton("Mantieni")
        self.retry_button = QPushButton("Ritenta")
        self.cancel_button = QPushButton("Annulla")
        self.keep_button.setObjectName("PrimaryButton")
        self.cancel_button.setObjectName("DangerButton")
        self.listen_button.setEnabled(False)
        self.keep_button.setEnabled(False)
        self.retry_button.setEnabled(False)
        self.listen_button.clicked.connect(self.play_clean_recording)
        self.keep_button.clicked.connect(self.keep_recording)
        self.retry_button.clicked.connect(self.retry_recording)
        self.cancel_button.clicked.connect(self.reject)
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
        QTimer.singleShot(0, self.start_countdown)

    def start_countdown(self) -> None:
        self.cleanup_preview_file()
        self._phase = "countdown"
        self._countdown_remaining = VOICE_PROFILE_START_COUNTDOWN_SECONDS
        self.counter_label.setText(str(self._countdown_remaining))
        self.status_label.setText("Prepare to read at a natural pace.")
        self.progress_bar.setValue(0)
        self.details_box.setVisible(False)
        self.listen_button.setEnabled(False)
        self.keep_button.setEnabled(False)
        self.retry_button.setEnabled(False)
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
        remaining = max(0.0, VOICE_PROFILE_RECORD_SECONDS - elapsed)
        self.progress_bar.setValue(min(self.progress_bar.maximum(), int(elapsed * 1000)))
        if 0 < remaining <= VOICE_PROFILE_END_COUNTDOWN_SECONDS:
            self.counter_label.setText(str(max(1, math.ceil(remaining))))
            self.status_label.setText("Finishing recording.")
        else:
            self.counter_label.setText("REC")
            self.status_label.setText(f"Recording... {format_duration(elapsed)} / 00:30")
        if elapsed >= VOICE_PROFILE_RECORD_SECONDS:
            self.complete_recording(auto_stopped=True)

    def start_recording(self) -> None:
        self.timer.stop()
        try:
            settings = select_input_settings(
                self.device_index,
                preferred_sample_rate=VOICE_PROFILE_RECORD_SAMPLE_RATE,
                channel_count=VOICE_PROFILE_RECORD_CHANNELS,
            )
            self._recorder = SoundDevicePcmRecorder(self.device_index, settings)
            self._recorder.start()
        except AudioRecorderError as exc:
            self.show_recording_error(str(exc))
            return

        self._phase = "recording"
        self._record_started_at = time.monotonic()
        self.counter_label.setText("REC")
        self.status_label.setText("Recording... 00:00 / 00:30")
        self.timer.start(VOICE_PROFILE_TICK_MS)

    def complete_recording(self, auto_stopped: bool = False) -> None:
        self.timer.stop()
        self._phase = "processing"
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
            self._preview_path = voice_profile_recording_path(self.profile_name)
            write_pcm16_wav(self._preview_path, recording.pcm_data, settings.sample_rate, settings.channel_count)
        except (OSError, ValueError) as exc:
            self.show_recording_error(str(exc))
            return

        self.recording_path = self._preview_path
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
        self.listen_button.setEnabled(True)
        self.keep_button.setEnabled(True)
        self.retry_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

    def show_recording_error(self, message: str) -> None:
        self._phase = "error"
        self.counter_label.setText("Error")
        self.status_label.setText(message)
        self.details_box.setPlainText(message)
        self.details_box.setVisible(True)
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
        self._kept_recording = True
        self.recording_path = self._preview_path
        self.accept()

    def retry_recording(self) -> None:
        self.stop_recording_if_needed()
        self.media_player.stop()
        self.cleanup_preview_file()
        self.recording_path = None
        self.status_message = ""
        self.quality_details = ""
        self.start_countdown()

    def reject(self) -> None:
        self.stop_recording_if_needed()
        self.media_player.stop()
        if not self._kept_recording:
            self.cleanup_preview_file()
        super().reject()

    def closeEvent(self, event) -> None:
        self.stop_recording_if_needed()
        if not self._kept_recording:
            self.cleanup_preview_file()
        super().closeEvent(event)

    def stop_recording_if_needed(self) -> None:
        self.timer.stop()
        recorder = self._recorder
        self._recorder = None
        if recorder is None:
            return
        with suppress(AudioRecorderError):
            recorder.stop()

    def cleanup_preview_file(self) -> None:
        if not self._preview_path or self._kept_recording:
            return
        with suppress(OSError):
            self._preview_path.unlink(missing_ok=True)
        self._preview_path = None


def build_recording_status_message(
    recording: Pcm16ProcessingResult,
    recorder_messages: tuple[str, ...] = (),
    *,
    auto_stopped: bool = False,
) -> str:
    cleanup_messages = (*recording.messages, *recorder_messages)
    cleanup_message = f" {' '.join(cleanup_messages)}" if cleanup_messages else ""
    if recording.duration_seconds < 10:
        return (
            f"Recorded {recording.duration_seconds:.1f}s. "
            f"Usable speech is short; retry if possible.{cleanup_message}"
        )
    if auto_stopped:
        return f"Recorded {recording.duration_seconds:.1f}s. Maximum reference length reached.{cleanup_message}"
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
        f"Input clipping: {source.clipped_percent:.2f}%",
    ]
    messages = (*recording.messages, *recorder_messages)
    if messages:
        lines.append("Notes: " + " ".join(messages))
    return "\n".join(lines)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
