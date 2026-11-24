"""Browser checks against a Chrome already listening on CDP.

These exercise the parts an offline test cannot: minting a real reCAPTCHA token, reading vendor
block pages, and seeing an hCaptcha widget. Start Chrome first, then:

    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
        --remote-debugging-port=9222 --user-data-dir=$HOME/.skyvern-chrome-profile
    python tests/test_browser.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from challenge_kit import hcaptcha, recaptcha_token, vendor  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

CDP = "http://127.0.0.1:9222"

SAMPLE_BLOCK_PAGES = {
    "datadome": '<html><body><iframe src="https://geo.captcha-delivery.com/captcha/"></iframe>datadome</body></html>',
    "perimeterx": '<html><body><div id="px-captcha">Press &amp; Hold</div></body></html>',
    "botshield": "<html><body>checking your browser botshield</body></html>",
}


async def main() -> int:
    failures = 0
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.connect_over_cdp(CDP)
        except Exception as exc:
            print(f"no Chrome on {CDP}: {exc}")
            return 1
        context = browser.contexts[0]

        page = await context.new_page()
        try:
            await page.goto(
                "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            await page.wait_for_timeout(2500)
            present = await recaptcha_token.present(page)
            solved = await recaptcha_token.solve(page)
            length = await page.evaluate(
                "() => { const f = document.querySelector('textarea[name=\"g-recaptcha-response\"],"
                " #g-recaptcha-response'); return f ? f.value.length : 0; }"
            )
            ok = bool(present and solved and length > 100)
            failures += 0 if ok else 1
            print(f"reCAPTCHA v3   present={present} solved={solved} token_chars={length} {'ok' if ok else 'MISS'}")
        finally:
            await page.close()

        page = await context.new_page()
        try:
            await page.goto("https://accounts.hcaptcha.com/demo", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(4000)
            present = await hcaptcha.present(page)
            clicked = await hcaptcha._click_checkbox(page)
            failures += 0 if present else 1
            print(f"hCaptcha       present={present} checkbox_click={clicked} {'ok' if present else 'MISS'}")
        finally:
            await page.close()

        page = await context.new_page()
        try:
            for name, html in SAMPLE_BLOCK_PAGES.items():
                await page.set_content(html)
                detected = await vendor.detect(page)
                ok = detected is not None and detected.value == name
                failures += 0 if ok else 1
                print(f"vendor {name:11s} detected={(detected.value if detected else None)!s:12s} {'ok' if ok else 'MISS'}")
            await page.set_content("<html><body><h1>hello</h1></body></html>")
            clean = await vendor.detect(page)
            failures += 0 if clean is None else 1
            print(f"vendor clean       detected={clean!s:12s} {'ok' if clean is None else 'MISS'}")
        finally:
            await page.close()

    print(f"\n{failures} failed check(s)" if failures else "\nall browser checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
