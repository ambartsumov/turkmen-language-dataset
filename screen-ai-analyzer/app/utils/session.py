"""Detection of the desktop session (Wayland / X11, compositor)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

WAYLAND = "wayland"
X11 = "x11"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class SessionInfo:
    session_type: str
    desktop: str

    @property
    def is_wayland(self) -> bool:
        return self.session_type == WAYLAND

    @property
    def is_x11(self) -> bool:
        return self.session_type == X11

    @property
    def is_gnome(self) -> bool:
        return "gnome" in self.desktop or "ubuntu" in self.desktop

    @property
    def is_kde(self) -> bool:
        return "kde" in self.desktop or "plasma" in self.desktop

    def describe(self) -> str:
        return f"session={self.session_type or 'unknown'} desktop={self.desktop or 'unknown'}"


def detect_session() -> SessionInfo:
    """Mirrors ``echo $XDG_SESSION_TYPE`` / ``echo $XDG_CURRENT_DESKTOP``."""
    stype = (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()
    desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").strip().lower()
    if not stype:
        if os.environ.get("WAYLAND_DISPLAY"):
            stype = WAYLAND
        elif os.environ.get("DISPLAY"):
            stype = X11
        else:
            stype = UNKNOWN
    return SessionInfo(session_type=stype, desktop=desktop)


def have(binary: str) -> bool:
    return shutil.which(binary) is not None
