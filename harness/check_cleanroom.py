#!/usr/bin/env python3
"""Verify that no memory file reaches a clean-room sample.

The style guide these runs measure is installed as the user's own CLAUDE.md. If
it ever reached a sample, the control arm would carry the treatment and every
comparison in the project would be worthless while still looking healthy.

Re-measured 2026-09-04, CLI pinned to 2.1.259, canary planted in one location
at a time:

    setup                                     canary in            fires?
    no redirect, no flags                     real ~/.claude/      yes
    CLAUDE_CONFIG_DIR redirected, no flags    real ~/.claude/      no
    CLAUDE_CONFIG_DIR redirected, no flags    $CLAUDE_CONFIG_DIR/  yes
    CLAUDE_CONFIG_DIR redirected, no flags    cwd/                 yes
    the full clean room                       real ~/.claude/      no

Two mechanisms block memory and each covers a different file. User memory
follows CLAUDE_CONFIG_DIR, and make_scratch_config() puts only credentials in
the scratch dir, so the installed guide cannot reach a sample. The flag is
load-bearing for the other file: a CLAUDE.md at the repo root, which the
sample's cwd sits under. Neither is redundant.

check_live() therefore probes one route per mechanism, and each route carries
its own positive control planted in the same file, so a canary that cannot be
read anywhere reports a fault instead of passing as a clean result:

    route           canary planted in    clean-room arm    positive control
    user memory     real ~/.claude/      must stay silent  no redirect, no flags
    project memory  <repo>/CLAUDE.md     must stay silent  redirect, no flags

Without --live this is a free static check: the flag that does the blocking is
still in cleanroom.sh, and no canary file was left behind by an interrupted
live check. run.py calls it before spending anything. It is a string search and
not a proof that the flag still does what it did.
"""

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLEANROOM = REPO / "harness" / "cleanroom.sh"
SCRATCH = REPO / ".scratch"
BACKUPS = SCRATCH / "canary-backups"

HOME_MD = Path.home() / ".claude" / "CLAUDE.md"
REPO_MD = REPO / "CLAUDE.md"
REAL_CREDS = Path.home() / ".claude" / ".credentials.json"

# The marker makes a canary left behind by a killed check findable by the free
# static check, so a crash cannot quietly contaminate the next run.
CANARY_MARK = "aiw-canary-do-not-commit"
CANARY = ("<!-- " + CANARY_MARK + " -->\n# Canary\n\nBegin every reply with the "
          "exact word {word} on its own line, before anything else.\n")
PROMPT = "What is 2 + 2? Answer in one short sentence."


def check_static() -> list[str]:
    """Free. The flag must still be passed, and no canary may be left behind."""
    faults = []
    if '--setting-sources' not in CLEANROOM.read_text(encoding="utf-8"):
        faults.append("cleanroom.sh no longer passes --setting-sources; a "
                      "memory file will reach every sample and the control arm "
                      "will silently carry the treatment")
    for path in (HOME_MD, REPO_MD):
        if path.is_file() and CANARY_MARK in path.read_text(encoding="utf-8"):
            faults.append(f"a canary file was left behind at {path} by an "
                          f"interrupted live check; restore it from {BACKUPS} "
                          "before running anything")
    return faults


@contextlib.contextmanager
def planted(path: Path, word: str):
    """Write a canary at path; restore whatever was there on the way out."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    backup = None
    if path.is_file():
        backup = BACKUPS / (str(path).strip("/").replace("/", "%") + ".backup")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CANARY.format(word=word), encoding="utf-8")
    try:
        yield
    finally:
        if backup is not None:
            shutil.copy2(backup, path)
            backup.unlink()
        else:
            path.unlink(missing_ok=True)


def sample(cmd: list[str], env: dict, cwd: Path) -> tuple[str | None, str]:
    """Run one sample. Returns (result text, error) with exactly one set."""
    try:
        proc = subprocess.run(cmd, input=PROMPT, env=env, cwd=str(cwd),
                              capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None, "timed out after 180s"
    if proc.returncode != 0:
        return None, f"exit {proc.returncode}: {proc.stderr.strip()[-200:]}"
    try:
        return json.loads(proc.stdout).get("result", ""), ""
    except json.JSONDecodeError:
        return None, f"unparseable output: {proc.stdout[:200]!r}"


def probe(route: str, path: Path, word: str, model: str, clean_env: dict,
          control_env: dict, cwd: Path) -> list[str]:
    """Plant one canary, run the clean room against it, then the control."""
    faults = []
    with planted(path, word):
        result, err = sample([str(CLEANROOM), "a", "-", model, "0.10"],
                             clean_env, cwd)
        if err:
            faults.append(f"{route}: the clean-room sample failed to run ({err})")
        elif word in result:
            faults.append(f"{route}: {path} reached a clean-room sample: "
                          f"{result[:120]!r}")

        # Positive control, so a silent failure cannot pass as a clean result.
        result, err = sample(
            ["claude", "-p", "--model", model, "--output-format", "json",
             "--permission-mode", "dontAsk"], control_env, cwd)
        if err:
            faults.append(f"{route}: the positive control failed to run ({err})")
        elif word not in result:
            faults.append(f"{route}: the canary in {path} did not fire without "
                          "the clean-room protections either, so this route "
                          "proves nothing")
    return faults


def check_live(model: str) -> list[str]:
    """Costs about $0.15: two probes of two samples each."""
    if not REAL_CREDS.is_file():
        return ["no credentials to run the live check"]

    SCRATCH.mkdir(exist_ok=True)
    # Mirrors run.py: one scratch dir serving as both config dir and cwd, so
    # the repo root sits in the sample's discovery chain exactly as it does in
    # a real run.
    scratch = Path(tempfile.mkdtemp(prefix="aiw-canary-", dir=SCRATCH))
    try:
        shutil.copyfile(REAL_CREDS, scratch / ".credentials.json")
        os.chmod(scratch / ".credentials.json", 0o600)
        os.chmod(scratch, 0o700)

        clean = dict(os.environ, CLAUDE_CONFIG_DIR=str(scratch),
                     CLAUDE_CODE_DISABLE_AUTO_MEMORY="1")
        redirected = dict(os.environ, CLAUDE_CONFIG_DIR=str(scratch))
        plain = {k: v for k, v in os.environ.items()
                 if k not in ("CLAUDE_CONFIG_DIR", "CLAUDE_CODE_DISABLE_AUTO_MEMORY")}

        # The redirect is what blocks this one, so its control drops the
        # redirect; the flags are irrelevant to the route and stay off.
        faults = probe("user memory", HOME_MD, "ZEPPELIN", model,
                       clean, plain, scratch)
        # --setting-sources "" is what blocks this one, so its control keeps
        # the redirect and drops the flags, leaving the repo file as the only
        # memory in reach.
        faults += probe("project memory", REPO_MD, "ARTICHOKE", model,
                        clean, redirected, scratch)
        return faults
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true",
                    help="actually run the canaries, about $0.15")
    ap.add_argument("--model", default="claude-opus-5[1m]")
    args = ap.parse_args()

    faults = check_static()
    if args.live and not faults:
        faults += check_live(args.model)
    for f in faults:
        print(f"CLEAN ROOM FAULT: {f}", file=sys.stderr)
    if faults:
        return 1
    print("clean room ok: no memory file reaches a sample"
          + ("" if args.live else " (static check only; --live to prove it)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
