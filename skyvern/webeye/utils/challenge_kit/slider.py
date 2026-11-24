"""Slider challenges: find the gap, then drag the handle there like a person.

Geetest ships two canvases — the background with a puzzle-shaped notch and the piece itself — so the
gap offset is measurable offline: the notch is the one solid dark run in the background at the piece's
width, and where that fails the piece is matched against the background through its alpha mask. The
handle is then dragged with an eased, overshooting path, because a constant-speed slide is the
classic slider tell.
"""

from __future__ import annotations

import io
import random
from typing import Any

import numpy as np
import structlog
from PIL import Image
from playwright.async_api import Page

from skyvern.webeye.utils import human_input

LOG = structlog.get_logger()

_BG_SELECTORS = (".geetest_canvas_bg", "canvas[class*='bg']", ".geetest_bg", "canvas[class*='background']")
_PIECE_SELECTORS = (".geetest_canvas_slice", "canvas[class*='slice']", ".geetest_slice", "canvas[class*='piece']")
_HANDLE_SELECTORS = (".geetest_slider_button", ".geetest_btn", "div[class*='slider_button']", "[class*='slider-btn']")
_SUCCESS_MARKERS = (".geetest_success_radar_tip", ".geetest_panel_success", "[class*='success'] [class*='tip']")


def _frames(page: Page) -> list[Any]:
    frames: list[Any] = [page.main_frame]
    try:
        frames.extend(frame for frame in page.frames if frame is not page.main_frame)
    except Exception:
        pass
    return frames


async def _first_visible(frame: Any, selectors: tuple[str, ...]) -> Any | None:
    for selector in selectors:
        try:
            locator = frame.locator(selector)
            count = await locator.count()
        except Exception:
            continue
        for index in range(min(count, 3)):
            candidate = locator.nth(index)
            try:
                if await candidate.is_visible():
                    return candidate
            except Exception:
                continue
    return None


def gap_offset(bg_png: bytes, piece_png: bytes) -> int | None:
    """Left edge of the gap, in background pixels, or None when neither method finds it."""
    try:
        background = Image.open(io.BytesIO(bg_png)).convert("RGB")
        piece = Image.open(io.BytesIO(piece_png)).convert("RGBA")
    except Exception:
        return None
    bg = np.asarray(background, dtype=np.int16)
    pc = np.asarray(piece, dtype=np.int16)
    if bg.size == 0 or pc.size == 0:
        return None
    piece_width = min(pc.shape[1], bg.shape[1])
    height = min(pc.shape[0], bg.shape[0])
    alpha = pc[:height, :piece_width, 3]
    mask = alpha > 200
    if mask.sum() < 60:
        mask = np.ones((height, piece_width), dtype=bool)

    notch = _notch_by_darkness(bg, piece_width)
    if notch is not None:
        return notch

    # Neither method read the notch, so align the piece's edges onto the background's edges: a notch
    # keeps the outline even when its fill is a flat silhouette that never matches the piece's colours.
    piece_gray = pc[:height, :piece_width, :3].mean(axis=2)
    bg_gray = bg[: height, :, :3].mean(axis=2)
    piece_edges = np.abs(np.diff(piece_gray, axis=1))
    bg_edges = np.abs(np.diff(bg_gray, axis=1))
    edge_mask = mask[:, :-1] & mask[:, 1:]
    if edge_mask.sum() < 40:
        return None
    best_x, best_score = None, -1e18
    for x in range(0, max(1, bg_edges.shape[1] - piece_width)):
        patch = bg_edges[:, x : x + piece_width - 1]
        if patch.shape != piece_edges.shape:
            continue
        score = -float(np.abs(patch[edge_mask] - piece_edges[edge_mask]).mean())
        if score > best_score:
            best_x, best_score = x, score
    return best_x


def _notch_by_darkness(bg: np.ndarray, piece_width: int) -> int | None:
    """The gap as the one column run much darker than the rest of the background.

    A flat threshold misses a notch that only covers part of the height, so the test is against the
    background's own median brightness: the notch is the region that stands out from its surroundings.
    """
    gray = bg.mean(axis=2)
    height, width = gray.shape
    if height < 8 or width < 8:
        return None
    band = gray[int(height * 0.25) :, :]
    column_mean = band.mean(axis=0)
    baseline = float(np.median(column_mean))
    spread = float(column_mean.std()) or 1.0
    columns = column_mean < baseline - max(8.0, spread)
    if not columns.any():
        return None
    best: tuple[float, int] | None = None
    run_start = None
    for index in range(width + 1):
        inside = index < width and bool(columns[index])
        if inside and run_start is None:
            run_start = index
        elif not inside and run_start is not None:
            run_width = index - run_start
            if 0.5 * piece_width <= run_width <= 1.8 * piece_width:
                darkness = baseline - float(column_mean[run_start:index].mean())
                if best is None or darkness > best[0]:
                    best = (darkness, run_start)
            run_start = None
    return best[1] if best else None


async def present(page: Page) -> bool:
    for frame in _frames(page):
        if await _first_visible(frame, _HANDLE_SELECTORS) is not None and (
            await _first_visible(frame, _BG_SELECTORS) is not None
        ):
            return True
    return False


async def _cleared(page: Page) -> bool:
    for frame in _frames(page):
        for selector in _SUCCESS_MARKERS:
            try:
                locator = frame.locator(selector)
                if await locator.count() and await locator.first.is_visible():
                    return True
            except Exception:
                continue
        if await _first_visible(frame, _HANDLE_SELECTORS) is None:
            continue
        if await _first_visible(frame, _BG_SELECTORS) is None:
            continue
        return False
    return not await present(page)


async def solve(page: Page) -> bool:
    """Solve a slider challenge on the page; False when the widget is unrecognised or refused."""
    for attempt in range(2):
        handle = frame = background = piece = None
        for candidate_frame in _frames(page):
            handle = await _first_visible(candidate_frame, _HANDLE_SELECTORS)
            if handle is None:
                continue
            background = await _first_visible(candidate_frame, _BG_SELECTORS)
            piece = await _first_visible(candidate_frame, _PIECE_SELECTORS)
            if background is not None and piece is not None:
                frame = candidate_frame
                break
        if handle is None or background is None or piece is None or frame is None:
            return False
        try:
            bg_png = await background.screenshot(timeout=5000)
            piece_png = await piece.screenshot(timeout=5000)
        except Exception:
            return False
        offset = gap_offset(bg_png, piece_png)
        if offset is None:
            LOG.info("Slider gap not found", attempt=attempt)
            return False
        try:
            background_box = await background.bounding_box()
            handle_box = await handle.bounding_box()
        except Exception:
            return False
        if not background_box or not handle_box:
            return False
        # The rendered track is wider than the puzzle: scale the pixel offset into pointer travel.
        try:
            layout = frame.locator("[class*='geetest'][class*='slider'], [class*='slide']").first
            track_box = await layout.bounding_box()
        except Exception:
            track_box = None
        track_width = (track_box["width"] if track_box else background_box["width"] + handle_box["width"]) - handle_box["width"]
        scale = track_width / background_box["width"] if background_box["width"] else 1.0
        travel = offset * scale
        if attempt:
            travel += random.uniform(-1.5, 1.5)
        LOG.info("Slider dragging to gap", attempt=attempt, offset=offset, travel=round(travel, 1), scale=round(scale, 3))
        await human_input.human_drag(
            page,
            handle_box["x"] + handle_box["width"] / 2,
            handle_box["y"] + handle_box["height"] / 2,
            travel,
        )
        for _ in range(12):
            await page.wait_for_timeout(250)
            if await _cleared(page):
                LOG.info("Slider cleared", attempt=attempt)
                return True
    return False
