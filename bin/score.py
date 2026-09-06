#!/usr/bin/env python3
"""Score captured samples for wall-of-text structure.

    bin/score.py samples/storage-choice/control [more/dirs ...]
    bin/score.py --check style/rules/001-land-the-answer.md

Writes scores.json into each directory and prints a table. Given more than one
directory, prints deltas against the first (the baseline).

--check reads a rule's frontmatter and verifies the two claims it makes: that the
metrics it *owns* improved on the probes it targets, and that its guard probes
did not move. A rule that shortens an explanation probe is over-firing.

Every metric is deterministic and structural. Lexical "Claude-ism" patterns were
tried and discarded: across the first three control samples they fired 1/0/4 and
0/0/1, because the recurring beats are stable in meaning but not in wording.
"""
import json
import re
import statistics
import sys
from pathlib import Path

TAIL_QUESTION = 0.15   # final fraction of words searched for a trailing question
TAIL_RESTATE = 0.20    # final fraction searched for a restated verdict


def load_probe(probe_id):
    """Return the probe's verdict tokens, or [] if it has none."""
    path = Path(__file__).resolve().parent.parent / "prompts" / f"{probe_id}.md"
    if not path.exists():
        return []
    m = re.search(r"^verdict_tokens:\s*\[(.*?)\]", path.read_text(), re.M)
    if not m or not m.group(1).strip():
        return []
    return [t.strip().strip('"\'') for t in m.group(1).split(",") if t.strip()]


def first_token_pct(text, words, tokens):
    """Word offset of the earliest verdict-token mention, as % of total.

    A proxy: it assumes the first mention of a candidate answer is the point
    where the response commits. That matched a hand read on all three of the
    first control samples, but it is a proxy, not a commitment detector.
    """
    best = None
    for tok in tokens:
        m = re.search(re.escape(tok), text, re.I)
        if m and (best is None or m.start() < best):
            best = m.start()
    if best is None:
        return None
    return round(100 * len(text[:best].split()) / max(len(words), 1), 1)


def score_file(path, tokens):
    text = path.read_text()
    words = text.split()
    n = len(words)
    tail_q = " ".join(words[int(n * (1 - TAIL_QUESTION)):])
    tail_r = " ".join(words[int(n * (1 - TAIL_RESTATE)):])
    verdict_pct = first_token_pct(text, words, tokens)

    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    prose = sum(1 for b in blocks
                if not re.match(r"^\s*([-*+]|\d+\.|\||#|```)", b))

    return {
        "file": path.name,
        "words": n,
        "first_verdict_pct": verdict_pct,
        "elaboration_ratio": None if verdict_pct is None else round(100 - verdict_pct, 1),
        "trailing_question": "?" in tail_q,
        "restates_verdict": bool(tokens) and any(
            re.search(re.escape(t), tail_r, re.I) for t in tokens
        ),
        "prose_paragraphs": prose,
        "bullets": len(re.findall(r"^\s*[-*+] ", text, re.M)),
        "sections": len(re.findall(r"^(?:#{1,4} |\*\*[^*\n]+\*\*)", text, re.M)),
        "code_fence_lines": len(re.findall(r"^```", text, re.M)) // 2,
        "em_dashes_per_100w": round(100 * text.count("—") / max(n, 1), 2),
    }


NUMERIC = ["words", "first_verdict_pct", "elaboration_ratio", "prose_paragraphs",
           "bullets", "sections", "code_fence_lines", "em_dashes_per_100w"]
BOOLEAN = ["trailing_question", "restates_verdict"]

# Metrics a rule is expected to drive down. first_verdict_pct is deliberately
# absent: landing the answer earlier is good, but so is a probe with no verdict.
LOWER_IS_BETTER = {"words", "elaboration_ratio", "prose_paragraphs", "sections",
                   "trailing_question", "restates_verdict"}

# A guard probe may drift this much before it counts as collateral damage.
GUARD_TOLERANCE = 0.15


def summarise(rows):
    out = {}
    for k in NUMERIC:
        vals = [r[k] for r in rows if r[k] is not None]
        out[k] = {
            "mean": round(statistics.mean(vals), 1),
            "min": min(vals),
            "max": max(vals),
        } if vals else None
    for k in BOOLEAN:
        hits = sum(1 for r in rows if r[k])
        out[k] = {"hits": hits, "of": len(rows), "rate": round(hits / len(rows), 2)}
    return out


def score_dir(d):
    d = Path(d)
    probe_id = d.parent.name
    tokens = load_probe(probe_id)
    files = sorted(f for f in d.glob("r*.md"))
    if not files:
        sys.exit(f"no samples in {d}")
    rows = [score_file(f, tokens) for f in files]
    result = {
        "probe": probe_id,
        "condition": d.name,
        "verdict_tokens": tokens,
        "n": len(rows),
        "summary": summarise(rows),
        "samples": rows,
    }
    (d / "scores.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def fmt(v):
    return "  n/a" if v is None else f"{v:>5}"


def main(dirs):
    results = [score_dir(d) for d in dirs]
    base = results[0]
    for r in results:
        print(f"\n{r['probe']} / {r['condition']}  (n={r['n']})")
        for k in NUMERIC:
            s, b = r["summary"][k], base["summary"][k]
            if s is None:
                print(f"  {k:<22} n/a")
                continue
            line = f"  {k:<22} mean {fmt(s['mean'])}   [{s['min']}–{s['max']}]"
            if r is not base and b:
                d = s["mean"] - b["mean"]
                pct = f"  ({d:+.1f}, {100 * d / b['mean']:+.0f}%)" if b["mean"] else ""
                line += pct
            print(line)
        for k in BOOLEAN:
            s = r["summary"][k]
            line = f"  {k:<22} {s['hits']}/{s['of']}"
            if r is not base:
                line += f"  (base {base['summary'][k]['hits']}/{base['summary'][k]['of']})"
            print(line)
    print()




# --- rule ownership checks -------------------------------------------------

def rule_meta(path):
    """Parse the bookkeeping frontmatter of a rule file."""
    text = Path(path).read_text()
    meta = {}
    for key in ("id", "name"):
        m = re.search(rf"^{key}:\s*(.+)$", text, re.M)
        if m:
            meta[key] = m.group(1).strip()
    for key in ("owns", "probes", "guards"):
        m = re.search(rf"^{key}:\s*\[(.*?)\]", text, re.M)
        meta[key] = ([t.strip().strip('"\'') for t in m.group(1).split(",") if t.strip()]
                     if m else [])
    if "id" not in meta:
        sys.exit(f"{path}: frontmatter needs an 'id'")
    return meta


def metric_mean(result, key):
    s = result["summary"][key]
    if s is None:
        return None
    return s["rate"] if "rate" in s else s["mean"]


def check_rule(rule_path):
    root = Path(__file__).resolve().parent.parent
    meta = rule_meta(rule_path)
    rid = meta["id"]
    print(f"\nrule {rid} ({meta.get('name', '?')})")
    print(f"  owns:   {', '.join(meta['owns']) or '(nothing)'}")
    print(f"  probes: {', '.join(meta['probes']) or '(none)'}")
    print(f"  guards: {', '.join(meta['guards']) or '(none)'}")

    failures = []

    for probe in meta["probes"]:
        base_d, rule_d = root / "samples" / probe / "control", root / "samples" / probe / rid
        if not rule_d.exists():
            failures.append(f"{probe}: no samples for condition '{rid}' — capture it first")
            continue
        base, ruled = score_dir(base_d), score_dir(rule_d)
        print(f"\n  {probe}")
        for k in meta["owns"]:
            b, r = metric_mean(base, k), metric_mean(ruled, k)
            if b is None or r is None:
                print(f"    {k:<22} n/a")
                continue
            delta = r - b
            better = delta < 0 if k in LOWER_IS_BETTER else delta > 0
            pct = f"{100 * delta / b:+.0f}%" if b else "n/a"
            print(f"    {k:<22} {b:>7.2f} -> {r:>7.2f}  ({pct})  "
                  f"{'ok' if better else 'NO MOVEMENT'}")
            if not better:
                failures.append(f"{probe}: owned metric '{k}' did not improve ({pct})")

    for probe in meta["guards"]:
        base_d, rule_d = root / "samples" / probe / "control", root / "samples" / probe / rid
        if not rule_d.exists():
            failures.append(f"{probe}: no guard samples for condition '{rid}'")
            continue
        base, ruled = score_dir(base_d), score_dir(rule_d)
        print(f"\n  {probe} (guard)")
        for k in ("words", "sections"):
            b, r = metric_mean(base, k), metric_mean(ruled, k)
            if not b:
                continue
            drift = abs(r - b) / b
            print(f"    {k:<22} {b:>7.2f} -> {r:>7.2f}  ({100 * (r - b) / b:+.0f}%)  "
                  f"{'ok' if drift <= GUARD_TOLERANCE else 'COLLATERAL'}")
            if drift > GUARD_TOLERANCE:
                failures.append(
                    f"{probe}: guard metric '{k}' moved {100 * (r - b) / b:+.0f}% "
                    f"(tolerance {int(GUARD_TOLERANCE * 100)}%)")

    print()
    if failures:
        print("FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS  rule moved what it owns and left its guards alone")
    return 0

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "--check":
        if len(args) != 2:
            sys.exit("usage: score.py --check <rule.md>")
        sys.exit(check_rule(args[1]))
    main(args)
