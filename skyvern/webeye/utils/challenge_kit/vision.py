"""Vision and OCR calls shared by the challenge solvers.

One OpenAI-compatible chat call answers "what does this widget say / which cells match", and the
document OCR endpoint is the fallback when the chat model returns nothing usable. Both take PNG
bytes and never raise: a solver that cannot read an image reports ``None`` and the ladder moves on.
"""

from __future__ import annotations

import base64

import httpx
import structlog

from skyvern.webeye.utils.challenge_kit import config

LOG = structlog.get_logger()


def _data_url(image_png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(image_png).decode()


async def ask(image_png: bytes, prompt: str, *, max_tokens: int = 64) -> str | None:
    """Ask the vision model about one image and return its raw answer."""
    key = config.api_key()
    if not key:
        return None
    body = {
        "model": config.vision_model(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": _data_url(image_png)},
                ],
            }
        ],
        "max_tokens": max_tokens,
        # Greedy sampling is refused by some hosted models, so a hair above zero is the floor.
        "temperature": 0.1,
    }
    try:
        async with httpx.AsyncClient(timeout=config.timeout_seconds()) as client:
            response = await client.post(
                f"{config.api_base()}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        content = payload["choices"][0]["message"].get("content") or ""
        if isinstance(content, list):
            content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        return str(content).strip() or None
    except Exception as exc:
        LOG.info("Challenge vision call failed", error_type=type(exc).__name__)
        return None


async def ocr(image_png: bytes) -> str | None:
    """Read an image with the document OCR endpoint."""
    key = config.api_key()
    if not key:
        return None
    body = {
        "model": config.ocr_model(),
        "document": {"type": "image_url", "image_url": _data_url(image_png)},
    }
    try:
        async with httpx.AsyncClient(timeout=config.timeout_seconds()) as client:
            response = await client.post(
                f"{config.api_base()}/ocr",
                headers={"Authorization": f"Bearer {key}"},
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        pages = payload.get("pages") or []
        text = " ".join(str(page.get("markdown", "")) for page in pages if isinstance(page, dict))
        return text.strip() or None
    except Exception as exc:
        LOG.info("Challenge OCR call failed", error_type=type(exc).__name__)
        return None
