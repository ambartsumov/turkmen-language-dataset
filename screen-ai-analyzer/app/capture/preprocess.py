"""Image preprocessing before the image is sent to a vision model."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

JPEG_MIME = "image/jpeg"
PNG_MIME = "image/png"


@dataclass
class PreparedImage:
    data: bytes
    mime_type: str
    width: int
    height: int

    def __len__(self) -> int:  # convenient in logs/tests
        return len(self.data)


def _open(source: Union[Path, bytes, "Image.Image"]) -> "Image.Image":
    if isinstance(source, Image.Image):
        return source
    if isinstance(source, (bytes, bytearray)):
        return Image.open(io.BytesIO(source))
    return Image.open(Path(source))


def prepare_for_vision(
    source: Union[Path, bytes, "Image.Image"],
    max_width: int = 1600,
    jpeg_quality: int = 85,
) -> PreparedImage:
    """Downscale, flatten and re-encode the screenshot.

    Smaller payload -> faster upload and fewer tokens, while text on a normal
    desktop screenshot stays readable.
    """
    with _open(source) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            converted = image.convert("RGBA")
            background.paste(converted, mask=converted.split()[-1])
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")

        if image.width > max_width:
            ratio = max_width / float(image.width)
            image = image.resize(
                (max_width, max(1, int(image.height * ratio))), Image.LANCZOS
            )

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
        log.debug("Prepared image %dx%d, %d bytes", image.width, image.height, buffer.tell())
        return PreparedImage(
            data=buffer.getvalue(),
            mime_type=JPEG_MIME,
            width=image.width,
            height=image.height,
        )


def prepare_for_ocr(source: Union[Path, bytes, "Image.Image"], max_width: int = 2400) -> "Image.Image":
    """Grayscale + autocontrast + upscale-to-sane-size for the OCR fallback."""
    image = _open(source)
    image = ImageOps.exif_transpose(image).convert("L")
    image = ImageOps.autocontrast(image)
    if image.width > max_width:
        ratio = max_width / float(image.width)
        image = image.resize((max_width, max(1, int(image.height * ratio))), Image.LANCZOS)
    return image
