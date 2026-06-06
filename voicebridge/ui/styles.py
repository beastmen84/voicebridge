def apply_app_style(widget, check_icon, chevron_icon):
    widget.setStyleSheet(
        """
        QMainWindow, QWidget { background: #f4f6f8; color: #111827; font-family: "Segoe UI"; font-size: 10pt; }
        QLabel, QCheckBox { background: transparent; }
        QScrollArea { background: #f4f6f8; border: 0; }
        QScrollArea > QWidget > QWidget { background: #f4f6f8; }
        QScrollBar:vertical {
            background: transparent;
            width: 10px;
            margin: 6px 2px 6px 0;
        }
        QScrollBar::handle:vertical {
            background: #b8c2d1;
            border-radius: 4px;
            min-height: 36px;
        }
        QScrollBar::handle:vertical:hover { background: #8f9caf; }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            background: transparent;
            border: 0;
            height: 0;
        }
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {
            background: transparent;
        }
        QScrollBar:horizontal {
            background: transparent;
            height: 10px;
            margin: 0 6px 2px 6px;
        }
        QScrollBar::handle:horizontal {
            background: #b8c2d1;
            border-radius: 4px;
            min-width: 36px;
        }
        QScrollBar::handle:horizontal:hover { background: #8f9caf; }
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {
            background: transparent;
            border: 0;
            width: 0;
        }
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {
            background: transparent;
        }
        QCheckBox { spacing: 8px; }
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1px solid #98a2b3;
            background: #ffffff;
        }
        QCheckBox::indicator:hover { border-color: #2f6fed; }
        QCheckBox::indicator:checked {
            background: #2f6fed;
            border: 1px solid #2f6fed;
            image: url("__CHECK_ICON__");
        }
        QCheckBox::indicator:disabled {
            background: #eef1f5;
            border-color: #cfd6e2;
        }
        #Sidebar { background: #101827; border: none; }
        #Sidebar QLabel { background: transparent; }
        #AppTitle { color: white; font-size: 18pt; font-weight: 700; }
        #AppSubtitle { color: #aab4c4; }
        #SidebarSection { color: #aab4c4; font-size: 8pt; font-weight: 800; }
        #SidebarStatus { background: transparent; }
        #StatusTile {
            border: 1px solid #445269;
            border-radius: 6px;
            padding: 5px 4px;
            min-height: 34px;
            font-size: 8pt;
            font-weight: 800;
        }
        #StatusTile[state="ok"] { background: #123a31; border-color: #21a67a; color: #d1fae5; }
        #StatusTile[state="warn"] { background: #3a2a12; border-color: #d99020; color: #fdecc8; }
        #StatusTile[state="bad"] { background: #3b1717; border-color: #d14343; color: #fee2e2; }
        #StatusTile[state="info"] { background: #1c2637; border-color: #445269; color: #d5dce8; }
        QPushButton { padding: 8px 12px; border-radius: 6px; border: 1px solid #cfd6e2; background: #ffffff; }
        QPushButton:hover { background: #f1f5fb; border-color: #aeb9c8; }
        QPushButton:disabled { color: #98a2b3; background: #eef1f5; }
        #PrimaryButton { color: white; background: #2f6fed; border-color: #2f6fed; font-weight: 600; }
        #PrimaryButton:hover { background: #265ecb; }
        #PrimaryButton:disabled { color: #98a2b3; background: #eef1f5; border-color: #cfd6e2; }
        #FlowButton { color: white; background: #1f8a5b; border-color: #1f8a5b; font-weight: 700; }
        #FlowButton:hover { background: #18734c; border-color: #18734c; }
        #FlowButton:disabled { color: #98a2b3; background: #eef1f5; border-color: #cfd6e2; }
        #DangerButton { color: white; background: #b42318; border-color: #b42318; font-weight: 600; }
        #DangerButton:disabled { color: #98a2b3; background: #eef1f5; border-color: #cfd6e2; }
        #HeaderHelpButton {
            color: #aab4c4;
            background: transparent;
            border: 1px solid #445269;
            border-radius: 999px;
            padding: 4px 8px;
            font-size: 8pt;
            font-weight: 700;
        }
        #HeaderHelpButton:hover { color: #ffffff; background: #1c2637; border-color: #617083; }
        QToolButton#InlineDangerButton {
            color: #b42318;
            background: transparent;
            border: 0;
            border-radius: 4px;
            font-size: 11pt;
            font-weight: 800;
            min-width: 20px;
            min-height: 20px;
            max-width: 20px;
            max-height: 20px;
            padding: 0;
        }
        QToolButton#InlineDangerButton:hover { background: #fee2e2; }
        #SecondaryButton { background: #f8fafc; }
        #SegmentButton {
            background: #f8fafc;
            border: 1px solid #cfd6e2;
            padding: 8px 12px;
            font-weight: 600;
        }
        #SegmentButton:hover { background: #edf3ff; border-color: #aeb9c8; }
        #SegmentButton:checked { background: #2f6fed; border-color: #2f6fed; color: #ffffff; }
        #NavButton { color: #d5dce8; background: transparent; border: 0; text-align: left; padding: 10px 12px; }
        #NavButton:hover { background: #1c2637; }
        #NavButton[active="true"] { background: #2f6fed; color: white; font-weight: 600; }
        QTabWidget#WorkspaceTabs::pane { border: 0; background: transparent; top: -1px; }
        QTabWidget#WorkspaceTabs QTabBar::tab {
            background: #ffffff;
            border: 1px solid #cfd6e2;
            border-bottom-color: #d8dee8;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            padding: 8px 18px;
            margin-right: 4px;
            font-weight: 650;
            color: #617083;
        }
        QTabWidget#WorkspaceTabs QTabBar::tab:hover {
            background: #f1f5fb;
            color: #1f2937;
        }
        QTabWidget#WorkspaceTabs QTabBar::tab:selected {
            background: #eef8f5;
            border-color: #b8ddd5;
            color: #1f5f54;
        }
        #Card { background: #ffffff; border: 1px solid #d8dee8; border-radius: 8px; }
        #HomeCard { background: #ffffff; border: 1px solid #d8dee8; border-radius: 8px; }
        #Card QLabel, #HomeCard QLabel, #InlinePanel { background: transparent; }
        #VerticalSeparator { color: #d8dee8; margin: 4px 6px; }
        #FilePicker { background: transparent; }
        #CardTitle { font-size: 13pt; font-weight: 700; }
        #PageTitle { font-size: 21pt; font-weight: 750; }
        #PageSubtitle, #Muted, #StatusText { color: #617083; }
        #FieldLabel { color: #1f2937; font-weight: 650; }
        #BadgeBlue { color: #2f6fed; font-weight: 800; letter-spacing: 1px; }
        #BadgeGreen { color: #00856f; font-weight: 800; letter-spacing: 1px; }
        #WarningBox { background: #fff7e6; border: 1px solid #f1c36d; border-radius: 8px; }
        #GoodBox { background: #eef8f5; border: 1px solid #b8ddd5; border-radius: 8px; color: #1f5f54; }
        #LogBox { background: #111827; color: #e5e7eb; border-radius: 8px; border: 1px solid #111827; }
        QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QListWidget {
            background: white; border: 1px solid #cfd6e2; border-radius: 6px; padding: 6px;
        }
        QComboBox {
            padding: 6px 34px 6px 8px;
            min-height: 22px;
            selection-background-color: #eaf1ff;
            selection-color: #111827;
        }
        QSpinBox {
            padding: 6px 8px;
            min-height: 22px;
            selection-background-color: #eaf1ff;
            selection-color: #111827;
        }
        QSpinBox::up-button,
        QSpinBox::down-button {
            width: 0;
            border: 0;
        }
        QComboBox:hover { border-color: #aeb9c8; }
        QComboBox:on { border-color: #2f6fed; }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 30px;
            border-left: 1px solid #e4e8ef;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
            background: #f8fafc;
        }
        QComboBox::drop-down:hover { background: #edf3ff; }
        QComboBox::down-arrow {
            image: url("__CHEVRON_ICON__");
            width: 14px;
            height: 14px;
        }
        QComboBox QAbstractItemView {
            background: #ffffff;
            border: 1px solid #cfd6e2;
            border-radius: 6px;
            padding: 4px;
            outline: 0;
            selection-background-color: #eaf1ff;
            selection-color: #111827;
        }
        QComboBox QAbstractItemView::item {
            min-height: 28px;
            padding: 6px 8px;
        }
        QProgressBar {
            border: 1px solid #cfd6e2;
            border-radius: 7px;
            height: 16px;
            background: #edf1f5;
            text-align: center;
            color: #1f2937;
            font-size: 8pt;
            font-weight: 650;
        }
        QProgressBar::chunk { background: #2f6fed; border-radius: 6px; }
        """
        .replace("__CHECK_ICON__", check_icon)
        .replace("__CHEVRON_ICON__", chevron_icon)
    )
