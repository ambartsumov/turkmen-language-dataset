"""Screen capture.

A capture happens only when :meth:`ScreenCapturer.capture` is called (i.e. only
after the hotkey / button).  Nothing is captured in the background and the
resulting image file is deleted as soon as the pipeline is done with it.

Backend order:

* Wayland  -> xdg-desktop-portal ``org.freedesktop.portal.Screenshot``
              -> ``gnome-screenshot`` -> ``grim`` -> ``spectacle``
* X11      -> Qt ``QScreen.grabWindow`` -> the CLI tools above
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from app.utils.session import SessionInfo, detect_session, have

log = logging.getLogger(__name__)


class CaptureError(RuntimeError):
    """No backend was able to produce a screenshot."""


@dataclass
class Screenshot:
    """A screenshot on disk that deletes itself.

    Use as a context manager so the file cannot outlive the analysis::

        with capturer.capture() as shot:
            ...
    """

    path: Path
    backend: str

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()

    def cleanup(self) -> None:
        try:
            if self.path.exists():
                self.path.unlink()
                log.debug("Deleted temporary screenshot")
        except OSError as exc:  # pragma: no cover - unusual
            log.warning("Could not delete temporary screenshot: %s", exc)

    def __enter__(self) -> "Screenshot":
        return self

    def __exit__(self, *exc_info) -> None:
        self.cleanup()


def _new_temp_path() -> Path:
    directory = Path(tempfile.gettempdir()) / "screen-ai-analyzer"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / f"shot-{uuid.uuid4().hex}.png"


def _run(cmd: List[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)


def _valid(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


# --------------------------------------------------------------------------
# backends: each takes a destination path and returns True on success
# --------------------------------------------------------------------------
def qt_backend(target: Path) -> bool:
    """Qt grab of the whole primary screen.  Works on X11, not on Wayland."""
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:  # pragma: no cover - PySide6 is a hard dependency
        return False
    app = QGuiApplication.instance()
    if app is None:
        return False
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return False
    pixmap = screen.grabWindow(0)
    if pixmap.isNull() or pixmap.width() == 0:
        return False
    return bool(pixmap.save(str(target), "PNG")) and _valid(target)


def portal_backend(target: Path) -> bool:
    """xdg-desktop-portal screenshot (the supported Wayland route)."""
    from app.capture.portal import portal_screenshot

    return portal_screenshot(target)


def gnome_screenshot_backend(target: Path) -> bool:
    if not have("gnome-screenshot"):
        return False
    _run(["gnome-screenshot", "-f", str(target)])
    return _valid(target)


def grim_backend(target: Path) -> bool:
    if not have("grim"):
        return False
    _run(["grim", str(target)])
    return _valid(target)


def spectacle_backend(target: Path) -> bool:
    if not have("spectacle"):
        return False
    _run(["spectacle", "-b", "-n", "-f", "-o", str(target)], timeout=20)
    return _valid(target)


def imagemagick_backend(target: Path) -> bool:
    if not have("import") or not os.environ.get("DISPLAY"):
        return False
    _run(["import", "-window", "root", str(target)])
    return _valid(target)


Backend = Callable[[Path], bool]


class ScreenCapturer:
    """Picks a capture backend for the current session."""

    def __init__(self, session: Optional[SessionInfo] = None) -> None:
        self.session = session or detect_session()
        self._preferred: Optional[str] = None

    def backends(self) -> List[tuple[str, Backend]]:
        wayland_chain: List[tuple[str, Backend]] = [
            ("portal", portal_backend),
            ("gnome-screenshot", gnome_screenshot_backend),
            ("grim", grim_backend),
            ("spectacle", spectacle_backend),
        ]
        x11_chain: List[tuple[str, Backend]] = [
            ("qt", qt_backend),
            ("gnome-screenshot", gnome_screenshot_backend),
            ("imagemagick", imagemagick_backend),
            ("spectacle", spectacle_backend),
            ("portal", portal_backend),
        ]
        chain = wayland_chain if self.session.is_wayland else x11_chain
        if self._preferred:  # remember what worked last time
            chain.sort(key=lambda item: item[0] != self._preferred)
        return chain

    def capture(self) -> Screenshot:
        errors: List[str] = []
        for name, backend in self.backends():
            target = _new_temp_path()
            try:
                ok = backend(target)
            except Exception as exc:  # a broken backend must not stop the chain
                log.warning("Capture backend %s failed: %s", name, exc)
                errors.append(f"{name}: {exc}")
                ok = False
            if ok and _valid(target):
                self._preferred = name
                log.info("Screenshot captured via %s (%d bytes)", name, target.stat().st_size)
                return Screenshot(path=target, backend=name)
            if target.exists():
                target.unlink(missing_ok=True)
            errors.append(f"{name}: unavailable")
        log.error("All capture backends failed: %s", "; ".join(errors))
        raise CaptureError(
            "Screen capture is not available in this session "
            f"({self.session.describe()}). Install a screenshot portal or gnome-screenshot."
        )
