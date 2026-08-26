"""Small control window: the alternative to the global hotkey."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ControlWindow(QWidget):
    """Always available way to start a capture, even without a global hotkey."""

    capture_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, hotkey: str = "F8", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Screen AI Analyzer")
        self.setMinimumWidth(340)

        layout = QVBoxLayout(self)
        self.capture_button = QPushButton(f"Capture & Analyze  ({hotkey})", self)
        self.capture_button.setMinimumHeight(38)
        self.capture_button.clicked.connect(self.capture_requested.emit)
        layout.addWidget(self.capture_button)

        row = QHBoxLayout()
        settings_button = QPushButton("Settings", self)
        settings_button.clicked.connect(self.settings_requested.emit)
        quit_button = QPushButton("Quit", self)
        quit_button.clicked.connect(self.quit_requested.emit)
        row.addWidget(settings_button)
        row.addWidget(quit_button)
        layout.addLayout(row)

        self.status_label = QLabel("", self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def set_hotkey(self, hotkey: str) -> None:
        self.capture_button.setText(f"Capture & Analyze  ({hotkey})")
