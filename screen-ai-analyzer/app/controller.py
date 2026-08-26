"""Wires capture, the AI pipeline and the chosen output sink together."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from app.ai.pipeline import AnalysisError, AnalysisPipeline
from app.ai.schema import Answer
from app.capture.screenshot import CaptureError, ScreenCapturer
from app.config import AppConfig

log = logging.getLogger(__name__)

#: Time given to the compositor to actually hide the overlay before grabbing.
HIDE_DELAY_MS = 180


def build_sink(config: AppConfig):
    """Pick the output sink: a desktop notification, or the answer overlay."""
    from app.config import OUTPUT_OVERLAY

    if config.output_mode == OUTPUT_OVERLAY:
        from app.overlay.overlay import AnswerOverlay

        return AnswerOverlay(config)
    from app.overlay.notifier import NotificationSink

    return NotificationSink(config)


class AnalysisWorker(QObject):
    """Runs preprocessing + the AI request off the GUI thread."""

    finished = Signal(int, object)  # generation, Answer
    failed = Signal(int, str)  # generation, user-facing message

    def __init__(self, pipeline: AnalysisPipeline, image: bytes, generation: int) -> None:
        super().__init__()
        self.pipeline = pipeline
        self.image = image
        self.generation = generation

    def run(self) -> None:
        try:
            answer = self.pipeline.analyze(self.image)
        except AnalysisError as exc:
            self.failed.emit(self.generation, str(exc))
        except Exception:
            log.exception("Unexpected failure during analysis")
            self.failed.emit(self.generation, "unexpected internal error (see log file)")
        else:
            self.finished.emit(self.generation, answer)
        finally:
            self.image = b""  # do not keep the screenshot in memory


class Controller(QObject):
    """One capture at a time; a new trigger replaces the previous result."""

    status_changed = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        sink=None,
        capturer: Optional[ScreenCapturer] = None,
        pipeline: Optional[AnalysisPipeline] = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.sink = sink if sink is not None else build_sink(config)
        self.capturer = capturer or ScreenCapturer()
        self.pipeline = pipeline or AnalysisPipeline(config)
        self._generation = 0
        self._thread: Optional[QThread] = None
        self._worker: Optional[AnalysisWorker] = None

    # -- public API -------------------------------------------------------
    def trigger(self) -> None:
        """Hotkey / button entry point."""
        self._generation += 1
        generation = self._generation
        log.info("Capture triggered (generation %d)", generation)
        self.status_changed.emit("Analyzing…")

        # Whatever the sink draws (if anything) must not end up in the shot.
        self.sink.hide_for_capture()
        QTimer.singleShot(HIDE_DELAY_MS, lambda: self._capture_and_analyze(generation))

    def shutdown(self) -> None:
        self._stop_thread()

    # -- internals --------------------------------------------------------
    def _capture_and_analyze(self, generation: int) -> None:
        if generation != self._generation:
            return
        try:
            with self.capturer.capture() as shot:
                image = shot.read_bytes()  # file is deleted when the block ends
        except CaptureError as exc:
            self._show_error(generation, str(exc))
            return
        except Exception:
            log.exception("Screen capture failed")
            self._show_error(generation, "screen capture failed (see log file)")
            return

        self.sink.show_busy("Analyzing…")
        self._start_worker(image, generation)

    def _start_worker(self, image: bytes, generation: int) -> None:
        self._stop_thread()
        thread = QThread()
        worker = AnalysisWorker(self.pipeline, image, generation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _stop_thread(self) -> None:
        thread, self._thread = self._thread, None
        self._worker = None
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(3000)

    def _on_finished(self, generation: int, answer: Answer) -> None:
        if generation != self._generation:
            log.info("Discarding stale result from generation %d", generation)
            return
        self.sink.show_answer(answer)
        self.status_changed.emit(f"Answer from {answer.provider}")

    def _on_failed(self, generation: int, message: str) -> None:
        self._show_error(generation, message)

    def _show_error(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        log.error("Analysis failed: %s", message)
        self.sink.show_error(message)
        self.status_changed.emit(f"Failed: {message}")
