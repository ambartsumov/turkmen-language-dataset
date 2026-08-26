"""Logging that goes to a file and never contains API keys."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable, List, Optional

from app.config import data_dir

LOG_FILE_NAME = "app.log"

# Shapes of well known credentials; used even for keys we were never told about.
_KEY_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z\-_]{10,}"),
    re.compile(r"sk-[0-9A-Za-z\-_]{10,}"),
    re.compile(r"(?i)(api[_-]?key\"?\s*[:=]\s*\"?)([^\s\"',}]{8,})"),
]

_REDACTED = "***REDACTED***"


class SecretRedactingFilter(logging.Filter):
    """Scrubs registered secrets and key-shaped strings from every record."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets: List[str] = []

    def register(self, secrets: Iterable[str]) -> None:
        for secret in secrets:
            secret = (secret or "").strip()
            if len(secret) >= 8 and secret not in self._secrets:
                self._secrets.append(secret)

    def scrub(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, _REDACTED)
        for pattern in _KEY_PATTERNS:
            if pattern.groups == 2:
                text = pattern.sub(lambda m: m.group(1) + _REDACTED, text)
            else:
                text = pattern.sub(_REDACTED, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D102
        try:
            if isinstance(record.msg, str):
                record.msg = self.scrub(record.msg)
            if record.args:
                # Only strings are scrubbed - numeric args must keep their type
                # so that "%d"-style formatting still works.
                if isinstance(record.args, dict):
                    record.args = {
                        k: (self.scrub(v) if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
                else:
                    record.args = tuple(
                        self.scrub(a) if isinstance(a, str) else a for a in record.args
                    )
        except Exception:  # never let logging break the app
            record.msg = "<unloggable record>"
            record.args = ()
        return True


_redactor = SecretRedactingFilter()


class RedactingFormatter(logging.Formatter):
    """Scrubs the fully rendered line, whatever the argument types were."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        return _redactor.scrub(super().format(record))


class ConsoleFormatter(RedactingFormatter):
    """Console lines stay short: full tracebacks belong in the log file."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        exc_info, exc_text = record.exc_info, record.exc_text
        record.exc_info, record.exc_text = None, None
        try:
            return super().format(record)
        finally:
            record.exc_info, record.exc_text = exc_info, exc_text


def log_path() -> Path:
    return data_dir() / LOG_FILE_NAME


def register_secrets(secrets: Iterable[str]) -> None:
    """Make sure these values can never reach the log file."""
    _redactor.register(secrets)


def setup_logging(level: str = "INFO", path: Optional[Path] = None) -> Path:
    target = Path(path) if path else log_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = RotatingFileHandler(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(
        RedactingFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    file_handler.addFilter(_redactor)
    root.addHandler(file_handler)

    stderr = logging.StreamHandler()
    stderr.setLevel(logging.WARNING)
    stderr.setFormatter(ConsoleFormatter("%(levelname)s: %(message)s"))
    stderr.addFilter(_redactor)
    root.addHandler(stderr)

    logging.getLogger(__name__).info("Logging to %s", target)
    return target
