# What this repository is

Skyvern **1.0.58**, complete source, based on upstream commit `7cc074c`, plus one local addition:
the captcha and bot-protection arms that the open build leaves to a person are solved here instead
of waited out.

Everything else — CLI, server, workflows, agent, browser factory, the frontend — is upstream code.
This is not a fork on GitHub; it is a standalone copy. The base clone was shallow, so the history
here is a single root commit holding the whole tree: the changes are described below and in
`local/challenge-kit/`, which also carries the patch, installer and tests.

Upstream: [Skyvern-AI/skyvern](https://github.com/Skyvern-AI/skyvern). Licence: AGPL-3.0 (`LICENSE`,
unchanged).

## The local commits

| Commit | Change |
|---|---|
| `f9eda66` | clear a rendered Cloudflare/Turnstile interstitial with a human gesture before a step plans |
| `46d84e1` | local solvers behind every captcha seam (`challenge_kit`) |
| `a25f6d3` | kit sync |

Diff against upstream:

```bash
git diff 7cc074c..HEAD --stat
```

## Files that differ from upstream

| File | Change |
|---|---|
| `skyvern/webeye/utils/human_input.py` | **new** — stealth init script, Bezier move, click, press-and-hold, drag |
| `skyvern/webeye/utils/challenge_kit/` | **new** — vision, image captcha, hCaptcha, slider, reCAPTCHA token, vendor handlers |
| `skyvern/forge/agent_functions.py` | the seven captcha seams now call the kit instead of returning "no" |
| `skyvern/forge/agent.py` | detect and clear an interstitial before each step, then let the page settle |
| `skyvern/webeye/actions/handler.py` | solve before falling back to the 30-second human wait |
| `skyvern/webeye/utils/captcha_solver.py` | click widgets with a real gesture, not `element.click` |
| `skyvern/webeye/browser_factory.py` | install the stealth init script on the CDP context |

## Run it

```bash
uv pip install "skyvern[server]"      # or: pip install "skyvern[server]"
skyvern run server                    # API on :8000, UI: skyvern run ui
```

Solvers need a vision backend in `.env` (not committed):

```bash
CHALLENGE_VISION_API_KEY=<key>
CHALLENGE_VISION_API_BASE=https://api.mistral.ai/v1   # any OpenAI-compatible endpoint
CHALLENGE_VISION_MODEL=mistral-small-latest
CHALLENGE_OCR_MODEL=mistral-ocr-latest
```

With no key the seams report unavailable and the build behaves as shipped upstream.

## What the solvers cover

| Challenge | Coverage |
|---|---|
| Cloudflare / Turnstile checkbox | full: out-of-process widget found by its box, click follows a human path, ~2s |
| reCAPTCHA v2 checkbox | upstream anchor click, now with a real gesture |
| reCAPTCHA v3 / invisible | full: token minted with the page's own key and written into the response field |
| image/text captcha | full: vision read, second read settling the length, document OCR fallback |
| hCaptcha checkbox | full: human click |
| hCaptcha area-select | best effort: cell numbers drawn on the screenshot, two readings must agree per cell, three rounds; a 16-cell grid is occasionally one cell off and costs a retried round |
| Geetest / slider | best effort: gap measured from the two canvases, eased drag with overshoot; other slider layouts fall back to edge alignment |
| DataDome / PerimeterX / BotShield | detect + the gesture the page asks for (PerimeterX press-and-hold twitches), then let the ladder re-probe |
| AWS WAF | wait out the proof-of-work, reload once; no gesture exists to fake |
| Akamai, Geetest v4 word-order, hCaptcha image-in-image | not covered |

Pointer work goes through `human_input` because these widgets score the gesture: a jump-to-target
click on an automated browser is refused with the coordinates still right.

## Evidence

Measured on this checkout, cold Chrome profile, datacenter IP (`83.97.112.25`), DeepSeek V4.1 Flash
as the planner:

- Cloudflare interstitial cleared in ~2s with `cf_clearance` set; task completes in one step, ~33s
  end to end (2 screenshots per LLM call instead of 5).
- reCAPTCHA v3: token of 2574 characters minted and written to `g-recaptcha-response`.
- Image captcha: `K7Bq2` and `4mRt9` read exactly; slider gaps 96/180/254 found exactly.
- hCaptcha grid: 3x3 exact, 4x4 exact after per-cell voting.
- Vendor detection exact on DataDome, PerimeterX and BotShield block pages; a clean page is not flagged.

## A smaller option

If you only want the solvers and not the whole tree, the same code ships as a patch set:
[skyvern-challenge-kit](https://github.com/tringuyen1032/skyvern-challenge-kit).
