from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

LOCAL_VOICES_TAB_PROFILES = 0
LOCAL_VOICES_TAB_DATASETS = 1
LOCAL_VOICES_TAB_MODELING = 2


class LocalVoicesWorkflowMixin:
    def show_local_voices_tab(self, tab_index: int = LOCAL_VOICES_TAB_PROFILES) -> None:
        self.show_page(2)
        if hasattr(self, "local_voice_tabs"):
            self.local_voice_tabs.setCurrentIndex(tab_index)

    def build_local_voices_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(16)
        self.page_header(
            layout,
            "LOCAL",
            "Local Voices",
            "Manage local voice profiles, collect modeling datasets and configure XTTS-v2 training.",
            "BadgeGreen",
        )

        self.local_voice_tabs = QTabWidget()
        self.local_voice_tabs.setObjectName("WorkspaceTabs")
        self.local_voice_tabs.addTab(self.build_voice_profiles_page(include_header=False), "Profiles")
        self.local_voice_tabs.addTab(self.build_modeling_datasets_page(include_header=False), "Datasets")
        self.local_voice_tabs.addTab(self.build_voice_modeling_page(include_header=False), "Modeling")
        layout.addWidget(self.local_voice_tabs, 1)
        return page
