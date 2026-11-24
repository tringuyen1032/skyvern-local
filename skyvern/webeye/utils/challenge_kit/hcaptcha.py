"""hCaptcha: the checkbox gate plus the area-select challenge it escalates to.

The checkbox is the same out-of-process widget problem as Turnstile, so it goes through
``human_input``. The escalation is a grid of images and a sentence describing what to pick, which a
vision model can answer: the grid is screenshotted, numbered left-to-right, and the cells it names
are clicked as a person would click them, then submitted. Two rounds are normal and a wrong round is
simply re-asked, which is exactly what a person does.
"""

from __future__ import annotations

import asyncio
import io
import re
from typing import Any

import structlog
from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import Page

from skyvern.webeye.utils import human_input
from skyvern.webeye.utils.challenge_kit import config, vision

LOG = structlog.get_logger()

_FRAME_MARKER = "hcaptcha.com"
_CELL_SELECTOR = ".task-image, div[class*='task-image'], .image-wrapper, div[class*='challenge-image']"
_SUBMIT_SELECTOR = "#_hcaptcha_button_submit, .button-submit, div[class*='button-submit']"
_PROMPT_SELECTOR = ".prompt-text, .challenge-prompt, div[class*='prompt']"

_GRID_PROMPT = (
    "This is a hCaptcha image grid. Every cell carries its own number in the corner.\n"
    "The task says: {task}\n"
    "Reply with the numbers written on the cells that match the task, comma separated, and nothing "
    "else. Reply 'none' if no cell matches."
)


def _frames(page: Page) -> list[Any]:
    try:
        return [frame for frame in page.frames if _FRAME_MARKER in (frame.url or "")]
    except Exception:
        return []


async def present(page: Page) -> bool:
    """Whether an hCaptcha widget or challenge is on screen."""
    for frame in _frames(page):
        try:
            element = await frame.frame_element()
            box = await element.bounding_box()
        except Exception:
            continue
        if box and box["width"] > 30 and box["height"] > 20:
            return True
    try:
        marker = page.locator(".h-captcha, [data-hcaptcha-widget-id]")
        return await marker.count() > 0
    except Exception:
        return False


async def _checkbox_frame(page: Page) -> Any | None:
    for frame in _frames(page):
        url = frame.url or ""
        if "/challenge" in url or "checkbox" not in url:
            continue
        return frame
    return None


async def _challenge_frame(page: Page) -> Any | None:
    for frame in _frames(page):
        if "/challenge" in (frame.url or ""):
            return frame
    return None


async def _click_checkbox(page: Page) -> bool:
    frame = await _checkbox_frame(page)
    if frame is None:
        return False
    for selector in ("#checkbox", "[id*='checkbox']", "div[role='checkbox']"):
        try:
            locator = frame.locator(selector)
            if await locator.count() == 0:
                continue
            box = await locator.first.bounding_box()
            if box and box["width"] > 0:
                await human_input.human_click_point(page, box["x"] + 12, box["y"] + box["height"] / 2)
                return True
        except Exception:
            continue
    try:
        element = await frame.frame_element()
        box = await element.bounding_box()
    except Exception:
        box = None
    if box and box["width"] > 30:
        await human_input.human_click_point(page, box["x"] + 30, box["y"] + box["height"] / 2)
        return True
    return False


async def _cells(frame: Any) -> list[Any]:
    for selector in (_CELL_SELECTOR.split(", ")):
        try:
            locator = frame.locator(selector)
            count = await locator.count()
        except Exception:
            continue
        if count >= 4:
            return [locator.nth(index) for index in range(count)]
    return []


async def _task_text(frame: Any) -> str:
    for selector in _PROMPT_SELECTOR.split(", "):
        try:
            locator = frame.locator(selector)
            if await locator.count() == 0:
                continue
            text = (await locator.first.inner_text(timeout=2000)).strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def _parse_cells(answer: str | None, limit: int) -> list[int]:
    if not answer:
        return []
    if re.search(r"\bnone\b", answer, re.I):
        return []
    picked: list[int] = []
    for token in re.findall(r"\d+", answer):
        index = int(token) - 1
        if 0 <= index < limit and index not in picked:
            picked.append(index)
    return picked


def _label_cells(image_png: bytes, offsets: list[tuple[float, float]]) -> bytes:
    """Draw each cell's number onto the grid we send, so the model reads a label instead of counting.

    Asking a vision model to number a grid itself is where the off-by-one picks come from: it sees
    nine pictures, not nine coordinates. ``offsets`` are the cell corners inside the screenshot.
    """
    try:
        image = Image.open(io.BytesIO(image_png)).convert("RGB")
    except Exception:
        return image_png
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default(size=22)
    except Exception:
        font = ImageFont.load_default()
    for index, (x, y) in enumerate(offsets, start=1):
        label = str(index)
        width = 10 + 13 * len(label)
        draw.rectangle((x + 1, y + 1, x + 1 + width, y + 29), fill=(255, 255, 255), outline=(0, 0, 0))
        draw.text((x + 6, y + 3), label, fill=(0, 0, 0), font=font)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


async def _vote_cells(image: bytes, task: str, cell_count: int) -> list[int]:
    """Pick the cells two independent readings agree on.

    A single reading of a sixteen-cell grid is regularly one cell off, and hCaptcha fails the round
    for a cell too many as readily as one too few, so each cell needs a second opinion: two answers
    that agree are taken as-is, and a split is settled per cell by a third reading.
    """
    first = _parse_cells(await vision.ask(image, _GRID_PROMPT.format(task=task), max_tokens=48), cell_count)
    second = _parse_cells(await vision.ask(image, _GRID_PROMPT.format(task=task), max_tokens=48), cell_count)
    if first == second:
        return first
    third = _parse_cells(await vision.ask(image, _GRID_PROMPT.format(task=task), max_tokens=48), cell_count)
    votes: dict[int, int] = {}
    for answer in (first, second, third):
        for index in answer:
            votes[index] = votes.get(index, 0) + 1
    agreed = sorted(index for index, count in votes.items() if count >= 2)
    LOG.info("hCaptcha cell votes split", first=first, second=second, third=third, agreed=agreed)
    return agreed


async def _solve_round(page: Page, frame: Any) -> bool:
    cells = await _cells(frame)
    if not cells:
        return False
    task = await _task_text(frame)
    try:
        grid = frame.locator(".challenge-container, [class*='challenge-container'], body")
        grid_element = grid.first
        image = await grid_element.screenshot(timeout=5000)
        grid_box = await grid_element.bounding_box()
    except Exception:
        image, grid_box = b"", None
    if not image:
        return False
    offsets: list[tuple[float, float]] = []
    for cell in cells:
        try:
            box = await cell.bounding_box()
        except Exception:
            box = None
        if not box or not grid_box:
            offsets.append((0.0, 0.0))
            continue
        offsets.append((box["x"] - grid_box["x"], box["y"] - grid_box["y"]))
    image = _label_cells(image, offsets)
    picked = await _vote_cells(image, task or "select the matching images", len(cells))
    LOG.info("hCaptcha grid answer", task=task[:60], cells=len(picked), answer=(answer or "")[:40])
    if not picked:
        return False
    for index in picked:
        try:
            box = await cells[index].bounding_box()
        except Exception:
            continue
        if not box:
            continue
        await human_input.human_click_point(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await page.wait_for_timeout(220)
    for selector in _SUBMIT_SELECTOR.split(", "):
        try:
            submit = frame.locator(selector)
            if await submit.count() == 0:
                continue
            box = await submit.first.bounding_box()
            if box:
                await human_input.human_click_point(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                return True
        except Exception:
            continue
    return False


async def solve(page: Page) -> bool:
    """Clear an hCaptcha on the page: checkbox first, then up to three grid rounds."""
    if not await present(page):
        return True
    if not config.available():
        LOG.info("hCaptcha detected but no vision backend is configured")
        return False
    if await _challenge_frame(page) is None and await _click_checkbox(page):
        LOG.info("hCaptcha checkbox clicked")
        for _ in range(12):
            await page.wait_for_timeout(500)
            if not await present(page):
                return True
            if await _challenge_frame(page) is not None:
                break
    for round_index in range(3):
        frame = await _challenge_frame(page)
        if frame is None:
            return not await present(page)
        try:
            solved_round = await _solve_round(page, frame)
        except Exception:
            LOG.info("hCaptcha round raised", round=round_index, exc_info=True)
            solved_round = False
        if not solved_round:
            break
        for _ in range(16):
            await page.wait_for_timeout(500)
            if await _challenge_frame(page) is None:
                break
        if await _challenge_frame(page) is None and not await present(page):
            LOG.info("hCaptcha cleared", rounds=round_index + 1)
            return True
    await asyncio.sleep(0)
    return not await present(page)
