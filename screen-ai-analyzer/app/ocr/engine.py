"""OCR fallback (Tesseract via pytesseract).

Used only when the selected provider cannot read images, so that a screenshot
is never sent to a text-only model.
"""

from __future__ import annotations

import logging
import shutil
from typing import Optional, Union

from app.capture.preprocess import prepare_for_ocr

log = logging.getLogger(__name__)

#: config ``language`` value -> tesseract traineddata code
LANG_MAP = {
    "auto": "",
    "english": "eng",
    "en": "eng",
    "russian": "rus",
    "ru": "rus",
    "german": "deu",
    "de": "deu",
    "french": "fra",
    "fr": "fra",
    "spanish": "spa",
    "es": "spa",
    "turkish": "tur",
    "tr": "tur",
    "turkmen": "tuk",
    "tk": "tuk",
}


class OcrError(RuntimeError):
    """OCR is unavailable or produced nothing usable."""


def tesseract_available() -> bool:
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def tesseract_lang(language: str) -> Optional[str]:
    code = LANG_MAP.get((language or "auto").strip().lower())
    if code:
        return code
    lowered = (language or "").strip().lower()
    if len(lowered) == 3 and lowered.isalpha():  # already a traineddata code
        return lowered
    return None


def extract_text(source: Union[str, bytes], language: str = "auto", max_width: int = 2400) -> str:
    """Run OCR over an image and return the recognised text."""
    if not tesseract_available():
        raise OcrError(
            "OCR is not available - install tesseract-ocr to use the text-only fallback"
        )
    import pytesseract

    image = prepare_for_ocr(source, max_width=max_width)
    kwargs = {}
    lang = tesseract_lang(language)
    if lang:
        kwargs["lang"] = lang
    try:
        text = pytesseract.image_to_string(image, **kwargs)
    except Exception as exc:
        log.exception("OCR failed")
        raise OcrError(f"OCR failed: {str(exc)[:120]}") from exc
    finally:
        image.close()

    text = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if len(text.strip()) < 3:
        raise OcrError("no readable text found on the screen")
    log.info("OCR extracted %d characters", len(text))
    return text
