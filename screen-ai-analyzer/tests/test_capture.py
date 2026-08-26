"""7. Screenshot cleanup (+ preprocessing and backend selection)."""

from pathlib import Path

import pytest

from app.capture.preprocess import prepare_for_ocr, prepare_for_vision
from app.capture.portal import uri_to_path
from app.capture.screenshot import CaptureError, ScreenCapturer, Screenshot
from app.utils.session import SessionInfo


def _make_shot(tmp_path) -> Screenshot:
    path = tmp_path / "shot.png"
    path.write_bytes(b"not-a-real-png")
    return Screenshot(path=path, backend="test")


def test_screenshot_is_deleted_by_the_context_manager(tmp_path):
    shot = _make_shot(tmp_path)
    with shot as opened:
        assert opened.path.exists()
        assert opened.read_bytes() == b"not-a-real-png"
    assert not shot.path.exists()


def test_cleanup_is_idempotent(tmp_path):
    shot = _make_shot(tmp_path)
    shot.cleanup()
    shot.cleanup()  # must not raise
    assert not shot.path.exists()


def test_screenshot_is_deleted_even_when_processing_fails(tmp_path):
    shot = _make_shot(tmp_path)
    with pytest.raises(ValueError):
        with shot:
            raise ValueError("analysis blew up")
    assert not shot.path.exists()


def test_capturer_deletes_partial_files_from_failed_backends(tmp_path, monkeypatch):
    created = []

    def failing_backend(target: Path) -> bool:
        target.write_bytes(b"")  # empty -> invalid
        created.append(target)
        return False

    capturer = ScreenCapturer(SessionInfo("wayland", "gnome"))
    monkeypatch.setattr(capturer, "backends", lambda: [("broken", failing_backend)])
    with pytest.raises(CaptureError):
        capturer.capture()
    assert created and not any(path.exists() for path in created)


def test_successful_capture_returns_a_real_file(tmp_path, screenshot_png):
    def working_backend(target: Path) -> bool:
        target.write_bytes(screenshot_png.read_bytes())
        return True

    capturer = ScreenCapturer(SessionInfo("wayland", "gnome"))
    capturer.backends = lambda: [("stub", working_backend)]
    with capturer.capture() as shot:
        assert shot.backend == "stub"
        assert shot.path.stat().st_size > 0
        path = shot.path
    assert not path.exists()


def test_backend_order_prefers_portal_on_wayland():
    names = [name for name, _ in ScreenCapturer(SessionInfo("wayland", "gnome")).backends()]
    assert names[0] == "portal"
    assert "gnome-screenshot" in names


def test_backend_order_prefers_qt_on_x11():
    names = [name for name, _ in ScreenCapturer(SessionInfo("x11", "gnome")).backends()]
    assert names[0] == "qt"


def test_capture_error_message_mentions_the_session():
    capturer = ScreenCapturer(SessionInfo("wayland", "gnome"))
    capturer.backends = lambda: []
    with pytest.raises(CaptureError) as excinfo:
        capturer.capture()
    assert "wayland" in str(excinfo.value)


# -- preprocessing ---------------------------------------------------------
def test_prepare_for_vision_downscales_and_encodes(screenshot_png):
    prepared = prepare_for_vision(screenshot_png, max_width=400)
    assert prepared.width == 400
    assert prepared.mime_type == "image/jpeg"
    assert prepared.data.startswith(b"\xff\xd8")  # JPEG magic
    assert len(prepared) < screenshot_png.stat().st_size * 4


def test_prepare_for_vision_accepts_bytes(screenshot_png):
    prepared = prepare_for_vision(screenshot_png.read_bytes(), max_width=200)
    assert prepared.width == 200


def test_small_images_are_not_upscaled(screenshot_png):
    prepared = prepare_for_vision(screenshot_png, max_width=5000)
    assert prepared.width == 800


def test_prepare_for_ocr_returns_grayscale(screenshot_png):
    image = prepare_for_ocr(screenshot_png)
    assert image.mode == "L"
    image.close()


# -- portal helper ---------------------------------------------------------
@pytest.mark.parametrize(
    "uri,expected",
    [
        ("file:///tmp/shot.png", "/tmp/shot.png"),
        ("file:///home/user/My%20Pictures/a.png", "/home/user/My Pictures/a.png"),
        ("/tmp/plain.png", "/tmp/plain.png"),
    ],
)
def test_uri_to_path(uri, expected):
    assert str(uri_to_path(uri)) == expected


def test_uri_to_path_rejects_remote():
    assert uri_to_path("https://example.com/a.png") is None
