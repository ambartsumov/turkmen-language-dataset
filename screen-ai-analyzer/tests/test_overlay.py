"""4. Clipboard, 5. Overlay rendering."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent

from app.ai.schema import Answer
from app.config import POSITION_BOTTOM, POSITION_TOP
from app.overlay.overlay import STATE_ANSWER, STATE_BUSY, STATE_ERROR, STATE_IDLE, AnswerOverlay


@pytest.fixture
def overlay(qapp, config):
    config.output_mode = "overlay"
    widget = AnswerOverlay(config)
    yield widget
    widget.close()
    widget.deleteLater()


def test_overlay_is_frameless_on_top_and_not_fullscreen(overlay):
    flags = overlay.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert not overlay.isFullScreen()
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_overlay_width_is_a_fraction_of_the_screen(overlay, config):
    overlay.show_busy()
    screen_width = QGuiApplication.primaryScreen().availableGeometry().width()
    expected = max(320, int(screen_width * config.overlay_width_ratio))
    assert overlay.width() == pytest.approx(expected, abs=1)
    assert overlay.width() < screen_width


def test_busy_then_answer_states(overlay, sample_answer):
    overlay.show_busy()
    assert overlay.state == STATE_BUSY
    assert "Analyzing" in overlay.body_label.text()
    assert not overlay.copy_button.isEnabled()

    overlay.show_answer(sample_answer)
    assert overlay.state == STATE_ANSWER
    assert overlay.copy_button.isEnabled()
    body = overlay.body_label.text()
    assert "Paris" in body and "Answer:" in body
    assert "gemini" in overlay.meta_label.text()
    assert "97%" in overlay.meta_label.text()


def test_overlay_grows_for_long_answers_but_is_capped(overlay, config):
    short = Answer(question="q", answer="short")
    overlay.show_answer(short)
    short_height = overlay.height()

    long_answer = Answer(question="q", answer="word " * 4000)
    overlay.show_answer(long_answer)
    tall_height = overlay.height()

    screen = QGuiApplication.primaryScreen().availableGeometry()
    assert tall_height > short_height
    assert tall_height <= int(screen.height() * config.overlay_max_height_ratio) + 1
    # very long text stays reachable by scrolling
    assert overlay.scroll.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert overlay.body_label.wordWrap()


def test_position_top_and_bottom(overlay, config, sample_answer):
    screen = QGuiApplication.primaryScreen().availableGeometry()

    config.overlay_position = POSITION_TOP
    overlay.apply_config(config)
    overlay.show_answer(sample_answer)
    top_y = overlay.y()

    config.overlay_position = POSITION_BOTTOM
    overlay.apply_config(config)
    overlay.show_answer(sample_answer)
    bottom_y = overlay.y()

    assert top_y < screen.height() / 2 < bottom_y
    assert bottom_y + overlay.height() <= screen.y() + screen.height()


def test_font_size_and_opacity_are_applied(overlay, config):
    config.font_size = 17
    config.opacity = 0.55
    overlay.apply_config(config)
    assert "17pt" in overlay.card.styleSheet()
    assert overlay.windowOpacity() == pytest.approx(0.55, abs=0.01)


def test_error_view_has_no_traceback(overlay):
    overlay.show_error("Gemini request failed (HTTP 429)")
    assert overlay.state == STATE_ERROR
    text = overlay.body_label.text()
    assert text.startswith("Unable to analyze screen:")
    assert "Traceback" not in text
    assert not overlay.copy_button.isEnabled()


def test_escape_closes_overlay(overlay, sample_answer):
    overlay.show_answer(sample_answer)
    assert overlay.isVisible()
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(event)
    assert not overlay.isVisible()
    assert overlay.state == STATE_IDLE


def test_close_button_hides_overlay(overlay, sample_answer):
    closed = []
    overlay.closed.connect(lambda: closed.append(True))
    overlay.show_answer(sample_answer)
    overlay.close_button.click()
    assert not overlay.isVisible()
    assert closed == [True]


# -- clipboard -------------------------------------------------------------
def test_copy_puts_only_the_answer_on_the_clipboard(overlay, sample_answer):
    QGuiApplication.clipboard().clear()
    overlay.show_answer(sample_answer)
    assert overlay.copy_answer() is True

    text = QGuiApplication.clipboard().text()
    assert text == "B. Paris"
    assert "{" not in text and "confidence" not in text
    assert sample_answer.explanation not in text


def test_copy_button_copies_open_answer(overlay):
    QGuiApplication.clipboard().clear()
    answer = Answer(question="Explain TCP", answer="TCP is a reliable transport protocol.")
    overlay.show_answer(answer)
    overlay.copy_button.click()
    assert QGuiApplication.clipboard().text() == "TCP is a reliable transport protocol."


def test_copy_without_answer_is_a_no_op(overlay):
    overlay.show_busy()
    assert overlay.copy_answer() is False


def test_second_trigger_replaces_previous_answer(overlay, sample_answer):
    overlay.show_answer(sample_answer)
    overlay.show_busy()
    assert overlay.state == STATE_BUSY
    assert "Paris" not in overlay.body_label.text()

    overlay.show_answer(Answer(question="q2", answer="42", provider="openrouter"))
    assert "42" in overlay.body_label.text()
    assert "Paris" not in overlay.body_label.text()
