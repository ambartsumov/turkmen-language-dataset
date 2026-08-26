"""End-to-end flow: hotkey -> capture -> pipeline -> overlay, and re-triggering."""

from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QDeadlineTimer, QEventLoop, QTimer

from app.ai.base import ProviderError
from app.ai.pipeline import AnalysisError, AnalysisPipeline
from app.ai.schema import Answer
from app.capture.screenshot import CaptureError, ScreenCapturer, Screenshot
from app.controller import Controller
from app.overlay.overlay import STATE_ANSWER, STATE_ERROR
from app.utils.hotkey import trigger_command
from app.utils.session import SessionInfo


class StubCapturer(ScreenCapturer):
    """Writes a real temp file so cleanup can be observed."""

    def __init__(self, png: Path):
        super().__init__(SessionInfo("wayland", "gnome"))
        self.png = png
        self.calls = 0
        self.paths = []

    def capture(self) -> Screenshot:
        self.calls += 1
        from app.capture.screenshot import _new_temp_path

        target = _new_temp_path()
        target.write_bytes(self.png.read_bytes())
        self.paths.append(target)
        return Screenshot(path=target, backend="stub")


class StubPipeline(AnalysisPipeline):
    def __init__(self, config, answers):
        super().__init__(config)
        self.answers = list(answers)
        self.seen_images = []

    def analyze(self, image_source):
        self.seen_images.append(image_source)
        result = self.answers.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def wait_for(predicate, timeout_ms=5000):
    deadline = QDeadlineTimer(timeout_ms)
    while not predicate():
        if deadline.hasExpired():
            return False
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    return True


@pytest.fixture
def parts(qapp, config, screenshot_png):
    from app.config import OUTPUT_OVERLAY
    from app.overlay.overlay import AnswerOverlay

    config.output_mode = OUTPUT_OVERLAY
    overlay = AnswerOverlay(config)
    capturer = StubCapturer(screenshot_png)
    yield overlay, capturer
    overlay.close()


def test_capture_flow_shows_answer_and_deletes_the_screenshot(parts, config):
    overlay, capturer = parts
    pipeline = StubPipeline(config, [Answer(question="2+2?", answer="4", provider="gemini")])
    controller = Controller(config, sink=overlay, capturer=capturer, pipeline=pipeline)

    controller.trigger()
    assert wait_for(lambda: overlay.state == STATE_ANSWER)

    assert "4" in overlay.body_label.text()
    assert capturer.calls == 1
    # the temporary screenshot is gone once the analysis has the bytes
    assert not any(path.exists() for path in capturer.paths)
    # the pipeline received bytes, not a path on disk
    assert isinstance(pipeline.seen_images[0], (bytes, bytearray))
    controller.shutdown()


def test_second_trigger_replaces_the_previous_result(parts, config):
    overlay, capturer = parts
    pipeline = StubPipeline(
        config,
        [
            Answer(question="q1", answer="first", provider="gemini"),
            Answer(question="q2", answer="second", provider="openrouter"),
        ],
    )
    controller = Controller(config, sink=overlay, capturer=capturer, pipeline=pipeline)

    controller.trigger()
    assert wait_for(lambda: overlay.state == STATE_ANSWER)
    assert "first" in overlay.body_label.text()

    controller.trigger()
    assert wait_for(lambda: "second" in overlay.body_label.text())

    assert "first" not in overlay.body_label.text()
    assert capturer.calls == 2
    assert not any(path.exists() for path in capturer.paths)
    controller.shutdown()


def test_analysis_error_is_shown_without_traceback(parts, config):
    overlay, capturer = parts
    pipeline = StubPipeline(config, [AnalysisError("gemini: quota exceeded")])
    controller = Controller(config, sink=overlay, capturer=capturer, pipeline=pipeline)

    controller.trigger()
    assert wait_for(lambda: overlay.state == STATE_ERROR)

    text = overlay.body_label.text()
    assert text.startswith("Unable to analyze screen:")
    assert "quota exceeded" in text
    assert "Traceback" not in text and "File \"" not in text
    controller.shutdown()


def test_unexpected_exception_is_not_leaked_to_the_user(parts, config):
    overlay, capturer = parts
    pipeline = StubPipeline(config, [RuntimeError("boom at 0xdeadbeef")])
    controller = Controller(config, sink=overlay, capturer=capturer, pipeline=pipeline)

    controller.trigger()
    assert wait_for(lambda: overlay.state == STATE_ERROR)
    assert "boom at 0xdeadbeef" not in overlay.body_label.text()
    assert "log file" in overlay.body_label.text().lower()
    controller.shutdown()


def test_capture_failure_is_reported(parts, config):
    overlay, capturer = parts

    def failing_capture():
        raise CaptureError("Screen capture is not available in this session (wayland)")

    capturer.capture = failing_capture
    controller = Controller(config, sink=overlay, capturer=capturer, pipeline=StubPipeline(config, []))

    controller.trigger()
    assert wait_for(lambda: overlay.state == STATE_ERROR)
    assert "not available" in overlay.body_label.text()
    controller.shutdown()


def test_overlay_is_hidden_while_the_screen_is_grabbed(parts, config):
    overlay, capturer = parts
    visible_during_capture = []

    original = capturer.capture

    def watching_capture():
        visible_during_capture.append(overlay.isVisible())
        return original()

    capturer.capture = watching_capture
    pipeline = StubPipeline(config, [Answer(question="q", answer="a", provider="gemini")])
    controller = Controller(config, sink=overlay, capturer=capturer, pipeline=pipeline)

    overlay.show_answer(Answer(question="old", answer="old answer"))
    controller.trigger()
    assert wait_for(lambda: "old answer" not in overlay.body_label.text())
    assert wait_for(lambda: overlay.state == STATE_ANSWER)
    assert visible_during_capture == [False]  # the overlay is never in the shot
    controller.shutdown()


def test_trigger_command_points_at_run_sh():
    command = trigger_command()
    assert command.endswith("--trigger")
    assert "run.sh" in command or "app.main" in command
