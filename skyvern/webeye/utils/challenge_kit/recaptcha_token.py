"""Mint a reCAPTCHA token in the page and hand it to the form.

Invisible/v3 widgets never show a checkbox: the site asks ``grecaptcha.execute`` for a token and
posts it. There is nothing to click, so the solve is to call the same API the page would — from the
page's own origin, with its own key, on the fingerprint the challenge already accepted — then write
the token into the response field the form reads.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import structlog
from playwright.async_api import Page

LOG = structlog.get_logger()

_TOKEN_JS = r"""
async ([sitekey, action]) => {
  const ready = (api) => new Promise((resolve) => {
    try { api.ready(resolve); } catch (e) { resolve(); }
  });
  const load = (key) => new Promise((resolve, reject) => {
    const g = window.grecaptcha;
    if (g && (g.execute || (g.enterprise && g.enterprise.execute))) return resolve();
    const script = document.createElement('script');
    script.src = 'https://www.google.com/recaptcha/api.js?render=' + encodeURIComponent(key);
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('recaptcha script failed'));
    document.head.appendChild(script);
  });
  try { await load(sitekey); } catch (e) { return ''; }
  const api = (window.grecaptcha.enterprise && window.grecaptcha.enterprise.execute)
    ? window.grecaptcha.enterprise
    : window.grecaptcha;
  if (!api || !api.execute) return '';
  await ready(api);
  try {
    return await api.execute(sitekey, { action: action });
  } catch (e) {
    return '';
  }
}
"""

_INJECT_JS = r"""
(token) => {
  const fields = document.querySelectorAll(
    'textarea[name="g-recaptcha-response"], textarea#g-recaptcha-response, ' +
    'textarea[id^="g-recaptcha-response"], input[name="g-recaptcha-response"]'
  );
  const fire = (el) => {
    el.value = token;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  let written = 0;
  fields.forEach((el) => { fire(el); written += 1; });
  if (!written) {
    const field = document.createElement('textarea');
    field.name = 'g-recaptcha-response';
    field.id = 'g-recaptcha-response';
    field.style.display = 'none';
    document.body.appendChild(field);
    fire(field);
    written += 1;
  }
  try {
    window.dispatchEvent(new CustomEvent('skyvern-recaptcha-token', { detail: token }));
  } catch (e) {}
  return written;
}
"""

_ACTION_GUESSES = ("submit", "verify", "login", "signup", "homepage")


def _sitekey_from_url(url: str) -> str | None:
    try:
        query = parse_qs(urlparse(url).query)
    except Exception:
        return None
    for key in ("k", "sitekey"):
        values = query.get(key)
        if values and values[0]:
            return values[0]
    return None


async def _sitekey(page: Page) -> tuple[str | None, bool]:
    """The key the page already uses, and whether it is an Enterprise widget."""
    enterprise = False
    try:
        for frame in page.frames:
            url = frame.url or ""
            if "google.com/recaptcha" not in url:
                continue
            enterprise = enterprise or "/enterprise/" in url
            key = _sitekey_from_url(url)
            if key:
                return key, enterprise
    except Exception:
        pass
    try:
        key = await page.evaluate(
            "() => { const el = document.querySelector('[data-sitekey]'); return el ? el.getAttribute('data-sitekey') : null; }"
        )
        if key:
            return str(key), enterprise
    except Exception:
        pass
    try:
        html = await page.content()
    except Exception:
        return None, enterprise
    match = re.search(r"['\"]sitekey['\"]\s*:\s*['\"]([A-Za-z0-9_-]{20,})['\"]", html)
    return (match.group(1) if match else None), enterprise


async def present(page: Page) -> bool:
    try:
        if await page.locator(".g-recaptcha, iframe[src*='recaptcha'], [data-sitekey]").count():
            return True
    except Exception:
        pass
    try:
        return any("google.com/recaptcha" in (frame.url or "") for frame in page.frames)
    except Exception:
        return False


async def solve(page: Page) -> bool:
    """Mint a token for the page's own key and write it into the form; False when nothing landed."""
    sitekey, enterprise = await _sitekey(page)
    if not sitekey:
        LOG.info("reCAPTCHA token solve found no sitekey")
        return False
    for action in _ACTION_GUESSES:
        token: Any = ""
        try:
            token = await page.evaluate(_TOKEN_JS, [sitekey, action])
        except Exception:
            LOG.info("reCAPTCHA execute raised", action=action, exc_info=True)
            continue
        if not isinstance(token, str) or len(token) < 20:
            continue
        try:
            written = await page.evaluate(_INJECT_JS, token)
        except Exception:
            written = 0
        LOG.info(
            "reCAPTCHA token minted",
            action=action,
            enterprise=enterprise,
            length=len(token),
            fields=int(written or 0),
        )
        return True
    return False
