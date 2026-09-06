#!/usr/bin/env python3
"""Render a rule file as a Claude Code output style.

    bin/mkstyle.py <rule.md> <out-dir>   -> prints the style name

The rule's frontmatter is passed through verbatim except for this repo's
bookkeeping keys, so anything Claude Code understands (description,
keep-coding-instructions, ...) survives intact. The style is named after the
rule's own `name`, and that name is what settings.json must reference.
"""
import re
import sys
from pathlib import Path

BOOKKEEPING = {"id", "owns", "probes", "guards"}


def split_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        sys.exit("rule file needs YAML frontmatter")
    return m.group(1), m.group(2)


def main(rule_path, out_dir):
    fm, body = split_frontmatter(Path(rule_path).read_text())

    kept, name = [], None
    current_key = None
    for line in fm.split("\n"):
        key = re.match(r"^([A-Za-z0-9_-]+):", line)
        if key:
            current_key = key.group(1)
            if current_key == "name":
                name = line.split(":", 1)[1].strip()
        # Continuation lines (list items, wrapped values) inherit the last key.
        if current_key in BOOKKEEPING:
            continue
        kept.append(line)

    if not name:
        sys.exit(f"{rule_path}: frontmatter needs a 'name' for the output style")

    out = Path(out_dir) / f"{name}.md"
    out.write_text("---\n" + "\n".join(kept).strip("\n") + "\n---\n" + body)
    print(name)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
