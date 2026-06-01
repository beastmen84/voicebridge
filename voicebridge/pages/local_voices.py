from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from voicebridge.modeling_datasets import modeling_dataset_exports_root
from voicebridge.voice_modeling import validate_voice_modeling_export
from voicebridge.voice_profiles import VOICE_PROFILE_MODELING

LOCAL_VOICES_TAB_PROFILES = 0
LOCAL_VOICES_TAB_DATASETS = 1
LOCAL_VOICES_TAB_MODELING = 2


class LocalVoicesWorkflowMixin:
    def show_local_voices_tab(self, tab_index: int = LOCAL_VOICES_TAB_PROFILES) -> None:
        self.show_page(2)
        if hasattr(self, "local_voice_tabs"):
            self.update_local_voice_tabs()
            if self.local_voice_tabs.isTabEnabled(tab_index):
                self.local_voice_tabs.setCurrentIndex(tab_index)

    def has_modeling_voice_profiles(self) -> bool:
        return any(profile.get("profile_type") == VOICE_PROFILE_MODELING for profile in self.voice_profiles)

    def has_voice_modeling_exports(self) -> bool:
        exports_root = modeling_dataset_exports_root()
        if not exports_root.is_dir():
            return False
        try:
            export_dirs = list(exports_root.iterdir())
        except OSError:
            return False
        for export_dir in export_dirs:
            if not export_dir.is_dir():
                continue
            try:
                validate_voice_modeling_export(export_dir)
            except (OSError, ValueError):
                continue
            return True
        return False

    def update_local_voice_tabs(self) -> None:
        if not hasattr(self, "local_voice_tabs"):
            return
        datasets_enabled = self.has_modeling_voice_profiles()
        modeling_enabled = self.has_voice_modeling_exports()
        self.local_voice_tabs.setTabEnabled(LOCAL_VOICES_TAB_DATASETS, datasets_enabled)
        self.local_voice_tabs.setTabEnabled(LOCAL_VOICES_TAB_MODELING, modeling_enabled)
        self.local_voice_tabs.setTabToolTip(
            LOCAL_VOICES_TAB_DATASETS,
            "" if datasets_enabled else "Create a Modeling dataset profile first.",
        )
        self.local_voice_tabs.setTabToolTip(
            LOCAL_VOICES_TAB_MODELING,
            "" if modeling_enabled else "Export a usable dataset first.",
        )
        if not self.local_voice_tabs.isTabEnabled(self.local_voice_tabs.currentIndex()):
            fallback_tab = LOCAL_VOICES_TAB_DATASETS if datasets_enabled else LOCAL_VOICES_TAB_PROFILES
            self.local_voice_tabs.setCurrentIndex(fallback_tab)

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
        self.update_local_voice_tabs()
        return page
