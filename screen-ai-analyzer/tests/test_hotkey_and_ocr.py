"""Hotkey strategy selection / GNOME keybinding management and the OCR fallback."""

import subprocess

import pytest

from app.ocr.engine import LANG_MAP, OcrError, extract_text, tesseract_available, tesseract_lang
from app.utils import hotkey as hk
from app.utils.session import SessionInfo, detect_session


class FakeGsettings:
    """Records gsettings invocations instead of touching the real desktop."""

    def __init__(self, existing="@as []"):
        self.calls = []
        self.existing = existing

    def __call__(self, *args, timeout=10):
        self.calls.append(args)
        if args[0] == "get":
            return subprocess.CompletedProcess(args, 0, stdout=self.existing, stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


@pytest.fixture
def fake_gsettings(monkeypatch):
    fake = FakeGsettings()
    monkeypatch.setattr(hk, "_gsettings", fake)
    monkeypatch.setattr(hk, "gnome_available", lambda: True)
    return fake


def test_install_keybinding_writes_name_command_and_binding(fake_gsettings):
    assert hk.install_gnome_keybinding("F8") is True
    written = {call[2]: call[3] for call in fake_gsettings.calls if call[0] == "set"}
    assert written["binding"] == "F8"
    assert written["command"].endswith("--trigger")
    assert written["name"] == hk.KEYBINDING_NAME
    assert hk.KEYBINDING_PATH in written["custom-keybindings"]


def test_install_keeps_existing_user_keybindings(monkeypatch):
    fake = FakeGsettings(existing="['/org/gnome/…/custom-keybindings/custom0/']")
    monkeypatch.setattr(hk, "_gsettings", fake)
    monkeypatch.setattr(hk, "gnome_available", lambda: True)
    hk.install_gnome_keybinding("F9")
    listing = next(c[3] for c in fake.calls if c[0] == "set" and c[2] == "custom-keybindings")
    assert "custom0" in listing and hk.KEYBINDING_PATH in listing


def test_remove_keybinding_drops_only_ours(monkeypatch):
    fake = FakeGsettings(existing=f"['{hk.KEYBINDING_PATH}', '/other/custom0/']")
    monkeypatch.setattr(hk, "_gsettings", fake)
    monkeypatch.setattr(hk, "gnome_available", lambda: True)
    assert hk.remove_gnome_keybinding() is True
    listing = fake.calls[-1][3]
    assert hk.KEYBINDING_PATH not in listing
    assert "/other/custom0/" in listing


def test_gsettings_failure_is_reported(monkeypatch):
    def failing(*args, timeout=10):
        if args[0] == "get":
            return subprocess.CompletedProcess(args, 0, stdout="@as []", stderr="")
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="no such schema")

    monkeypatch.setattr(hk, "_gsettings", failing)
    monkeypatch.setattr(hk, "gnome_available", lambda: True)
    assert hk.install_gnome_keybinding("F8") is False


def test_no_hotkey_grab_is_attempted_on_wayland(monkeypatch):
    manager = hk.HotkeyManager("F8", SessionInfo("wayland", "gnome"))
    # pynput must never be used on Wayland, even when it is installed
    assert manager.pynput_available() is False
    monkeypatch.setattr(hk, "gnome_available", lambda: True)
    assert manager.preferred_method() == hk.METHOD_GNOME


def test_unknown_wayland_compositor_falls_back_to_manual(monkeypatch):
    manager = hk.HotkeyManager("F8", SessionInfo("wayland", "sway"))
    monkeypatch.setattr(hk, "gnome_available", lambda: False)
    status = manager.start()
    assert status.method == hk.METHOD_MANUAL
    assert status.active is False
    assert "--trigger" in status.message  # tells the user what to bind


def test_status_is_inactive_until_the_shortcut_is_registered(monkeypatch):
    monkeypatch.setattr(hk, "gnome_available", lambda: True)
    monkeypatch.setattr(hk, "gnome_keybinding_installed", lambda: False)
    status = hk.HotkeyManager("F8", SessionInfo("wayland", "ubuntu:gnome")).start()
    assert status.method == hk.METHOD_GNOME and status.active is False


def test_detect_session_reads_the_environment(monkeypatch):
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "ubuntu:GNOME")
    session = detect_session()
    assert session.is_wayland and session.is_gnome and not session.is_x11


# -- OCR -------------------------------------------------------------------
@pytest.mark.parametrize("language,expected", [("auto", None), ("Russian", "rus"), ("tuk", "tuk")])
def test_language_mapping(language, expected):
    assert tesseract_lang(language) == expected


def test_language_map_covers_the_ui_choices():
    for language in ("english", "russian", "turkmen"):
        assert language in LANG_MAP


@pytest.mark.skipif(not tesseract_available(), reason="tesseract-ocr is not installed")
def test_ocr_reads_text_from_an_image(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    path = tmp_path / "q.png"
    image = Image.new("RGB", (900, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 40), "What is the capital of France?", fill="black", font=ImageFont.load_default(size=34))
    image.save(path)

    text = extract_text(path)
    assert "capital" in text.lower()


@pytest.mark.skipif(not tesseract_available(), reason="tesseract-ocr is not installed")
def test_ocr_on_a_blank_screen_raises(tmp_path):
    from PIL import Image

    path = tmp_path / "blank.png"
    Image.new("RGB", (400, 200), "white").save(path)
    with pytest.raises(OcrError):
        extract_text(path)
