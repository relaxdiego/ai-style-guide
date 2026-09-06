#!/usr/bin/env python3
"""Compose the release notes for a tagged guide, provenance included.

The tag message for 1.0 recorded the style sha and the shipping rule ids by
hand. This generates the same facts instead, so a release cannot claim a
provenance it does not have.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "harness"))

import package_style as ps  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    guide_path, notes_path = Path(sys.argv[1]), Path(sys.argv[2])
    rules_path = REPO / "style" / "rules.md"

    # Rebuild in process and compare. The workflow already ran the packager;
    # if these two disagree the release would ship an unattributed document.
    guide, ids = ps.build(rules_path)
    on_disk = guide_path.read_text(encoding="utf-8")
    if guide != on_disk:
        sys.exit("built guide differs from the one package_style.py wrote")

    slug = os.environ.get("GITHUB_REPOSITORY", "relaxdiego/ai-style-guide")
    tag = os.environ.get("GITHUB_REF_NAME", "HEAD")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
        text=True, check=True).stdout.strip()

    url = f"https://github.com/{slug}/releases/download/{tag}/CLAUDE.md"
    notes = f"""The prose style guide, built from `style/rules.md` at this tag.

## Installing it

    curl -LO {url}
    mkdir -p ~/.claude
    cp CLAUDE.md ~/.claude/CLAUDE.md

If you already have a `CLAUDE.md` there, append to it instead of overwriting, or
the rest of your instructions go with it. The README has the details, including
how to scope the guide to a single repository.

## Provenance

| | |
|---|---|
| source commit | `{commit}` |
| `style/rules.md` | `sha256:{sha256(rules_path)}` |
| `CLAUDE.md` | `sha256:{sha256(guide_path)}` |
| rules, in file order | {", ".join(ids)} |
| length | {len(guide.split())} words |

The packager reads the rule text verbatim, so the source commit above is the
whole provenance of this wording. Verify a download with `sha256sum CLAUDE.md`.
"""
    notes_path.write_text(notes, encoding="utf-8")
    print(f"{notes_path}  {len(ids)} rules  commit {commit[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
