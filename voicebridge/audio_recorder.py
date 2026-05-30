from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

try:
    import sounddevice as _sounddevice
except (ImportError, OSError):
    _sounddevice = None


class AudioRecorderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioInputDevice:
    index: int
    name: str
    host_api: str
    max_input_channels: int
    default_sample_rate: int
    is_default: bool = False


@dataclass(frozen=True)
class AudioRecordingSettings:
    sample_rate: int
    channel_count: int


def sounddevice_available() -> bool:
    return _sounddevice is not None


def list_input_devices() -> list[AudioInputDevice]:
    sd = _load_sounddevice()
    try:
        raw_devices = sd.query_devices()
        raw_host_apis = sd.query_hostapis()
    except Exception as exc:
        raise AudioRecorderError(f"Could not query audio input devices: {exc}") from exc

    host_api_names = [
        str(host_api.get("name", f"Host API {index}")) if isinstance(host_api, dict) else f"Host API {index}"
        for index, host_api in enumerate(raw_host_apis)
    ]
    default_input_index = _default_input_device_index(sd)
    devices: list[AudioInputDevice] = []
    for index, device in enumerate(raw_devices):
        if not isinstance(device, dict):
            continue
        max_input_channels = int(device.get("max_input_channels", 0) or 0)
        if max_input_channels <= 0:
            continue
        device_index_value = device.get("index", index)
        device_index = int(device_index_value if device_index_value is not None else index)
        host_api_value = device.get("hostapi", -1)
        host_api_index = int(host_api_value if host_api_value is not None else -1)
        host_api = host_api_names[host_api_index] if 0 <= host_api_index < len(host_api_names) else "Unknown"
        default_sample_rate = int(float(device.get("default_samplerate", 0) or 0))
        devices.append(
            AudioInputDevice(
                index=device_index,
                name=str(device.get("name", f"Input {index}")),
                host_api=host_api,
                max_input_channels=max_input_channels,
                default_sample_rate=default_sample_rate,
                is_default=device_index == default_input_index,
            )
        )

    return _deduplicate_input_devices(devices)


def select_input_settings(
    device_index: int,
    *,
    preferred_sample_rate: int = 24_000,
    channel_count: int = 1,
) -> AudioRecordingSettings:
    sd = _load_sounddevice()
    sample_rates = _candidate_sample_rates(preferred_sample_rate)
    last_error: Exception | None = None
    for sample_rate in sample_rates:
        try:
            sd.check_input_settings(
                device=device_index,
                channels=channel_count,
                samplerate=sample_rate,
                dtype="int16",
            )
        except Exception as exc:
            last_error = exc
            continue
        return AudioRecordingSettings(sample_rate=sample_rate, channel_count=channel_count)

    raise AudioRecorderError("The selected microphone does not support PCM int16 recording.") from last_error


class SoundDevicePcmRecorder:
    def __init__(self, device_index: int, settings: AudioRecordingSettings) -> None:
        self.device_index = device_index
        self.settings = settings
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._stream: Any | None = None
        self._status_messages: list[str] = []

    @property
    def is_running(self) -> bool:
        return self._stream is not None

    @property
    def status_messages(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._status_messages)

    def start(self) -> None:
        if self._stream is not None:
            return
        sd = _load_sounddevice()
        try:
            self._stream = sd.RawInputStream(
                samplerate=self.settings.sample_rate,
                device=self.device_index,
                channels=self.settings.channel_count,
                dtype="int16",
                callback=self._record_callback,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise AudioRecorderError(f"Could not start microphone recording: {exc}") from exc

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        stop_error: Exception | None = None
        try:
            stream.stop()
        except Exception as exc:
            stop_error = exc
        try:
            stream.close()
        except Exception as exc:
            stop_error = exc
        if stop_error is not None:
            raise AudioRecorderError(f"Could not stop microphone recording cleanly: {stop_error}") from stop_error

    def read_pcm(self) -> bytes:
        with self._lock:
            return bytes(self._buffer)

    def _record_callback(self, indata, _frames: int, _time_info, status) -> None:
        if status:
            message = str(status)
            with self._lock:
                if message and message not in self._status_messages:
                    self._status_messages.append(message)
        if indata:
            with self._lock:
                self._buffer.extend(bytes(indata))


def _candidate_sample_rates(preferred_sample_rate: int) -> tuple[int, ...]:
    candidates = [preferred_sample_rate, 48_000, 44_100, 32_000, 22_050, 16_000]
    unique_candidates: list[int] = []
    for sample_rate in candidates:
        if sample_rate > 0 and sample_rate not in unique_candidates:
            unique_candidates.append(sample_rate)
    return tuple(unique_candidates)


def _deduplicate_input_devices(devices: list[AudioInputDevice]) -> list[AudioInputDevice]:
    physical_devices: dict[str, list[AudioInputDevice]] = {}
    for device in devices:
        if _is_virtual_input_device(device.name):
            continue
        key = _physical_input_device_key(device.name)
        physical_devices.setdefault(key, []).append(device)

    deduplicated = [_preferred_input_device(group) for group in physical_devices.values()]
    return sorted(deduplicated, key=lambda device: (not device.is_default, device.name.casefold(), device.index))


def _preferred_input_device(devices: list[AudioInputDevice]) -> AudioInputDevice:
    preferred = min(
        devices,
        key=lambda device: (_host_api_priority(device.host_api), not device.is_default, device.index),
    )
    if preferred.is_default == any(device.is_default for device in devices):
        return preferred
    return AudioInputDevice(
        index=preferred.index,
        name=preferred.name,
        host_api=preferred.host_api,
        max_input_channels=preferred.max_input_channels,
        default_sample_rate=preferred.default_sample_rate,
        is_default=True,
    )


def _physical_input_device_key(name: str) -> str:
    name = re.sub(r"\s+", " ", name.strip().casefold())
    name = re.sub(r"\s*\(.*$", "", name)
    return re.sub(r"[^a-z0-9]+", " ", name).strip() or name


def _is_virtual_input_device(name: str) -> bool:
    normalized = name.casefold()
    ignored_fragments = (
        "microsoft sound mapper",
        "primary sound capture",
        "stereo mix",
        "pc speaker",
    )
    return any(fragment in normalized for fragment in ignored_fragments)


def _host_api_priority(host_api: str) -> int:
    normalized = host_api.casefold()
    if "wasapi" in normalized:
        return 0
    if "directsound" in normalized:
        return 1
    if "mme" in normalized:
        return 2
    if "wdm" in normalized:
        return 3
    return 4


def _default_input_device_index(sd) -> int | None:
    try:
        default_devices = sd.default.device
        default_input = default_devices[0]
    except Exception:
        return None
    try:
        default_index = int(default_input)
    except (TypeError, ValueError):
        return None
    return default_index if default_index >= 0 else None


def _load_sounddevice():
    if _sounddevice is None:
        raise AudioRecorderError("sounddevice is not installed. Reinstall the main app requirements.")
    return _sounddevice
