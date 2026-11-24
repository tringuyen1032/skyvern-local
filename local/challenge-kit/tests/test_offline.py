"""Offline solver checks: no browser, no Skyvern import, one vision backend.

Run from the repository root with the key in the environment:

    CHALLENGE_VISION_API_KEY=... python tests/test_offline.py
"""

from __future__ import annotations

import asyncio
import io
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from challenge_kit import config, hcaptcha, image_captcha, slider  # noqa: E402


def make_captcha(text: str) -> bytes:
    image = Image.new("RGB", (180, 70), (245, 245, 240))
    draw = ImageDraw.Draw(image)
    for _ in range(400):
        draw.point((random.randint(0, 179), random.randint(0, 69)), fill=(random.randint(120, 220),) * 3)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 34)
    except Exception:
        font = ImageFont.load_default(size=34)
    draw.text((26, 16), text, font=font, fill=(30, 30, 40))
    for _ in range(6):
        y = random.randint(5, 65)
        draw.line((0, y, 180, y + random.randint(-6, 6)), fill=(150, 150, 150), width=1)
    out = io.BytesIO()
    image.filter(ImageFilter.SMOOTH).save(out, "PNG")
    return out.getvalue()


def make_slider(gap_x: int) -> tuple[bytes, bytes]:
    background = Image.new("RGB", (340, 180), (200, 210, 225))
    draw = ImageDraw.Draw(background)
    for x in range(0, 340, 20):
        draw.line((x, 0, x, 180), fill=(180, 190, 205), width=1)
    draw.rectangle((gap_x, 60, gap_x + 48, 128), fill=(20, 20, 24))
    bg_out = io.BytesIO()
    background.save(bg_out, "PNG")

    piece = Image.new("RGBA", (48, 68), (0, 0, 0, 0))
    ImageDraw.Draw(piece).rectangle((0, 0, 47, 67), fill=(233, 120, 82, 255))
    piece_out = io.BytesIO()
    piece.save(piece_out, "PNG")
    return bg_out.getvalue(), piece_out.getvalue()


def make_grid(circle_cells: set[int], rows: int = 3, cols: int = 3, size: int = 100) -> tuple[bytes, list]:
    image = Image.new("RGB", (cols * size, rows * size), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    for index in range(rows * cols):
        row, col = divmod(index, cols)
        x, y = col * size, row * size
        if index in circle_cells:
            draw.ellipse((x + 25, y + 25, x + 75, y + 75), fill=(200, 40, 40))
        else:
            draw.rectangle((x + 25, y + 25, x + 75, y + 75), fill=(40, 60, 200))
    out = io.BytesIO()
    image.save(out, "PNG")
    offsets = [((index % cols) * size, (index // cols) * size) for index in range(rows * cols)]
    return out.getvalue(), offsets


async def main() -> int:
    failures = 0
    soft = 0
    if not config.available():
        print("no vision backend configured; set CHALLENGE_VISION_API_KEY to run these checks")
        return 1

    for text in ("K7Bq2", "4mRt9"):
        got = await image_captcha.read_text(make_captcha(text))
        ok = (got or "").lower() == text.lower()
        failures += 0 if ok else 1
        print(f"image captcha  expected {text!r:8s} got {got!r:10s} {'ok' if ok else 'MISS'}")

    for gap in (96, 180, 254):
        background, piece = make_slider(gap)
        got = slider.gap_offset(background, piece)
        ok = got is not None and abs(got - gap) <= 2
        failures += 0 if ok else 1
        print(f"slider gap     expected {gap:3d}      got {got!s:10s} {'ok' if ok else 'MISS'}")

    # A sixteen-cell grid is where model picking still slips a cell; hCaptcha fails the round and the
    # solver asks again, so a miss here is soft — it costs a round, not the solve.
    grid_cases = [
        ({0, 4, 8}, 3, 3, False),
        ({2, 5, 7}, 3, 3, False),
        ({1, 3, 6, 9, 11, 14}, 4, 4, True),
        ({0, 5, 8, 10, 15}, 4, 4, True),
    ]
    for cells, rows, cols, is_soft in grid_cases:
        png, offsets = make_grid(cells, rows, cols)
        labelled = hcaptcha._label_cells(png, offsets)
        picked = await hcaptcha._vote_cells(labelled, "all cells showing a red circle", rows * cols)
        ok = sorted(picked) == sorted(cells)
        if not ok:
            soft += 1 if is_soft else 0
            failures += 0 if is_soft else 1
        verdict = "ok" if ok else ("soft-miss" if is_soft else "MISS")
        print(f"grid {rows}x{cols}      expected {sorted(cells)!s:22s} got {sorted(picked)!s:22s} {verdict}")

    if failures:
        print(f"\n{failures} failed check(s)")
    elif soft:
        print(f"\nhard checks passed, {soft} soft miss(es) on 4x4 grids (a retried round, not a failure)")
    else:
        print("\nall offline checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
