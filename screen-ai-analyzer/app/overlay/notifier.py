"""Headless output sink: clipboard + a normal desktop notification.

Nothing is drawn on the screen by the application itself - the answer goes to
the clipboard and the desktop's own notification daemon says it is ready.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from typing import Optional

from PySide6.QtGui import QGuiApplication

from app.ai.schema import Answer
from app.config import AppConfig

log = logging.getLogger(__name__)

APP_NAME = "Screen AI Analyzer"
ICON = "dialog-information"

#: Notification bodies get elided; the full text is on the clipboard.
MAX_BODY_CHARS = 220


def notify_send_available() -> bool:
    return shutil.which("notify-send") is not None


def _notify_send(title: str, body: str, timeout_ms: int = 6000, urgency: str = "normal") -> bool:
    if not notify_send_available():
        return False
    try:
        subprocess.run(
            [
                "notify-send",
                "--app-name",
                APP_NAME,
                "--icon",
                ICON,
                "--expire-time",
                str(timeout_ms),
                "--urgency",
                urgency,
                title,
                body,
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return True
    except Exception as exc:  # pragma: no cover - depends on the desktop
        log.warning("notify-send failed: %s", exc)
        return False


def elide(text: str, limit: int = MAX_BODY_CHARS) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class NotificationSink:
    """Same interface as the overlay, but without any window on screen."""

    def __init__(self, config: AppConfig, tray=None) -> None:
        self.config = config
        self.tray = tray  # QSystemTrayIcon, used when notify-send is missing
        self.state = "idle"
        self.last_answer: Optional[Answer] = None

    # -- sink interface ---------------------------------------------------
    def hide_for_capture(self) -> None:
        """Nothing is shown, so there is nothing to hide before the grab."""

    def show_busy(self, message: str = "Analyzing…") -> None:
        self.state = "busy"
        self.last_answer = None
        if self.config.notify_on_start:
            self._notify(APP_NAME, message, timeout_ms=2000)

    def show_answer(self, answer: Answer) -> None:
        self.state = "answer"
        self.last_answer = answer
        copied = self.copy_answer()
        title = "Answer copied" if copied else "Answer ready"
        self._notify(title, elide(self.notification_body(answer)))
        log.info("Answer delivered via notification (provider %s)", answer.provider)

    def show_error(self, message: str) -> None:
        self.state = "error"
        self.last_answer = None
        self._notify("Unable to analyze screen", elide(message), urgency="critical")

    def apply_config(self, config: AppConfig) -> None:
        self.config = config

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def notification_body(answer: Answer) -> str:
        body = answer.answer
        if answer.answer_text and answer.answer_text.strip() != answer.answer.strip():
            body = f"{answer.answer} — {answer.answer_text}"
        if answer.explanation:
            body = f"{body}\n{answer.explanation}"
        return body

    def copy_answer(self) -> bool:
        """Put only the answer text on the clipboard (never the JSON)."""
        if self.last_answer is None:
            return False
        text = self.last_answer.clipboard_text()
        if not text:
            return False
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:  # pragma: no cover - no GUI at all
            return False
        clipboard.setText(text)
        return True

    def _notify(self, title: str, body: str, timeout_ms: int = 6000, urgency: str = "normal") -> bool:
        if _notify_send(title, body, timeout_ms, urgency):
            return True
        if self.tray is not None:
            try:
                self.tray.showMessage(title, body, self.tray.icon(), timeout_ms)
                return True
            except Exception:  # pragma: no cover
                log.warning("Tray notification failed")
        log.info("Notification (no daemon available): %s — %s", title, body)
        return False
