# skyvern-challenge-kit

Local solvers for the bot-protection arms that Skyvern's OSS build leaves to a human.

Skyvern's captcha ladder detects a challenge and then asks `AGENT_FUNCTION` to solve it. In the open
build every one of those answers is "no", so anything harder than a visible DOM checkbox ends in a
30-second wait for a person. This kit answers those seams: image captchas are read with a vision
model, hCaptcha escalation is picked cell by cell, sliders are measured and dragged, reCAPTCHA tokens
are minted from the page's own key, and vendor block pages get the one gesture they ask for.

Nothing here is required by Skyvern. Install it, restart, and the same runs clear the challenges they
used to wait on; skip it and the build behaves exactly as shipped.

## Install

```bash
git clone https://github.com/<you>/skyvern-challenge-kit
cd skyvern-challenge-kit

# point at your Skyvern checkout; the kit is copied in and one patch is applied
python install.py --skyvern /path/to/skyvern --dry-run   # see the plan
python install.py --skyvern /path/to/skyvern
```

Then give the solvers a vision backend in Skyvern's `.env` and restart the server:

```bash
CHALLENGE_VISION_API_KEY=<key>
CHALLENGE_VISION_API_BASE=https://api.mistral.ai/v1   # any OpenAI-compatible endpoint
CHALLENGE_VISION_MODEL=mistral-small-latest
CHALLENGE_OCR_MODEL=mistral-ocr-latest
CHALLENGE_VISION_TIMEOUT=60
```

With no key set, `captcha_solving_available()` reports false and Skyvern's behaviour is unchanged.

## What gets installed

| File | Change |
|---|---|
| `skyvern/webeye/utils/challenge_kit/` | the solvers, copied in as a package |
| `skyvern/webeye/utils/human_input.py` | human gestures: Bezier move, click, press-and-hold, drag |
| `skyvern/webeye/actions/handler.py` | solve the visible challenge before the 30s human wait |
| `skyvern/webeye/utils/captcha_solver.py` | click widgets with a real gesture, not `element.click` |
| `skyvern/webeye/browser_factory.py` | install the stealth init script on the CDP context |
| `skyvern/forge/agent_functions.py` | wire the seven captcha seams to the kit |
| `skyvern/forge/agent.py` | clear an interstitial before a step plans, then let the page settle |

Those patched files are the only Skyvern source touched, and the patch is context-bound: if it does
not apply, nothing is half-written (`install.py` checks before writing).

## The solvers

| Module | Handles | How |
|---|---|---|
| `image_captcha` | text/image captcha | vision read, a second read settling the length, document OCR as fallback |
| `hcaptcha` | checkbox + area-select | human click, then the grid: cell numbers drawn onto the screenshot, two readings must agree per cell, a third breaks a split |
| `slider` | Geetest and generic sliders | gap = the column run darker than its surroundings, else edge alignment through the piece's alpha mask; then an eased drag that overshoots and corrects |
| `recaptcha_token` | reCAPTCHA v3 / invisible | `grecaptcha.execute` with the page's own key, token written into the response field |
| `vendor` | DataDome, PerimeterX, BotShield | detect from page and cookies, run the gesture asked for (the PerimeterX hold twitches), let the ladder re-probe |
| `vendor.handle_aws_waf` | AWS WAF | waits out the proof-of-work, reloads once with the minted token |

Pointer work goes through `human_input` rather than element clicks because these widgets score the
gesture: a jump-to-target click on an obviously automated browser is refused with the coordinates
still correct.

## Verified

`tests/test_offline.py` — no browser, one vision key:

```
image captcha  expected 'K7Bq2'  got 'K7Bq2'    ok
image captcha  expected '4mRt9'  got '4mRt9'    ok
slider gap     expected  96      got 96         ok
slider gap     expected 180      got 180        ok
slider gap     expected 254      got 254        ok
grid 3x3       expected [0, 4, 8]              got [0, 4, 8]              ok
grid 3x3       expected [2, 5, 7]              got [2, 5, 7]              ok
grid 4x4       expected [1, 3, 6, 9, 11, 14]   got [1, 3, 6, 9, 11, 14]   ok
grid 4x4       expected [0, 5, 8, 10, 15]      got [0, 5, 8, 10, 15]      ok
```

`tests/test_browser.py` — against Chrome on CDP, real pages:

```
reCAPTCHA v3   present=True solved=True token_chars=2574 ok
hCaptcha       present=True checkbox_click=True ok
vendor datadome    detected=datadome     ok
vendor perimeterx  detected=perimeterx   ok
vendor botshield   detected=botshield    ok
vendor clean       detected=None         ok
```

End to end through Skyvern: a cold Chrome profile on a Cloudflare-protected page clears the
interstitial in ~2s with `cf_clearance` set and the task completes in one step (~33s, DeepSeek V4.1
Flash, 2 screenshots per LLM call).

## Limits, stated plainly

- Grid picking on a 16-cell hCaptcha is occasionally one cell off. hCaptcha fails that round and the
  solver asks again (three rounds), so it costs time rather than the solve. 3x3 is reliable.
- Image captchas that are heavily distorted or low contrast can read wrong; the read is voted twice
  and never submitted blind, but a wrong read is still a wrong read.
- AWS WAF has no solver: it is a JS proof-of-work, so the kit waits and reloads once.
- PerimeterX/DataDome often pass on fingerprint alone; the handler is the gesture plus patience, not
  a bypass. A site that demands phone verification still needs a person.
- The slider gap finder is tuned for the two-canvas layout Geetest ships. Other sliders fall back to
  edge alignment and may need a second attempt.

## Tests

```bash
export CHALLENGE_VISION_API_KEY=...
python tests/test_offline.py            # no browser

# browser checks need Chrome on CDP
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 --user-data-dir=$HOME/.skyvern-chrome-profile &
python tests/test_browser.py
```

## License

AGPL-3.0. The patch modifies Skyvern, which is AGPL-3.0, so the combined work carries the same terms.
The kit itself is likewise AGPL-3.0 to keep the two compatible.
