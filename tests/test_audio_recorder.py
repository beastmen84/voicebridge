from types import SimpleNamespace

from voicebridge import audio_recorder
from voicebridge.audio_recorder import AudioRecordingSettings, SoundDevicePcmRecorder


class FakeSoundDevice:
    def __init__(self) -> None:
        self.default = SimpleNamespace(device=[2, -1])
        self.checked_sample_rates: list[int] = []
        self.last_stream = None

    @staticmethod
    def query_hostapis():
        return [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}]

    @staticmethod
    def query_devices():
        return [
            {"name": "Speakers", "max_input_channels": 0, "hostapi": 0, "default_samplerate": 48_000},
            {
                "name": "Microsoft Sound Mapper - Input",
                "max_input_channels": 2,
                "hostapi": 0,
                "default_samplerate": 48_000,
            },
            {
                "name": "Primary Sound Capture Driver",
                "max_input_channels": 2,
                "hostapi": 1,
                "default_samplerate": 48_000,
            },
            {"name": "USB Mic", "max_input_channels": 1, "hostapi": 0, "default_samplerate": 48_000},
            {"name": "USB Mic", "max_input_channels": 1, "hostapi": 2, "default_samplerate": 48_000},
            {"name": "Stereo Mix", "max_input_channels": 2, "hostapi": 2, "default_samplerate": 48_000},
            {"name": "Studio Mic", "max_input_channels": 2, "hostapi": 0, "default_samplerate": 44_100},
            {"name": "Studio Mic", "max_input_channels": 2, "hostapi": 1, "default_samplerate": 44_100},
            {"name": "Studio Mic", "index": 2, "max_input_channels": 2, "hostapi": 2, "default_samplerate": 48_000},
        ]

    def check_input_settings(self, *, device, channels, samplerate, dtype) -> None:
        self.checked_sample_rates.append(samplerate)
        assert device == 2
        assert channels == 1
        assert dtype == "int16"
        if samplerate != 48_000:
            raise ValueError("unsupported sample rate")

    def RawInputStream(self, **kwargs):
        stream = FakeRawInputStream(**kwargs)
        self.last_stream = stream
        return stream


class FakeRawInputStream:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


def test_list_input_devices_returns_inputs_with_default_first(monkeypatch) -> None:
    fake = FakeSoundDevice()
    monkeypatch.setattr(audio_recorder, "_sounddevice", fake)

    devices = audio_recorder.list_input_devices()

    assert [device.name for device in devices] == ["Studio Mic", "USB Mic"]
    assert devices[0].index == 2
    assert devices[0].host_api == "Windows WASAPI"
    assert devices[0].is_default is True
    assert devices[1].host_api == "Windows WASAPI"


def test_select_input_settings_falls_back_to_supported_sample_rate(monkeypatch) -> None:
    fake = FakeSoundDevice()
    monkeypatch.setattr(audio_recorder, "_sounddevice", fake)

    settings = audio_recorder.select_input_settings(2, preferred_sample_rate=24_000, channel_count=1)

    assert settings == AudioRecordingSettings(sample_rate=48_000, channel_count=1)
    assert fake.checked_sample_rates == [24_000, 48_000]


def test_sounddevice_pcm_recorder_buffers_raw_pcm(monkeypatch) -> None:
    fake = FakeSoundDevice()
    monkeypatch.setattr(audio_recorder, "_sounddevice", fake)
    recorder = SoundDevicePcmRecorder(2, AudioRecordingSettings(sample_rate=24_000, channel_count=1))

    recorder.start()
    assert fake.last_stream.started is True
    fake.last_stream.kwargs["callback"](b"\x01\x00\x02\x00", 2, None, "input overflow")
    recorder.stop()

    assert recorder.read_pcm() == b"\x01\x00\x02\x00"
    assert recorder.status_messages == ("input overflow",)
    assert fake.last_stream.stopped is True
    assert fake.last_stream.closed is True
