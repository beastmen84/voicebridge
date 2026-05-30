from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget


class Card(QFrame):
    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.content_layout: QVBoxLayout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(18, 14, 18, 14)
        self.content_layout.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("CardTitle")
            self.content_layout.addWidget(label)


class FilePicker(QWidget):
    def __init__(self, label, button_text="Browse...", parent=None):
        super().__init__(parent)
        self.setObjectName("FilePicker")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setColumnStretch(0, 1)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(5)

        self.label = QLabel(label)
        self.label.setObjectName("FieldLabel")
        self.edit = QLineEdit()
        self.button = QPushButton(button_text)
        self.button.setObjectName("SecondaryButton")
        self.edit.setMinimumHeight(34)
        self.button.setMinimumHeight(34)

        layout.addWidget(self.label, 0, 0, 1, 2)
        layout.addWidget(self.edit, 1, 0)
        layout.addWidget(self.button, 1, 1)

    def text(self):
        return self.edit.text().strip()

    def set_text(self, value):
        self.edit.setText(value or "")
