"""The always-on-top answer overlay."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ai.schema import Answer
from app.config import POSITION_BOTTOM, AppConfig

log = logging.getLogger(__name__)

STATE_IDLE = "idle"
STATE_BUSY = "busy"
STATE_ANSWER = "answer"
STATE_ERROR = "error"

_EDGE_MARGIN = 48


class AnswerOverlay(QWidget):
    """Compact, frameless, translucent window that shows one answer at a time."""

    closed = Signal()

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config = config
        self.state = STATE_IDLE
        self._answer: Optional[Answer] = None
        self._drag_offset = None

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Screen AI Analyzer")

        self._build_ui()
        self.apply_config(config)

    # -- construction -----------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame(self)
        self.card.setObjectName("card")
        outer.addWidget(self.card)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        self.title_label = QLabel("Screen AI", self.card)
        self.title_label.setObjectName("title")
        self.meta_label = QLabel("", self.card)
        self.meta_label.setObjectName("meta")
        header.addWidget(self.title_label)
        header.addStretch(1)
        header.addWidget(self.meta_label)

        self.copy_button = QPushButton("Copy", self.card)
        self.copy_button.setObjectName("copyButton")
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.clicked.connect(self.copy_answer)
        self.copy_button.setEnabled(False)

        self.close_button = QPushButton("Close", self.card)
        self.close_button.setObjectName("closeButton")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.close_overlay)

        header.addWidget(self.copy_button)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        self.body_label = QLabel("", self.card)
        self.body_label.setObjectName("body")
        self.body_label.setWordWrap(True)
        self.body_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body_label.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.body_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.scroll = QScrollArea(self.card)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.body_label)
        layout.addWidget(self.scroll)

    # -- configuration ----------------------------------------------------
    def apply_config(self, config: AppConfig) -> None:
        self.config = config
        self.setWindowOpacity(config.opacity)
        size = config.font_size
        self.card.setStyleSheet(
            f"""
            QFrame#card {{
                background-color: rgba(22, 24, 30, 235);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 10px;
            }}
            QLabel#title {{
                color: rgba(150, 200, 255, 230);
                font-size: {max(7, size - 1)}pt;
                font-weight: 600;
            }}
            QLabel#meta {{
                color: rgba(200, 200, 200, 160);
                font-size: {max(7, size - 2)}pt;
            }}
            QLabel#body {{
                color: rgba(240, 240, 240, 245);
                font-size: {size}pt;
            }}
            QPushButton {{
                color: rgba(240, 240, 240, 235);
                background-color: rgba(255, 255, 255, 26);
                border: none;
                border-radius: 5px;
                padding: 2px 10px;
                font-size: {max(7, size - 2)}pt;
            }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 46); }}
            QPushButton:disabled {{ color: rgba(240, 240, 240, 90); }}
            """
        )
        self._resize_to_content()

    def _target_width(self) -> int:
        geometry = self._screen_geometry()
        return max(320, int(geometry.width() * self.config.overlay_width_ratio))

    def _screen_geometry(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def hide_for_capture(self) -> None:
        """The overlay must never appear inside the screenshot."""
        self.hide()

    # -- content ----------------------------------------------------------
    def show_busy(self, message: str = "Analyzing…") -> None:
        self.state = STATE_BUSY
        self._answer = None
        self.copy_button.setEnabled(False)
        self.meta_label.setText("")
        self._set_body(message)
        self.present()

    def show_answer(self, answer: Answer) -> None:
        self.state = STATE_ANSWER
        self._answer = answer
        self.copy_button.setEnabled(True)
        self.copy_button.setText("Copy")
        meta = [answer.provider] if answer.provider else []
        if answer.confidence:
            meta.append(f"{answer.confidence:.0%}")
        self.meta_label.setText(" · ".join(meta))
        self._set_body(self.format_answer(answer))
        self.present()

    def show_error(self, message: str) -> None:
        self.state = STATE_ERROR
        self._answer = None
        self.copy_button.setEnabled(False)
        self.meta_label.setText("")
        self._set_body(f"Unable to analyze screen:\n{message}")
        self.present()

    @staticmethod
    def format_answer(answer: Answer) -> str:
        lines = []
        if answer.question:
            lines.append(f"Q: {answer.question}")
        body = answer.answer
        if answer.answer_text and answer.answer_text.strip() != answer.answer.strip():
            body = f"{answer.answer} — {answer.answer_text}"
        lines.append(f"Answer:\n{body}")
        if answer.explanation:
            lines.append(answer.explanation)
        return "\n\n".join(lines)

    def _set_body(self, text: str) -> None:
        self.body_label.setText(text)
        self._resize_to_content()

    # -- geometry ---------------------------------------------------------
    def _resize_to_content(self) -> None:
        width = self._target_width()
        inner_width = width - 24  # card margins
        self.body_label.setFixedWidth(inner_width)
        content_height = self.body_label.heightForWidth(inner_width)
        if content_height <= 0:
            content_height = self.body_label.sizeHint().height()

        chrome = self.copy_button.sizeHint().height() + 30
        max_height = int(self._screen_geometry().height() * self.config.overlay_max_height_ratio)
        height = min(content_height + chrome, max_height)
        height = max(height, chrome + 24)
        self.setFixedSize(width, int(height))
        self._reposition()

    def _reposition(self) -> None:
        geometry = self._screen_geometry()
        x = geometry.x() + (geometry.width() - self.width()) // 2
        if self.config.overlay_position == POSITION_BOTTOM:
            y = geometry.y() + geometry.height() - self.height() - _EDGE_MARGIN
        else:
            y = geometry.y() + _EDGE_MARGIN
        self.move(x, max(geometry.y(), y))

    def present(self) -> None:
        """Show (or re-show) the overlay on top without going fullscreen."""
        self.show()
        self.raise_()
        self.activateWindow()

    # -- actions ----------------------------------------------------------
    def copy_answer(self) -> bool:
        """Copy only the answer text - never the JSON envelope."""
        if self._answer is None:
            return False
        text = self._answer.clipboard_text()
        if not text:
            return False
        clipboard = QGuiApplication.clipboard() or QApplication.clipboard()
        clipboard.setText(text)
        self.copy_button.setText("Copied")
        QTimer.singleShot(1200, lambda: self.copy_button.setText("Copy"))
        log.info("Answer copied to clipboard (%d chars)", len(text))
        return True

    def close_overlay(self) -> None:
        self.hide()
        self.state = STATE_IDLE
        self.closed.emit()

    # -- events -----------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt naming)
        if event.key() == Qt.Key.Key_Escape:
            self.close_overlay()
            event.accept()
            return
        if event.key() == Qt.Key.Key_C and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.copy_answer()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_offset = None
        event.accept()
