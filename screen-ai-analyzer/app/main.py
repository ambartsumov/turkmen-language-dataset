"""Entry point.

    python -m app.main             # start the app
    python -m app.main --trigger   # tell a running instance to capture now
    python -m app.main --check     # self-test: session, backends, providers
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from app.config import KEY_ENV_VARS, AppConfig, load_dotenv
from app.utils.logging_setup import log_path, register_secrets, setup_logging
from app.utils.session import detect_session

log = logging.getLogger(__name__)

APP_ID = "screen-ai-analyzer"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=APP_ID, description="Screen AI Analyzer")
    parser.add_argument(
        "--trigger",
        action="store_true",
        help="ask the running instance to capture and analyse the screen now",
    )
    parser.add_argument(
        "--check", action="store_true", help="run environment self-checks and exit"
    )
    parser.add_argument(
        "--hidden", action="store_true", help="start without showing the control window"
    )
    parser.add_argument("--capture", action="store_true", help="capture once at startup")
    parser.add_argument(
        "--ping",
        action="store_true",
        help="send one tiny request to every configured provider and report the result",
    )
    return parser.parse_args(argv)


def bootstrap() -> AppConfig:
    load_dotenv()
    config = AppConfig.load()
    register_secrets(config.secret_values())
    setup_logging(config.log_level)
    log.info("Config: %s", config.redacted_dict())
    return config


# --------------------------------------------------------------------------
# --check
# --------------------------------------------------------------------------
def run_checks(config: AppConfig) -> int:
    import os

    from app.capture.screenshot import ScreenCapturer
    from app.ai.pipeline import AnalysisPipeline
    from app.ocr.engine import tesseract_available
    from app.utils.hotkey import HotkeyManager, trigger_command

    session = detect_session()
    print(f"Session:          {session.describe()}")
    print(f"Log file:         {log_path()}")

    print("\nAPI keys:")
    for provider, env_var in KEY_ENV_VARS.items():
        source = (
            "environment/.env"
            if os.environ.get(env_var, "").strip()
            else ("settings file" if config.resolved_key(provider) else None)
        )
        state = f"set ({source})" if source else "not set"
        print(f"  {provider:<11} {env_var:<20} {state}")

    pipeline = AnalysisPipeline(config)
    providers = pipeline.build_providers()
    print("\nProvider chain:")
    if not providers:
        print("  (none — no API key configured)")
    for provider in providers:
        kind = "vision" if provider.supports_vision else "text (needs OCR)"
        print(f"  {provider.name:<34} model={provider.model:<28} {kind}")

    print(f"\nOCR (tesseract):  {'available' if tesseract_available() else 'NOT installed'}")

    capturer = ScreenCapturer(session)
    print("Capture backends (in order):")
    for name, _ in capturer.backends():
        print(f"  {name}")

    manager = HotkeyManager(config.hotkey, session)
    status = manager.start()
    print(f"\nHotkey method:    {status.method} ({'active' if status.active else 'inactive'})")
    print(f"                  {status.message}")
    print(f"Trigger command:  {trigger_command()}")
    manager.stop()
    return 0


def run_ping(config: AppConfig) -> int:
    """Verify API keys with one cheap text request per provider."""
    from app.ai.base import ProviderError
    from app.ai.pipeline import AnalysisPipeline

    providers = AnalysisPipeline(config).build_providers()
    if not providers:
        print("No provider configured — put a key in .env first.")
        return 1

    question = "What is 2+2? A) 3 B) 4 C) 5"
    failures = 0
    for provider in providers:
        label = f"{provider.name} ({provider.model})"
        try:
            answer = provider.analyze_text(question)
        except ProviderError as exc:
            failures += 1
            print(f"  FAIL  {label}: {exc}")
        except Exception as exc:  # pragma: no cover - network specific
            failures += 1
            print(f"  FAIL  {label}: {type(exc).__name__}")
        else:
            print(f"  OK    {label}: answer={answer.answer!r} confidence={answer.confidence:.2f}")
    return 0 if failures == 0 else 2


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
def _tray_icon(app):
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(60, 130, 220))
    painter.setPen(QColor(255, 255, 255))
    painter.drawRoundedRect(6, 6, 52, 52, 12, 12)
    font = painter.font()
    font.setBold(True)
    font.setPointSize(22)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), 0x0084, "AI")  # AlignCenter
    painter.end()
    return QIcon(pixmap)


def run_gui(config: AppConfig, args: argparse.Namespace) -> int:
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    from app.config import OUTPUT_OVERLAY
    from app.controller import Controller
    from app.overlay.control_window import ControlWindow
    from app.overlay.notifier import NotificationSink, notify_send_available
    from app.overlay.overlay import AnswerOverlay
    from app.overlay.settings_dialog import SettingsDialog
    from app.utils.hotkey import HotkeyManager
    from app.utils.ipc import TriggerServer, instance_running, send_trigger

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Screen AI Analyzer")
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    if args.trigger:
        ok = send_trigger()
        if not ok:
            print(
                "No running instance found. Start the app first (./run.sh).",
                file=sys.stderr,
            )
        return 0 if ok else 1

    if instance_running():
        print("Screen AI Analyzer is already running; asking it to show up.")
        from app.utils.ipc import SHOW_MESSAGE

        send_trigger(SHOW_MESSAGE)
        return 0

    notification_mode = config.output_mode != OUTPUT_OVERLAY
    sink = NotificationSink(config) if notification_mode else AnswerOverlay(config)
    controller = Controller(config, sink=sink)
    hotkeys = HotkeyManager(config.hotkey)
    status = hotkeys.start()

    window = ControlWindow(config.hotkey)
    window.set_status(status.message)
    window.capture_requested.connect(controller.trigger)
    window.quit_requested.connect(app.quit)
    controller.status_changed.connect(window.set_status)
    hotkeys.triggered.connect(controller.trigger)

    server = TriggerServer()
    server.start()
    server.triggered.connect(controller.trigger)
    server.show_requested.connect(lambda: (window.show(), window.raise_()))

    def open_settings() -> None:
        dialog = SettingsDialog(config, hotkeys, window)
        if dialog.exec():
            updated = dialog.apply_to_config()
            updated.save()
            register_secrets(updated.secret_values())
            sink.apply_config(updated)
            controller.pipeline = type(controller.pipeline)(updated)
            hotkeys.hotkey = updated.hotkey
            window.set_hotkey(updated.hotkey)
            log.info("Settings saved: %s", updated.redacted_dict())

    window.settings_requested.connect(open_settings)

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(_tray_icon(app), app)
        menu = QMenu()
        menu.addAction(f"Capture & Analyze ({config.hotkey})", controller.trigger)
        menu.addAction("Show window", lambda: (window.show(), window.raise_()))
        menu.addAction("Settings…", open_settings)
        menu.addSeparator()
        menu.addAction("Quit", app.quit)
        tray.setContextMenu(menu)
        tray.setToolTip("Screen AI Analyzer")
        tray.show()
        if isinstance(sink, NotificationSink):
            sink.tray = tray  # fallback when notify-send is missing

    if notification_mode and not notify_send_available() and tray is None:
        log.warning("No notification daemon and no system tray: results are only logged")
    # In notification mode nothing is drawn on screen, so the control window
    # only opens when the user asks for it.
    if not args.hidden and not notification_mode:
        window.show()
    elif not args.hidden and notification_mode and tray is None:
        window.show()  # otherwise there would be no way to reach Settings/Quit
    if args.capture:
        controller.trigger()

    app.aboutToQuit.connect(controller.shutdown)
    app.aboutToQuit.connect(hotkeys.stop)
    app.aboutToQuit.connect(server.stop)
    log.info("Application started (%s)", detect_session().describe())
    return app.exec()


def main(argv: Optional[List[str]] = None) -> int:
    # `./run.sh --check | head` should not end in a BrokenPipeError traceback.
    try:
        import signal

        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):  # pragma: no cover
        pass

    args = parse_args(argv)
    if args.trigger:
        # Short-lived helper process: no config, no logging, just the message.
        from PySide6.QtWidgets import QApplication
        from app.utils.ipc import send_trigger

        QApplication(sys.argv[:1])
        if send_trigger():
            return 0
        print("No running instance found. Start the app first (./run.sh).", file=sys.stderr)
        return 1

    config = bootstrap()
    if args.check:
        return run_checks(config)
    if args.ping:
        return run_ping(config)
    return run_gui(config, args)


if __name__ == "__main__":
    raise SystemExit(main())
