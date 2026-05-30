from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from voicebridge.app_paths import resource_path
from voicebridge.constants import APP_ICON_PNG, APP_NAME
from voicebridge.main_window import VoiceBridgeQt


def main():
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    icon_path = resource_path(APP_ICON_PNG)
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = VoiceBridgeQt()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
