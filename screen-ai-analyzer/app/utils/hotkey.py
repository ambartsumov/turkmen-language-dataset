"""Global hotkey handling.

There is no way for an ordinary application to grab a global key on a GNOME
Wayland session - and this app does not try to work around that.  Instead it
uses the supported route for each session:

* **GNOME (Wayland or X11)** - a GNOME *custom keybinding* is registered with
  ``gsettings``; pressing it runs ``run.sh --trigger``, which sends "capture"
  to the running instance over a local socket.  Installed only when the user
  explicitly asks for it in the settings dialog.
* **X11 (any desktop)** - an in-process listener via ``pynput``, if installed.
* **Other Wayland compositors (KDE, sway, …)** - the app prints/shows the
  command to bind manually in the desktop's own shortcut settings.

The GUI button and the tray menu always work, whatever the session is.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, Signal

from app.config import project_root
from app.utils.session import SessionInfo, detect_session, have

log = logging.getLogger(__name__)

METHOD_PYNPUT = "pynput"
METHOD_GNOME = "gnome-keybinding"
METHOD_MANUAL = "manual"

SCHEMA_MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
KEYBINDING_PATH = (
    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/screen-ai-analyzer/"
)
KEYBINDING_NAME = "Screen AI Analyzer"


def trigger_command() -> str:
    """Command a desktop keybinding should run."""
    run_sh = project_root() / "run.sh"
    if run_sh.exists():
        return f"{shlex.quote(str(run_sh))} --trigger"
    return f"python3 -m app.main --trigger"


@dataclass
class HotkeyStatus:
    method: str
    active: bool
    message: str


# --------------------------------------------------------------------------
# GNOME custom keybinding (gsettings)
# --------------------------------------------------------------------------
def _gsettings(*args: str, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gsettings", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


def gnome_available() -> bool:
    return have("gsettings")


def _custom_list() -> List[str]:
    result = _gsettings("get", SCHEMA_MEDIA_KEYS, "custom-keybindings")
    raw = (result.stdout or "").strip()
    if not raw or raw.startswith("@as []") or raw == "[]":
        return []
    raw = raw.replace("@as ", "")
    try:
        import ast

        value = ast.literal_eval(raw)
        return [str(v) for v in value]
    except (ValueError, SyntaxError):
        return []


def gnome_keybinding_installed(path: str = KEYBINDING_PATH) -> bool:
    return path in _custom_list()


def install_gnome_keybinding(
    key: str = "F8", command: Optional[str] = None, path: str = KEYBINDING_PATH
) -> bool:
    """Register the GNOME custom shortcut. Returns True on success."""
    if not gnome_available():
        log.warning("gsettings not available; cannot install GNOME keybinding")
        return False
    command = command or trigger_command()
    entries = _custom_list()
    if path not in entries:
        entries.append(path)
    listing = "[" + ", ".join(f"'{item}'" for item in entries) + "]"
    steps = [
        ("set", SCHEMA_MEDIA_KEYS, "custom-keybindings", listing),
        ("set", f"{CUSTOM_SCHEMA}:{path}", "name", KEYBINDING_NAME),
        ("set", f"{CUSTOM_SCHEMA}:{path}", "command", command),
        ("set", f"{CUSTOM_SCHEMA}:{path}", "binding", key),
    ]
    for step in steps:
        result = _gsettings(*step)
        if result.returncode != 0:
            log.error("gsettings %s failed: %s", step[1], (result.stderr or "").strip())
            return False
    log.info("GNOME keybinding installed for %s", key)
    return True


def remove_gnome_keybinding(path: str = KEYBINDING_PATH) -> bool:
    if not gnome_available():
        return False
    entries = [item for item in _custom_list() if item != path]
    listing = "[" + ", ".join(f"'{item}'" for item in entries) + "]" if entries else "@as []"
    result = _gsettings("set", SCHEMA_MEDIA_KEYS, "custom-keybindings", listing)
    if result.returncode != 0:
        return False
    log.info("GNOME keybinding removed")
    return True


# --------------------------------------------------------------------------
# manager
# --------------------------------------------------------------------------
class HotkeyManager(QObject):
    """Chooses and owns the hotkey mechanism for this session."""

    triggered = Signal()

    def __init__(self, hotkey: str = "F8", session: Optional[SessionInfo] = None) -> None:
        super().__init__()
        self.hotkey = hotkey or "F8"
        self.session = session or detect_session()
        self._listener = None
        self.status = HotkeyStatus(METHOD_MANUAL, False, "not started")

    # -- capability probing ----------------------------------------------
    def pynput_available(self) -> bool:
        if not self.session.is_x11:
            return False  # pynput cannot grab keys on Wayland
        try:
            import pynput  # noqa: F401
        except Exception:
            return False
        return True

    def preferred_method(self) -> str:
        if self.pynput_available():
            return METHOD_PYNPUT
        if self.session.is_gnome and gnome_available():
            return METHOD_GNOME
        return METHOD_MANUAL

    # -- lifecycle --------------------------------------------------------
    def start(self) -> HotkeyStatus:
        method = self.preferred_method()
        if method == METHOD_PYNPUT and self._start_pynput():
            self.status = HotkeyStatus(
                METHOD_PYNPUT, True, f"{self.hotkey} is active (X11 listener)"
            )
        elif method == METHOD_GNOME:
            installed = gnome_keybinding_installed()
            self.status = HotkeyStatus(
                METHOD_GNOME,
                installed,
                (
                    f"{self.hotkey} is registered as a GNOME shortcut"
                    if installed
                    else "Register the GNOME shortcut in Settings to use the hotkey"
                ),
            )
        else:
            self.status = HotkeyStatus(
                METHOD_MANUAL,
                False,
                "Bind this command in your desktop's keyboard settings: "
                + trigger_command(),
            )
        log.info("Hotkey status: %s (%s)", self.status.method, self.status.message)
        return self.status

    def _start_pynput(self) -> bool:
        try:
            from pynput import keyboard
        except Exception:
            return False
        key_name = self.hotkey.strip().lower()
        try:
            hotkey = keyboard.HotKey(keyboard.HotKey.parse(f"<{key_name}>"), self.triggered.emit)
        except Exception as exc:
            log.warning("Could not parse hotkey %s: %s", self.hotkey, exc)
            return False

        def on_press(key):
            hotkey.press(listener.canonical(key))

        def on_release(key):
            hotkey.release(listener.canonical(key))

        try:
            listener = keyboard.Listener(on_press=on_press, on_release=on_release)
            listener.daemon = True
            listener.start()
        except Exception as exc:
            log.warning("pynput listener failed to start: %s", exc)
            return False
        self._listener = listener
        return True

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:  # pragma: no cover
                pass
            self._listener = None

    # -- desktop keybinding management (called from the settings dialog) ---
    def install_desktop_shortcut(self) -> bool:
        if not (self.session.is_gnome and gnome_available()):
            return False
        ok = install_gnome_keybinding(self.hotkey)
        if ok:
            self.status = HotkeyStatus(
                METHOD_GNOME, True, f"{self.hotkey} is registered as a GNOME shortcut"
            )
        return ok

    def remove_desktop_shortcut(self) -> bool:
        ok = remove_gnome_keybinding()
        if ok:
            self.status = HotkeyStatus(METHOD_GNOME, False, "GNOME shortcut removed")
        return ok
