"""xdg-desktop-portal screenshot backend (primary route on Wayland).

Calls ``org.freedesktop.portal.Screenshot.Screenshot`` over the session bus and
waits for the ``Response`` signal of the returned request object.  This is the
supported, permission-respecting way to capture the screen on Wayland: the
compositor stays in control and may show its own consent dialog.

Requires a Qt event loop on the calling thread (i.e. call it from the GUI
thread).
"""

from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

log = logging.getLogger(__name__)

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"
REQUEST_IFACE = "org.freedesktop.portal.Request"

DEFAULT_TIMEOUT_MS = 30_000


def uri_to_path(uri: str) -> Optional[Path]:
    if not uri:
        return None
    parsed = urlparse(uri)
    if parsed.scheme and parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path or uri))


def portal_available() -> bool:
    try:
        from PySide6.QtDBus import QDBusConnection
    except ImportError:
        return False
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return False
    iface = bus.interface()
    if iface is None:
        return False
    reply = iface.isServiceRegistered(PORTAL_SERVICE)
    return bool(reply.value()) if hasattr(reply, "value") else bool(reply)


def portal_screenshot(target: Path, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> bool:
    """Take a full-screen screenshot through the portal into ``target``."""
    try:
        from PySide6.QtCore import QEventLoop, QObject, QTimer, Slot
        from PySide6.QtDBus import QDBusConnection, QDBusMessage
    except ImportError:  # pragma: no cover - PySide6 is a hard dependency
        return False

    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        log.info("No D-Bus session bus; portal capture unavailable")
        return False
    if not portal_available():
        log.info("xdg-desktop-portal is not running; skipping portal capture")
        return False

    token = f"screenai{uuid.uuid4().hex[:16]}"
    sender = bus.baseService().lstrip(":").replace(".", "_")
    request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

    state: dict = {"code": None, "results": {}}
    loop = QEventLoop()

    class _Receiver(QObject):
        @Slot("uint", "QVariantMap")
        def on_response(self, code, results):  # noqa: D401
            state["code"] = int(code)
            state["results"] = dict(results or {})
            loop.quit()

    receiver = _Receiver()
    connected = bus.connect(
        PORTAL_SERVICE, request_path, REQUEST_IFACE, "Response", receiver, "on_response"
    )
    if not connected:
        log.warning("Could not subscribe to portal Response signal")
        return False

    try:
        message = QDBusMessage.createMethodCall(
            PORTAL_SERVICE, PORTAL_PATH, SCREENSHOT_IFACE, "Screenshot"
        )
        message.setArguments(
            ["", {"handle_token": token, "interactive": False, "modal": False}]
        )
        reply = bus.call(message, timeout=10_000)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            log.warning("Portal screenshot call failed: %s", reply.errorMessage())
            return False

        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        loop.exec()
        timer.stop()
    finally:
        bus.disconnect(
            PORTAL_SERVICE, request_path, REQUEST_IFACE, "Response", receiver, "on_response"
        )

    if state["code"] is None:
        log.warning("Portal screenshot timed out after %d ms", timeout_ms)
        return False
    if state["code"] != 0:
        log.info("Portal screenshot was cancelled or denied (code %s)", state["code"])
        return False

    source = uri_to_path(str(state["results"].get("uri", "")))
    if source is None or not source.exists():
        log.warning("Portal returned no usable screenshot URI")
        return False

    try:
        shutil.copyfile(source, target)
    except OSError as exc:
        log.warning("Could not read portal screenshot: %s", exc)
        return False
    finally:
        # The portal wrote this file on our behalf - do not leave it behind.
        try:
            os.unlink(source)
        except OSError:
            log.debug("Portal screenshot file could not be removed (read-only location)")

    return target.exists() and target.stat().st_size > 0
