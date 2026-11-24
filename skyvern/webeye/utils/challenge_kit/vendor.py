"""Vendor challenge pages: DataDome, PerimeterX, BotShield and AWS WAF.

These are not captchas with a checkbox for most visitors — they are interstitials that either pass
themselves once the browser looks like a browser, or ask for one physical gesture (PerimeterX's
"Press & Hold"). The handler detects the vendor from the page it landed on, performs the gesture the
page asks for, and returns so the ladder's own re-probe decides whether the page is really clear.
"""

from __future__ import annotations

import structlog
from playwright.async_api import Page

try:  # inside a Skyvern checkout this is the enum the ladder routes on
    from skyvern.webeye.utils.challenge_signature import ChallengeVendor
except Exception:  # standalone (tests, tooling) the same values are enough
    from enum import StrEnum

    class ChallengeVendor(StrEnum):  # type: ignore[no-redef]
        DATADOME = "datadome"
        PERIMETERX = "perimeterx"
        BOTSHIELD = "botshield"
from skyvern.webeye.utils import human_input

LOG = structlog.get_logger()

_MARKERS: dict[ChallengeVendor, tuple[str, ...]] = {
    ChallengeVendor.DATADOME: (
        "captcha-delivery.com",
        "geo.captcha-delivery.com",
        "dd_captcha",
        "datadome",
    ),
    ChallengeVendor.PERIMETERX: (
        "px-captcha",
        "press &amp; hold",
        "press & hold",
        "perimeterx",
        "_px3",
    ),
    ChallengeVendor.BOTSHIELD: ("botshield", "bshield", "bot shield"),
}

_AWS_WAF_MARKERS = ("token.awswaf.com", "awswaf", "aws-waf", "challenge.js")
_COOKIE_MARKERS: dict[ChallengeVendor, tuple[str, ...]] = {
    ChallengeVendor.DATADOME: ("datadome",),
    ChallengeVendor.PERIMETERX: ("_px3", "_px2", "_px"),
}


async def _body_text(page: Page) -> str:
    try:
        return (await page.evaluate("() => document.body ? document.body.innerText.slice(0, 4000) : ''")) or ""
    except Exception:
        return ""


async def _html(page: Page) -> str:
    try:
        return (await page.content())[:200000]
    except Exception:
        return ""


def _frame_urls(page: Page) -> list[str]:
    try:
        return [frame.url or "" for frame in page.frames]
    except Exception:
        return []


async def _cookies(page: Page) -> set[str]:
    try:
        return {cookie.get("name", "") for cookie in await page.context.cookies()}
    except Exception:
        return set()


async def detect(page: Page) -> ChallengeVendor | None:
    """Which vendor's challenge page this is, or None for an ordinary page."""
    haystack_parts = [page.url or "", await _body_text(page), await _html(page), " ".join(_frame_urls(page))]
    haystack = " ".join(haystack_parts).lower()
    cookies = await _cookies(page)
    for vendor, markers in _MARKERS.items():
        if any(marker in haystack for marker in markers):
            return vendor
        # A vendor's own cookie on a page that mentions the vendor is a block, not a visit.
        if any(name in cookies for name in _COOKIE_MARKERS.get(vendor, ())) and vendor.value in haystack:
            return vendor
    if any(marker in haystack for marker in _AWS_WAF_MARKERS):
        # AWS WAF is not in ChallengeVendor; BotShield's slot is the generic "managed by a vendor" one
        # only when a shield product is named, so an AWS challenge gets no vendor routing.
        LOG.info("AWS WAF challenge detected; no vendor handler")
    return None


async def aws_waf_present(page: Page) -> bool:
    haystack = " ".join(
        [page.url or "", await _body_text(page), await _html(page), " ".join(_frame_urls(page))]
    ).lower()
    return any(marker in haystack for marker in _AWS_WAF_MARKERS)


async def _hold_target(page: Page) -> bool:
    for frame in [page.main_frame, *page.frames]:
        for selector in ("#px-captcha", "[id*='px-captcha']", "[class*='px-captcha']", "div[role='button']"):
            try:
                locator = frame.locator(selector)
                if not await locator.count():
                    continue
                box = await locator.first.bounding_box()
            except Exception:
                continue
            if not box or box["width"] < 40:
                continue
            LOG.info("PerimeterX press-and-hold", selector=selector)
            await human_input.human_press_hold(
                page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, seconds=11.0
            )
            return True
    return False


async def _click_any_checkbox(page: Page) -> bool:
    for frame in [page.main_frame, *page.frames]:
        try:
            locator = frame.locator("input[type='checkbox'], [role='checkbox'], [class*='checkbox']")
            count = await locator.count()
        except Exception:
            continue
        for index in range(min(count, 4)):
            candidate = locator.nth(index)
            try:
                if not await candidate.is_visible():
                    continue
            except Exception:
                continue
            if await human_input.human_click_target(page, candidate):
                return True
    return False


async def handle(page: Page, vendor: ChallengeVendor) -> None:
    """Do whatever gesture this vendor's page asks for; the caller re-probes afterwards."""
    body = (await _body_text(page)).lower()
    LOG.info("Vendor challenge handler start", vendor=vendor.value, asks_hold="hold" in body)
    if vendor is ChallengeVendor.PERIMETERX or "hold" in body:
        if await _hold_target(page):
            await page.wait_for_timeout(2500)
    if await _click_any_checkbox(page):
        LOG.info("Vendor challenge checkbox clicked", vendor=vendor.value)
    # Some DataDome/BotShield pages pass on their own once the fingerprinting finishes.
    for _ in range(10):
        await page.wait_for_timeout(1000)
        if await detect(page) is None:
            LOG.info("Vendor challenge cleared without a gesture", vendor=vendor.value)
            return
    LOG.info("Vendor challenge still present", vendor=vendor.value)


async def handle_aws_waf(page: Page, *, reload_after: float = 12.0) -> bool:
    """AWS WAF's challenge is a JS proof-of-work: wait for it, then reload once with the new token."""
    for _ in range(int(reload_after)):
        await page.wait_for_timeout(1000)
        if not await aws_waf_present(page):
            return True
    LOG.info("AWS WAF challenge still present; reloading with the minted token")
    try:
        await page.reload(wait_until="domcontentloaded", timeout=30000)
    except Exception:
        return False
    for _ in range(10):
        await page.wait_for_timeout(1000)
        if not await aws_waf_present(page):
            return True
    return False
