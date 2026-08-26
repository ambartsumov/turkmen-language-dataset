"""Single-instance guard + local trigger channel.

The desktop keybinding launches ``run.sh --trigger``; that short-lived process
sends ``capture`` over a local socket to the already running instance instead
of starting a second copy of the app.
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

SERVER_NAME = "screen-ai-analyzer.trigger"
TRIGGER_MESSAGE = b"capture\n"
SHOW_MESSAGE = b"show\n"


class TriggerServer(QObject):
    """Listens for trigger messages from other processes."""

    triggered = Signal()
    show_requested = Signal()

    def __init__(self, name: str = SERVER_NAME, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.name = name
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)

    def start(self) -> bool:
        QLocalServer.removeServer(self.name)  # clear a socket left by a crash
        if not self._server.listen(self.name):
            log.warning("Could not listen on %s: %s", self.name, self._server.errorString())
            return False
        log.info("Trigger server listening on %s", self.name)
        return True

    def stop(self) -> None:
        self._server.close()
        QLocalServer.removeServer(self.name)

    def _on_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda: self._on_ready(socket))
        socket.disconnected.connect(socket.deleteLater)

    def _on_ready(self, socket: QLocalSocket) -> None:
        payload = bytes(socket.readAll().data()).strip()
        socket.disconnectFromServer()
        if payload == TRIGGER_MESSAGE.strip():
            log.info("Capture triggered via local socket")
            self.triggered.emit()
        elif payload == SHOW_MESSAGE.strip():
            self.show_requested.emit()
        else:
            log.debug("Ignoring unknown local message")


def send_trigger(message: bytes = TRIGGER_MESSAGE, name: str = SERVER_NAME, timeout_ms: int = 1500) -> bool:
    """Ask a running instance to capture. False if nothing is running."""
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(message)
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True


def instance_running(name: str = SERVER_NAME) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(name)
    connected = socket.waitForConnected(400)
    if connected:
        socket.disconnectFromServer()
    return connected
