import ctypes
import os
import sys

from voicebridge.app_paths import resource_path
from voicebridge.constants import APP_ICON_PNG, APP_NAME


def should_force_100_percent_dpi(display_size: tuple[int, int] | None, dpi: int | None) -> bool:
    return display_size == (1920, 1080) and dpi is not None and dpi > 100


def primary_display_size_windows() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None

    cch_device_name = 32
    cch_form_name = 32
    enum_current_settings = -1

    class DevModeW(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", ctypes.c_wchar * cch_device_name),
            ("dmSpecVersion", ctypes.c_ushort),
            ("dmDriverVersion", ctypes.c_ushort),
            ("dmSize", ctypes.c_ushort),
            ("dmDriverExtra", ctypes.c_ushort),
            ("dmFields", ctypes.c_uint),
            ("dmOrientation", ctypes.c_short),
            ("dmPaperSize", ctypes.c_short),
            ("dmPaperLength", ctypes.c_short),
            ("dmPaperWidth", ctypes.c_short),
            ("dmScale", ctypes.c_short),
            ("dmCopies", ctypes.c_short),
            ("dmDefaultSource", ctypes.c_short),
            ("dmPrintQuality", ctypes.c_short),
            ("dmColor", ctypes.c_short),
            ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short),
            ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short),
            ("dmFormName", ctypes.c_wchar * cch_form_name),
            ("dmLogPixels", ctypes.c_ushort),
            ("dmBitsPerPel", ctypes.c_uint),
            ("dmPelsWidth", ctypes.c_uint),
            ("dmPelsHeight", ctypes.c_uint),
            ("dmDisplayFlags", ctypes.c_uint),
            ("dmDisplayFrequency", ctypes.c_uint),
            ("dmICMMethod", ctypes.c_uint),
            ("dmICMIntent", ctypes.c_uint),
            ("dmMediaType", ctypes.c_uint),
            ("dmDitherType", ctypes.c_uint),
            ("dmReserved1", ctypes.c_uint),
            ("dmReserved2", ctypes.c_uint),
            ("dmPanningWidth", ctypes.c_uint),
            ("dmPanningHeight", ctypes.c_uint),
        ]

    dev_mode = DevModeW()
    dev_mode.dmSize = ctypes.sizeof(DevModeW)
    if not ctypes.windll.user32.EnumDisplaySettingsW(None, enum_current_settings, ctypes.byref(dev_mode)):
        return None
    return int(dev_mode.dmPelsWidth), int(dev_mode.dmPelsHeight)


def primary_display_dpi_windows() -> int | None:
    if sys.platform != "win32":
        return None

    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32 = ctypes.windll.user32
    try:
        monitor = user32.MonitorFromPoint(Point(0, 0), 1)
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        if ctypes.windll.shcore.GetDpiForMonitor(monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
            return int(dpi_x.value)
    except (AttributeError, OSError):
        pass

    hdc = user32.GetDC(None)
    if not hdc:
        return None
    try:
        log_pixels_x = 88
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, log_pixels_x)
    finally:
        user32.ReleaseDC(None, hdc)
    return int(dpi) if dpi else None


def apply_1080p_high_dpi_workaround() -> None:
    if sys.platform != "win32" or os.environ.get("VOICEBRIDGE_DISABLE_DPI_FIX") == "1":
        return

    display_size = primary_display_size_windows()
    dpi = primary_display_dpi_windows()
    if not should_force_100_percent_dpi(display_size, dpi):
        return

    # Temporary usability workaround for 1080p laptop panels at 125-150% Windows scaling.
    # This must run before QApplication imports/initialization so Qt lays out at 100%.
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    os.environ["QT_SCALE_FACTOR"] = "1"
    os.environ["QT_SCREEN_SCALE_FACTORS"] = "1"
    os.environ["QT_FONT_DPI"] = "96"


def main():
    apply_1080p_high_dpi_workaround()

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from voicebridge.main_window import VoiceBridgeQt

    app = QApplication([])
    app.setApplicationName(APP_NAME)
    icon_path = resource_path(APP_ICON_PNG)
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = VoiceBridgeQt()
    window.showMaximized()
    app.exec()


if __name__ == "__main__":
    main()
