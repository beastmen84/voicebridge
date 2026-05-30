from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from voicebridge.pages.home import HomePageMixin


class PageBuilderMixin(HomePageMixin):
    @staticmethod
    def nav_button(text: str, callback: Callable[[], None]) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("NavButton")
        button.clicked.connect(callback)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def show_page(self, index):
        if self.is_converting or self.is_stt_running or self.is_video_running or self.is_cleanup_running:
            return
        self.stack.setCurrentIndex(index)
        for button, active in (
            (self.nav_home, index == 0),
            (self.nav_tts, index == 1),
            (self.nav_stt, index == 2),
            (self.nav_video, index == 3),
            (self.nav_cleanup, index == 4),
        ):
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)
        if index == 2:
            self.refresh_stt_preflight_async()
        if index == 3:
            self.sync_video_subtitle_inputs_from_stt()

    def update_navigation_state(self):
        if not hasattr(self, "nav_home"):
            return
        enabled = not (self.is_converting or self.is_stt_running or self.is_video_running or self.is_cleanup_running)
        for button in (self.nav_home, self.nav_tts, self.nav_stt, self.nav_video, self.nav_cleanup):
            button.setEnabled(enabled)

    @staticmethod
    def page_container():
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(16)
        scroll.setWidget(page)
        return scroll, layout

    @staticmethod
    def page_header(layout, badge, title, subtitle, badge_name):
        header = QVBoxLayout()
        header.setSpacing(4)
        badge_label = QLabel(badge)
        badge_label.setObjectName(badge_name)
        title_label = QLabel(title)
        title_label.setObjectName("PageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("PageSubtitle")
        subtitle_label.setWordWrap(True)
        header.addWidget(badge_label)
        header.addWidget(title_label)
        header.addWidget(subtitle_label)
        layout.addLayout(header)
