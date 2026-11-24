#!/usr/bin/env python3
"""Install the challenge solvers into a Skyvern checkout.

Two steps, both idempotent: copy ``challenge_kit`` next to Skyvern's webeye utils, and apply the
patch that adds the ladder seam calls (plus the human gestures they use). Nothing is fetched and
nothing outside the target checkout is touched, so ``--dry-run`` is a safe way to see the plan.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PATCH = Path("patches") / "0001-skyvern-solver-seams.patch"
KIT = Path("challenge_kit")
KIT_TARGET = Path("skyvern/webeye/utils/challenge_kit")


def _run(command: list[str], cwd: Path, *, dry_run: bool) -> int:
    print("$", " ".join(command), f"(in {cwd})")
    if dry_run:
        return 0
    return subprocess.run(command, cwd=cwd).returncode


def _apply_patch(target: Path, *, dry_run: bool) -> bool:
    patch_file = PATCH.resolve()
    if not patch_file.is_file():
        print(f"missing {patch_file}")
        return False
    check = subprocess.run(
        ["git", "apply", "--check", "-p1", str(patch_file)], cwd=target, capture_output=True, text=True
    )
    if check.returncode != 0:
        # A checkout that already carries the patch reports every hunk as taken; anything else is real.
        if "already" in check.stderr or "does not exist" in check.stderr:
            print("patch does not apply cleanly:", check.stderr.strip()[:400])
        else:
            print("patch does not apply:", check.stderr.strip()[:400])
        return False
    return _run(["git", "apply", "-p1", str(patch_file)], target, dry_run=dry_run) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Install local captcha solvers into Skyvern.")
    parser.add_argument("--skyvern", default=".", help="path to the Skyvern checkout (default: cwd)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan without writing")
    parser.add_argument("--skip-patch", action="store_true", help="copy the kit only")
    args = parser.parse_args()

    target = Path(args.skyvern).resolve()
    if not (target / "skyvern" / "forge" / "agent.py").is_file():
        print(f"{target} does not look like a Skyvern checkout")
        return 2

    destination = target / KIT_TARGET
    print(f"copy {KIT.resolve()} -> {destination}")
    if not args.dry_run:
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(KIT, destination, ignore=shutil.ignore_patterns("__pycache__"))

    if not args.skip_patch and not _apply_patch(target, dry_run=args.dry_run):
        print("the kit was copied but the seam patch did not apply; the solvers will be unused")
        return 1

    print(
        "\ndone. configure a vision backend in the Skyvern .env, then restart the server:\n"
        "  CHALLENGE_VISION_API_KEY=<key>\n"
        "  CHALLENGE_VISION_API_BASE=https://api.mistral.ai/v1   # any OpenAI-compatible endpoint\n"
        "  CHALLENGE_VISION_MODEL=mistral-small-latest\n"
        "  CHALLENGE_OCR_MODEL=mistral-ocr-latest\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
