"""Self-hosted solvers for the challenge arms Skyvern OSS leaves to a person.

The ladder in ``skyvern.webeye.utils.captcha_solver`` already detects a challenge and asks
``AGENT_FUNCTION`` to solve it; the OSS base answers "no" for every arm but the DOM checkbox, which
is why a self-hosted build waits 30 seconds for a human. Each module here answers one of those
seams instead: vision work goes to a Mistral-compatible chat/OCR endpoint, pointer work goes through
``human_input`` so the gestures read as a person's.

Nothing here is required by the rest of Skyvern: a deployment that never calls these modules behaves
exactly as the shipped OSS build does.
"""

from skyvern.webeye.utils.challenge_kit import (
    config,
    hcaptcha,
    image_captcha,
    recaptcha_token,
    slider,
    vendor,
    vision,
)

__all__ = [
    "config",
    "hcaptcha",
    "image_captcha",
    "recaptcha_token",
    "slider",
    "vendor",
    "vision",
]
