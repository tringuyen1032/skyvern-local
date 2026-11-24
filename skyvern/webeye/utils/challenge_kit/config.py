"""Settings for the local challenge solvers.

Everything is read from the environment so a self-hosted build can point the solvers at whichever
OpenAI-compatible endpoint it already pays for; with no key configured every solver reports itself
unavailable and the ladder falls back to its shipped behaviour.

The server loads ``.env`` into settings, not into ``os.environ``, so a key placed there for the app
would otherwise be invisible here; the file is read directly as the second source.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

DEFAULT_API_BASE = "https://api.mistral.ai/v1"
# A small vision model reads a 5-character captcha faster than a large one and is accurate enough for
# the job; the document OCR model is the fallback for images that are plain text on noise.
DEFAULT_VISION_MODEL = "mistral-small-latest"
DEFAULT_OCR_MODEL = "mistral-ocr-latest"

ENV_API_KEY = "CHALLENGE_VISION_API_KEY"
ENV_FALLBACK_API_KEY = "MISTRAL_API_KEY"
ENV_API_BASE = "CHALLENGE_VISION_API_BASE"
ENV_VISION_MODEL = "CHALLENGE_VISION_MODEL"
ENV_OCR_MODEL = "CHALLENGE_OCR_MODEL"
ENV_TIMEOUT = "CHALLENGE_VISION_TIMEOUT"

_ENV_FILES = (".env", "../.env")


@lru_cache(maxsize=1)
def _env_file_values() -> dict[str, str]:
    try:
        from dotenv import dotenv_values
    except Exception:
        return {}
    for name in _ENV_FILES:
        path = Path(name)
        if not path.is_file():
            continue
        try:
            return {key: value for key, value in dotenv_values(path).items() if value is not None}
        except Exception:
            continue
    return {}


def _get(name: str) -> str | None:
    return os.getenv(name) or _env_file_values().get(name) or None


def api_key() -> str | None:
    return _get(ENV_API_KEY) or _get(ENV_FALLBACK_API_KEY)


def api_base() -> str:
    return (_get(ENV_API_BASE) or DEFAULT_API_BASE).rstrip("/")


def vision_model() -> str:
    return _get(ENV_VISION_MODEL) or DEFAULT_VISION_MODEL


def ocr_model() -> str:
    return _get(ENV_OCR_MODEL) or DEFAULT_OCR_MODEL


def timeout_seconds() -> float:
    try:
        return float(_get(ENV_TIMEOUT) or 60)
    except ValueError:
        return 60.0


def available() -> bool:
    """Whether a vision backend is configured at all."""
    return bool(api_key())
