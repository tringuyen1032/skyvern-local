"""Human-like pointer input for anti-bot challenge widgets.

Turnstile and reCAPTCHA score the gesture and the browser fingerprint, not only
the click: a jump-to-target click on an obviously automated browser is refused
even when the coordinates are right, and the widget stays unchecked. This module
moves the pointer along a jittered Bezier path, settles on the target, holds the
button for a human interval, and releases. ``STEALTH_INIT_SCRIPT`` removes the
cheap automation tells (``navigator.webdriver``, missing ``chrome.runtime``,
empty plugin list, notification permission mismatch) that the challenge scripts
read before the widget is even drawn.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import structlog
from playwright.async_api import ElementHandle, Locator, Page

LOG = structlog.get_logger()

CHALLENGE_FRAME_MARKER = "challenges.cloudflare.com"
CLEARANCE_COOKIE = "cf_clearance"

STEALTH_INIT_SCRIPT = r"""
(() => {
  const patch = (obj, prop, value) => {
    try { Object.defineProperty(obj, prop, {get: () => value, configurable: true}); } catch (e) {}
  };
  patch(navigator, 'webdriver', undefined);
  patch(navigator, 'languages', ['en-US', 'en']);
  patch(navigator, 'platform', 'MacIntel');
  patch(navigator, 'hardwareConcurrency', 10);
  patch(navigator, 'deviceMemory', 8);
  window.chrome = window.chrome || {};
  window.chrome.runtime = window.chrome.runtime || {
    connect: () => ({onMessage: {addListener: () => {}}, postMessage: () => {}, disconnect: () => {}}),
    sendMessage: () => {},
  };
  window.chrome.app = window.chrome.app || {isInstalled: false, InstallState: {}, RunningState: {}};
  window.chrome.csi = window.chrome.csi || (() => ({}));
  window.chrome.loadTimes = window.chrome.loadTimes || (() => ({}));
  const mkPlugin = (name) => {
    const p = Object.create(Plugin.prototype);
    Object.defineProperty(p, 'name', {value: name});
    Object.defineProperty(p, 'filename', {value: 'internal-pdf-viewer'});
    Object.defineProperty(p, 'description', {value: 'Portable Document Format'});
    Object.defineProperty(p, 'length', {value: 1});
    return p;
  };
  Object.defineProperty(navigator, 'plugins', {
    get: () => ['PDF Viewer', 'Chrome PDF Viewer', 'Chromium PDF Viewer'].map(mkPlugin),
  });
  Object.defineProperty(navigator, 'mimeTypes', {get: () => []});
  const origQuery = navigator.permissions && navigator.permissions.query.bind(navigator.permissions);
  if (origQuery) {
    navigator.permissions.query = (p) =>
      p && p.name === 'notifications' ? Promise.resolve({state: Notification.permission}) : origQuery(p);
  }
  const patchGL = (proto) => {
    const orig = proto.getParameter;
    proto.getParameter = function (p) {
      if (p === 37445) return 'Apple Inc.';
      if (p === 37446) return 'Apple M-series GPU';
      return orig.apply(this, arguments);
    };
  };
  try { patchGL(WebGLRenderingContext.prototype); } catch (e) {}
  try { patchGL(WebGL2RenderingContext.prototype); } catch (e) {}
  delete window.__playwright;
  delete window.__pw_manual;
  delete window.__PW_inspect;
})();
"""


async def human_move(page: Page, x0: float, y0: float, x1: float, y1: float) -> None:
    """Glide the pointer to (x1, y1) on a curved, jittered, irregularly timed path."""
    dist = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    steps = max(10, min(45, int(dist / 13)))
    ctrl_x = (x0 + x1) / 2 + random.uniform(-dist * 0.16, dist * 0.16)
    ctrl_y = (y0 + y1) / 2 + random.uniform(-dist * 0.10, dist * 0.10)
    for i in range(1, steps + 1):
        t = i / steps
        ease = 3 * t * t - 2 * t * t * t  # ease-in-out
        bx = (1 - ease) ** 2 * x0 + 2 * (1 - ease) * ease * ctrl_x + ease * ease * x1
        by = (1 - ease) ** 2 * y0 + 2 * (1 - ease) * ease * ctrl_y + ease * ease * y1
        jx = random.uniform(-1.5, 1.5) if i < steps else 0.0
        jy = random.uniform(-1.2, 1.2) if i < steps else 0.0
        await page.mouse.move(bx + jx, by + jy)
        await page.wait_for_timeout(random.uniform(3, 12))


async def human_click_point(page: Page, x: float, y: float) -> None:
    """Walk to (x, y), settle, press with a human hold, release."""
    try:
        start_x, start_y = random.randint(380, 720), random.randint(260, 480)
        await human_move(page, start_x, start_y, x, y)
    except Exception:
        await page.mouse.move(x, y)
    await page.wait_for_timeout(random.uniform(150, 400))
    await page.mouse.down()
    await page.wait_for_timeout(random.uniform(75, 145))
    await page.mouse.up()


async def human_click_target(page: Page, target: Locator | ElementHandle) -> bool:
    """Human-click a locator or handle; False when it has no box to aim at."""
    try:
        box = await target.bounding_box()
    except Exception:
        box = None
    if not box or box["width"] <= 0 or box["height"] <= 0:
        return False
    await human_click_point(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    return True


async def human_press_hold(page: Page, x: float, y: float, seconds: float) -> None:
    """Press and hold at (x, y): PerimeterX's gate scores a steady hold with a twitching finger.

    The micro-jitter is what separates a held human finger from an untouched ``mouse.down``: the
    challenge listens for the tremor, and a perfectly still cursor keeps the hold from completing.
    """
    try:
        await human_move(page, random.randint(320, 640), random.randint(240, 420), x, y)
    except Exception:
        await page.mouse.move(x, y)
    await page.wait_for_timeout(random.uniform(120, 300))
    await page.mouse.down()
    elapsed = 0.0
    while elapsed < seconds:
        pause = random.uniform(0.12, 0.3)
        await page.mouse.move(x + random.uniform(-0.8, 0.8), y + random.uniform(-0.8, 0.8))
        await page.wait_for_timeout(pause * 1000)
        elapsed += pause
    await page.wait_for_timeout(random.uniform(60, 160))
    await page.mouse.up()


async def human_drag(page: Page, x0: float, y0: float, dx: float, dy: float = 0.0) -> None:
    """Drag a slider handle to the right: accelerate, overshoot a few pixels, correct back.

    A straight constant-speed drag is the single strongest slider tell, so the path eases in, drifts
    past the target, and settles back with a pause before release.
    """
    await page.mouse.move(x0, y0)
    await page.wait_for_timeout(random.uniform(90, 200))
    await page.mouse.down()
    await page.wait_for_timeout(random.uniform(80, 160))
    steps = max(18, min(60, int(abs(dx) / 4)))
    overshoot = random.uniform(2.0, 6.0)
    for i in range(1, steps + 1):
        t = i / steps
        ease = t * t * (3 - 2 * t)
        offset = ease * (dx + overshoot)
        wobble = random.uniform(-0.9, 0.9)
        await page.mouse.move(x0 + offset, y0 + dy * ease + wobble)
        await page.wait_for_timeout(random.uniform(6, 18))
    for i in range(1, 5):
        back = overshoot * (1 - i / 4)
        await page.mouse.move(x0 + dx + back, y0 + dy)
        await page.wait_for_timeout(random.uniform(10, 24))
    await page.wait_for_timeout(random.uniform(120, 260))
    await page.mouse.up()


async def challenge_frames(page: Page) -> list[Any]:
    """Child frames that can host a challenge widget.

    Turnstile usually renders as an out-of-process iframe whose ``url`` is empty until the
    document commits, so a URL-only check reports "no challenge" while the widget is on screen.
    """
    frames: list[Any] = []
    try:
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            url = frame.url or ""
            if CHALLENGE_FRAME_MARKER in url or url in ("", "about:blank"):
                frames.append(frame)
    except Exception:
        return []
    return frames


async def challenge_present(page: Page) -> bool:
    for frame in await challenge_frames(page):
        try:
            element = await frame.frame_element()
            box = await element.bounding_box()
        except Exception:
            continue
        if box and box["width"] > 40 and box["height"] > 20:
            return True
    return False


async def clearance_present(page: Page) -> bool:
    try:
        return any(c.get("name") == CLEARANCE_COOKIE for c in await page.context.cookies())
    except Exception:
        return False


async def _widget_point(page: Page) -> tuple[float, float] | None:
    """The checkbox of a rendered challenge widget, as page coordinates."""
    # Cross-origin frame locators hang on these pages, so aim by the hosting element's box: the
    # checkbox sits ~30px in from the left edge, vertically centered.
    try:
        for el in await page.query_selector_all("iframe"):
            src = (await el.get_attribute("src")) or ""
            if CHALLENGE_FRAME_MARKER not in src:
                continue
            box = await el.bounding_box()
            if box and box["width"] > 40 and box["height"] > 20:
                return box["x"] + 30, box["y"] + box["height"] / 2
    except Exception:
        LOG.debug("Challenge widget iframe probe failed", exc_info=True)
    # Out-of-process widget: the element that hosts the frame carries the same box.
    for frame in await challenge_frames(page):
        try:
            element = await frame.frame_element()
            box = await element.bounding_box()
        except Exception:
            continue
        if box and box["width"] > 40 and box["height"] > 20:
            return box["x"] + 30, box["y"] + box["height"] / 2
    return None


async def solve_visible_challenge(page: Page, *, timeout: float = 20.0, attempts: int = 4) -> bool:
    """Human-click a visible challenge checkbox until it clears or the budget runs out.

    A click that lands before the widget finishes its entrance animation is silently dropped, so a
    failed attempt re-clicks after ``per_attempt`` rather than sitting out a long poll: the wait per
    attempt is what the challenge phase costs, and the checkbox answers within a second or two of a
    click that registers.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    per_attempt = max(2.0, timeout / attempts)
    for attempt in range(attempts):
        if asyncio.get_event_loop().time() >= deadline:
            return False
        point = await _widget_point(page)
        if point is None:
            checkbox = page.locator("input[type='checkbox'][id*='captcha' i], input[type='checkbox'][name*='captcha' i]")
            try:
                if await checkbox.count() and await checkbox.first.is_visible():
                    if await human_click_target(page, checkbox.first):
                        point = (-1.0, -1.0)
            except Exception:
                pass
        if point is None:
            if await clearance_present(page) or not await challenge_present(page):
                return True
            await page.wait_for_timeout(1000)
            continue
        if point != (-1.0, -1.0):
            # Later attempts drift a couple of pixels: a widget that ignored one point often takes the next.
            x = point[0] + 2 * attempt
            y = point[1] + (1 if attempt % 2 else -1) * attempt
            LOG.info("Human-clicking challenge checkbox", attempt=attempt, x=x, y=y)
            await human_click_point(page, x, y)
        for _ in range(int(per_attempt / 0.25)):
            await page.wait_for_timeout(250)
            if await clearance_present(page) or not await challenge_present(page):
                LOG.info("Challenge cleared", attempt=attempt)
                return True
            if asyncio.get_event_loop().time() >= deadline:
                break
    return False
