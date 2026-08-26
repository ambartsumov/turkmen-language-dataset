"""Headless output: clipboard + desktop notification, nothing drawn on screen."""

import pytest
from PySide6.QtGui import QGuiApplication

from app.ai.schema import Answer
from app.config import OUTPUT_NOTIFICATION, OUTPUT_OVERLAY, AppConfig
from app.controller import build_sink
from app.overlay import notifier
from app.overlay.notifier import NotificationSink, elide


@pytest.fixture
def sent(monkeypatch):
    """Capture notify-send calls instead of talking to the notification daemon."""
    calls = []

    def fake_notify(title, body, timeout_ms=6000, urgency="normal"):
        calls.append({"title": title, "body": body, "urgency": urgency})
        return True

    monkeypatch.setattr(notifier, "_notify_send", fake_notify)
    return calls


@pytest.fixture
def sink(qapp, config, sent):
    return NotificationSink(config)


def test_notification_is_the_default_output_mode():
    assert AppConfig().output_mode == OUTPUT_NOTIFICATION


def test_build_sink_returns_notifier_by_default(qapp, config):
    assert isinstance(build_sink(config), NotificationSink)


def test_build_sink_returns_overlay_when_configured(qapp, config):
    from app.overlay.overlay import AnswerOverlay

    config.output_mode = OUTPUT_OVERLAY
    widget = build_sink(config)
    assert isinstance(widget, AnswerOverlay)
    widget.deleteLater()


def test_answer_is_copied_and_notified(sink, sent, sample_answer):
    QGuiApplication.clipboard().clear()
    sink.show_answer(sample_answer)

    assert QGuiApplication.clipboard().text() == "B. Paris"
    assert len(sent) == 1
    assert sent[0]["title"] == "Answer copied"
    assert "Paris" in sent[0]["body"]


def test_clipboard_never_contains_the_json_envelope(sink, sent, sample_answer):
    sink.show_answer(sample_answer)
    text = QGuiApplication.clipboard().text()
    assert "{" not in text and "confidence" not in text and "question" not in text


def test_long_answers_are_elided_in_the_notification_but_not_on_the_clipboard(sink, sent):
    long_text = "word " * 400
    sink.show_answer(Answer(question="q", answer=long_text, provider="openrouter"))

    assert len(sent[0]["body"]) <= notifier.MAX_BODY_CHARS
    assert sent[0]["body"].endswith("…")
    assert len(QGuiApplication.clipboard().text()) > notifier.MAX_BODY_CHARS


def test_nothing_is_drawn_on_screen(sink, sent, sample_answer):
    from PySide6.QtWidgets import QApplication

    before = list(QApplication.topLevelWidgets())
    sink.show_busy()
    sink.show_answer(sample_answer)
    assert list(QApplication.topLevelWidgets()) == before
    assert not hasattr(sink, "show")  # it is not a widget at all


def test_hide_for_capture_is_a_no_op(sink):
    sink.hide_for_capture()  # must not raise: there is no window to hide


def test_busy_is_silent_unless_enabled(sink, sent, config):
    sink.show_busy()
    assert sent == []

    config.notify_on_start = True
    sink.show_busy()
    assert len(sent) == 1 and "Analyzing" in sent[0]["body"]


def test_error_notification_is_critical_and_has_no_traceback(sink, sent):
    sink.show_error("gemini: quota exceeded")
    assert sent[0]["title"] == "Unable to analyze screen"
    assert sent[0]["urgency"] == "critical"
    assert "Traceback" not in sent[0]["body"]


def test_second_answer_replaces_the_clipboard_content(sink, sent, sample_answer):
    sink.show_answer(sample_answer)
    sink.show_answer(Answer(question="q2", answer="42", provider="openrouter"))
    assert QGuiApplication.clipboard().text() == "42"
    assert len(sent) == 2


def test_tray_is_used_when_notify_send_is_missing(qapp, config, monkeypatch, sample_answer):
    monkeypatch.setattr(notifier, "_notify_send", lambda *a, **k: False)
    shown = []

    class FakeTray:
        def icon(self):
            return None

        def showMessage(self, title, body, icon, timeout):
            shown.append((title, body))

    sink = NotificationSink(config, tray=FakeTray())
    sink.show_answer(sample_answer)
    assert shown and "Paris" in shown[0][1]


def test_missing_notification_daemon_does_not_break_the_flow(qapp, config, monkeypatch, sample_answer):
    monkeypatch.setattr(notifier, "_notify_send", lambda *a, **k: False)
    sink = NotificationSink(config)  # no tray either
    sink.show_answer(sample_answer)  # must not raise
    assert QGuiApplication.clipboard().text() == "B. Paris"


@pytest.mark.parametrize(
    "text,limit,expected",
    [("short", 10, "short"), ("a b c d e", 5, "a b…"), ("multi\nline  text", 40, "multi line text")],
)
def test_elide(text, limit, expected):
    assert elide(text, limit) == expected
