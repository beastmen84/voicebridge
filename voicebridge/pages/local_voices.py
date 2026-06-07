from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from voicebridge.i18n import translate_ui
from voicebridge.voice_modeling import list_voice_modeling_exports, list_voice_modeling_job_configs
from voicebridge.voice_profiles import VOICE_PROFILE_MODELING

LOCAL_VOICES_TAB_PROFILES = 0
LOCAL_VOICES_TAB_DATASETS = 1
LOCAL_VOICES_TAB_SETUP = 2
LOCAL_VOICES_TAB_TRAINING = 3


def _ui_text(owner, key: str, **kwargs) -> str:
    translator = getattr(owner, "ui_text", None)
    if callable(translator):
        return translator(key, **kwargs)
    return translate_ui(key, **kwargs)


# noinspection PyAttributeOutsideInit,PyUnresolvedReferences,PyMethodMayBeStatic
class LocalVoicesWorkflowMixin:
    def eventFilter(self, watched, event):
        if (
            hasattr(self, "local_voice_tabs")
            and watched is self.local_voice_tabs.tabBar()
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            tab_index = watched.tabAt(event.pos())
            guarded_tabs = {
                LOCAL_VOICES_TAB_DATASETS: "local_voice_dataset_tab_open_allowed",
                LOCAL_VOICES_TAB_SETUP: "local_voice_setup_tab_open_allowed",
                LOCAL_VOICES_TAB_TRAINING: "local_voice_training_tab_open_allowed",
            }
            guard_name = guarded_tabs.get(tab_index)
            if guard_name and not getattr(self, guard_name, False):
                return True
        return super().eventFilter(watched, event)

    def open_local_voice_workflow_tab(self, tab_index: int) -> None:
        if tab_index == LOCAL_VOICES_TAB_DATASETS:
            self.local_voice_dataset_tab_open_allowed = True
        if tab_index == LOCAL_VOICES_TAB_SETUP:
            self.local_voice_setup_tab_open_allowed = True
        if tab_index == LOCAL_VOICES_TAB_TRAINING:
            self.local_voice_training_tab_open_allowed = True
        self.show_local_voices_tab(tab_index)

    def show_local_voices_tab(self, tab_index: int = LOCAL_VOICES_TAB_PROFILES) -> None:
        self.show_page(2)
        if hasattr(self, "local_voice_tabs"):
            self.update_local_voice_tabs()
            if self.local_voice_tabs.isTabEnabled(tab_index):
                self.local_voice_tabs.setCurrentIndex(tab_index)

    def has_modeling_voice_profiles(self) -> bool:
        return any(profile.get("profile_type") == VOICE_PROFILE_MODELING for profile in self.voice_profiles)

    def has_voice_modeling_exports(self) -> bool:
        return bool(list_voice_modeling_exports())

    def has_voice_training_jobs(self) -> bool:
        return bool(list_voice_modeling_job_configs())

    def update_local_voice_tabs(self) -> None:
        if not hasattr(self, "local_voice_tabs"):
            return
        datasets_enabled = self.has_modeling_voice_profiles()
        setup_enabled = self.has_voice_modeling_exports()
        training_enabled = self.has_voice_training_jobs()
        self.local_voice_tabs.setTabEnabled(LOCAL_VOICES_TAB_DATASETS, datasets_enabled)
        self.local_voice_tabs.setTabEnabled(LOCAL_VOICES_TAB_SETUP, setup_enabled)
        self.local_voice_tabs.setTabEnabled(LOCAL_VOICES_TAB_TRAINING, training_enabled)
        self.local_voice_tabs.setTabToolTip(
            LOCAL_VOICES_TAB_DATASETS,
            (
                _ui_text(self, "local_voices.tooltip.datasets_profile_only")
                if datasets_enabled
                else _ui_text(self, "local_voices.tooltip.datasets_disabled")
            ),
        )
        self.local_voice_tabs.setTabToolTip(
            LOCAL_VOICES_TAB_SETUP,
            "" if setup_enabled else _ui_text(self, "local_voices.tooltip.setup_disabled"),
        )
        self.local_voice_tabs.setTabToolTip(
            LOCAL_VOICES_TAB_TRAINING,
            "" if training_enabled else _ui_text(self, "local_voices.tooltip.training_disabled"),
        )
        if not self.local_voice_tabs.isTabEnabled(self.local_voice_tabs.currentIndex()):
            fallback_tab = (
                LOCAL_VOICES_TAB_DATASETS
                if datasets_enabled and getattr(self, "local_voice_dataset_tab_open_allowed", False)
                else LOCAL_VOICES_TAB_PROFILES
            )
            self.local_voice_tabs.setCurrentIndex(fallback_tab)

    def local_voice_tab_changed(self, tab_index: int) -> None:
        if tab_index == LOCAL_VOICES_TAB_DATASETS:
            if not getattr(self, "local_voice_dataset_tab_open_allowed", False):
                self.local_voice_tabs.setCurrentIndex(LOCAL_VOICES_TAB_PROFILES)
                return
            self.refresh_modeling_datasets_page()
        else:
            self.local_voice_dataset_tab_open_allowed = False
        if tab_index == LOCAL_VOICES_TAB_SETUP:
            if not getattr(self, "local_voice_setup_tab_open_allowed", False):
                self.local_voice_tabs.setCurrentIndex(LOCAL_VOICES_TAB_PROFILES)
                return
            self.refresh_voice_modeling_exports()
        else:
            self.local_voice_setup_tab_open_allowed = False
        if tab_index == LOCAL_VOICES_TAB_TRAINING:
            if not getattr(self, "local_voice_training_tab_open_allowed", False):
                self.local_voice_tabs.setCurrentIndex(LOCAL_VOICES_TAB_PROFILES)
                return
            self.refresh_voice_training_jobs()
        else:
            self.local_voice_training_tab_open_allowed = False

    def build_local_voices_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 26, 28, 24)
        layout.setSpacing(16)
        self.local_voices_title_label, self.local_voices_subtitle_label, _badge_label = self.page_header(
            layout,
            _ui_text(self, "local_voices.title"),
            _ui_text(self, "local_voices.subtitle"),
        )

        self.local_voice_tabs = QTabWidget()
        self.local_voice_tabs.setObjectName("WorkspaceTabs")
        self.local_voice_dataset_tab_open_allowed = False
        self.local_voice_setup_tab_open_allowed = False
        self.local_voice_training_tab_open_allowed = False
        self.local_voice_tabs.tabBar().installEventFilter(self)
        self.local_voice_tabs.addTab(
            self.build_voice_profiles_page(include_header=False),
            _ui_text(self, "local_voices.tab.profiles"),
        )
        self.local_voice_tabs.addTab(
            self.build_modeling_datasets_page(include_header=False),
            _ui_text(self, "local_voices.tab.datasets"),
        )
        self.local_voice_tabs.addTab(
            self.build_voice_modeling_page(include_header=False),
            _ui_text(self, "local_voices.tab.setup"),
        )
        self.local_voice_tabs.addTab(
            self.build_voice_training_page(include_header=False),
            _ui_text(self, "local_voices.tab.training"),
        )
        self.local_voice_tabs.currentChanged.connect(self.local_voice_tab_changed)
        layout.addWidget(self.local_voice_tabs, 1)
        self.update_local_voice_tabs()
        return page

    def retranslate_local_voices_page(self) -> None:
        if not hasattr(self, "local_voice_tabs"):
            return
        self.local_voices_title_label.setText(_ui_text(self, "local_voices.title"))
        self.local_voices_subtitle_label.setText(_ui_text(self, "local_voices.subtitle"))
        self.local_voice_tabs.setTabText(LOCAL_VOICES_TAB_PROFILES, _ui_text(self, "local_voices.tab.profiles"))
        self.local_voice_tabs.setTabText(LOCAL_VOICES_TAB_DATASETS, _ui_text(self, "local_voices.tab.datasets"))
        self.local_voice_tabs.setTabText(LOCAL_VOICES_TAB_SETUP, _ui_text(self, "local_voices.tab.setup"))
        self.local_voice_tabs.setTabText(LOCAL_VOICES_TAB_TRAINING, _ui_text(self, "local_voices.tab.training"))
        self.update_local_voice_tabs()
