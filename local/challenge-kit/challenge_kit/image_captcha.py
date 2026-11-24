"""Read an image-text captcha with the vision model, falling back to document OCR.

Sites that still ship an image captcha render the characters as an image next to a text field; the
workflow block and the task tools already know how to screenshot that element and fill the field, so
all that was missing is the reading.
"""

from __future__ import annotations

import re

import structlog

from skyvern.webeye.utils.challenge_kit import config, vision

LOG = structlog.get_logger()

_READ_PROMPT = (
    "This image is a CAPTCHA. Read the characters it shows and reply with those characters only: "
    "no words, no punctuation, no explanation. Keep the original upper/lower case."
)
_MAX_LENGTH = 16


def _clean(raw: str | None) -> str | None:
    if not raw:
        return None
    # Models like to wrap the answer in quotes or prefix it with "The characters are:".
    candidate = raw.strip().splitlines()[0] if raw.strip() else ""
    candidate = re.sub(r"^\s*(the\s+)?(characters?|text|captcha)\s*(are|is)\s*[:\-]?\s*", "", candidate, flags=re.I)
    candidate = re.sub(r"[^A-Za-z0-9]", "", candidate)
    if not candidate or len(candidate) > _MAX_LENGTH:
        return None
    return candidate


async def read_text(image_png: bytes) -> str | None:
    """The characters shown in ``image_png``, or None when nothing readable came back.

    One read of a distorted five-character image is a coin flip on the length, so the answer is
    confirmed by a second read: an agreed answer is returned as-is, a disagreement is broken by a
    third read and settles on the value two of them share.
    """
    if not image_png:
        return None
    first = _clean(await vision.ask(image_png, _READ_PROMPT, max_tokens=32))
    if not first:
        return _clean(await vision.ocr(image_png))
    second = _clean(await vision.ask(image_png, _READ_PROMPT, max_tokens=32))
    if not second or second == first:
        return first
    third = _clean(await vision.ask(image_png, _READ_PROMPT, max_tokens=32))
    for candidate in (first, second, third):
        if candidate and [first, second, third].count(candidate) >= 2:
            LOG.info("Image captcha read settled by consensus")
            return candidate
    LOG.info("Image captcha reads disagreed", first_len=len(first), second_len=len(second))
    return first


async def enabled() -> bool:
    """Whether an OCR/text read can happen at all on this deployment."""
    return config.available()
