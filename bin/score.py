#!/usr/bin/env python3
"""Score captured samples for wall-of-text structure.

    bin/score.py samples/storage-choice/control [more/dirs ...]
    bin/score.py --check styles/no-slop-2026.09.06

Writes scores.json into each directory and prints a table. Given more than one
directory, prints deltas against the first (the baseline).

--check reads a style's claims.yaml and verifies the two claims it makes: that
the metrics it *owns* moved the right way on the probes it targets, by more
than a permutation test is willing to call noise, and that its guard probes
held. What a guard holds is substance where the probe declares coverage
markers and length where it does not: a style that compresses an explanation
without dropping any of it is not over-firing, so on a probe with coverage
markers `words` is reported rather than enforced. `ceilings:` caps a metric
absolutely, for the case where a relative guard has no baseline to work from.

Owned metrics are graded at p < PERM_ALPHA on a two-sided permutation test of
the difference of means. With roughly ten rows in a report that leaves an
unaddressed multiple-comparison problem: one row in twenty clearing 0.05 by
chance is what 0.05 means, and nothing here corrects for it.

The arm it compares against is `control` unless claims.yaml names another with
`baseline:`. A style that revises an earlier one sets it to that earlier one:
where control already sits at zero on a metric, "better than control" is not a
question with an answer, and "better than the version being replaced" is.

The verdict is written back into the style directory as results.md and
results.json, so a style ships with its own measured record. Those files are
rewritten only when the numbers change, so their `checked` date is the date the
result last moved rather than the date --check last ran.

Samples record the sha256 of the style.md they were captured under. Editing a
style invalidates its samples, and --check fails rather than reporting stale
numbers against the edited text.

Every metric is deterministic and structural. Lexical "Claude-ism" patterns were
tried and discarded: across the first three control samples they fired 1/0/4 and
0/0/1, because the recurring beats are stable in meaning but not in wording.
"""
import hashlib
import itertools
import json
import math
import random
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

# A heading is a `#` line, or a bold span alone on its line. Both are counted
# by `sections` and both are excluded from `prose_paragraphs`; a bold span
# with prose after it on the same line is a lead-in, not a heading.
HEADING = re.compile(r"^(?:#{1,4} |\*\*[^*\n]+\*\*[ \t]*$)", re.M)

TAIL_QUESTION = 0.15   # final fraction of words searched for a trailing question
TAIL_RESTATE = 0.20    # final fraction searched for a restated verdict


def _list_key(text, key):
    """Parse a possibly multi-line inline YAML list from frontmatter.

    Scanned rather than matched to the first `]` and split on commas: coverage
    markers are regexes, so an item may legitimately contain either character
    inside its quotes, and splitting cut `["a,b", "c[x]d"]` into three wrong
    items. Quoted items keep their contents verbatim, single or double; a bare
    item runs to the next comma and is stripped, which is what the unquoted
    entries in `owns:`, `probes:` and `verdict_tokens:` rely on.
    """
    m = re.search(rf"^{key}:\s*\[", text, re.M)
    if not m:
        return []
    segs, items = [], []       # segs: [text, was_quoted] runs of the item so far

    def add(s, quoted):
        # Unquoted runs accumulate, so the whitespace *between* items can be
        # stripped without also stripping the space inside "worth noting".
        if not quoted and segs and not segs[-1][1]:
            segs[-1][0] += s
        else:
            segs.append([s, quoted])

    def flush():
        v = "".join(t if q else t.strip() for t, q in segs)
        if v or any(q for _, q in segs):
            items.append(v)
        segs.clear()

    i, n = m.end(), len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            j = text.find(ch, i + 1)
            j = n if j < 0 else j
            add(text[i + 1:j], True)
            i = j + 1
        elif ch == ",":
            flush()
            i += 1
        elif ch == "]":
            flush()
            return items
        else:
            add(ch, False)
            i += 1
    flush()                        # unterminated list: report what was there
    return items


def load_probe(probe_id):
    """Return (verdict tokens, coverage markers) for a probe."""
    path = Path(__file__).resolve().parent.parent / "prompts" / f"{probe_id}.md"
    if not path.exists():
        return [], []
    text = path.read_text()
    return _list_key(text, "verdict_tokens"), _list_key(text, "coverage")


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


def strip_fences(text):
    """Drop fenced code blocks, fences and contents alike.

    Prose structure is a property of the prose. A `# comment` inside a bash
    block is not a heading, and a blank line inside a block does not start a
    new paragraph, but both read that way to a line-anchored regex: in the
    ci-permission-denied samples, 2 of 2 "sections" were bash comments. An
    unterminated fence swallows the rest of the file, which is the same thing
    a Markdown renderer does with it.
    """
    out, inside = [], False
    for line in text.splitlines():
        if re.match(r"^\s*```", line):
            inside = not inside
        elif not inside:
            out.append(line)
    return "\n".join(out)


def score_file(path, tokens, coverage=()):
    text = path.read_text()
    words = text.split()
    n = len(words)
    tail_q = " ".join(words[int(n * (1 - TAIL_QUESTION)):])
    tail_r = " ".join(words[int(n * (1 - TAIL_RESTATE)):])
    verdict_pct = first_token_pct(text, words, tokens)

    # Structure is counted over the prose only. Fenced code is measured by
    # code_blocks and must not also register as headings or paragraphs.
    proseonly = strip_fences(text)

    blocks = [b for b in re.split(r"\n\s*\n", proseonly.strip()) if b.strip()]
    # `[-*+] ` needs the space: without it the `*` also matched the opening
    # star of a `**Bold lead-in.**`, and every paragraph that opens with one
    # was dropped from the prose count (53 of them across the samples).
    # HEADING then removes the other half of that distinction: a bold span
    # alone on its line is a heading, counted by `sections`, and must not also
    # count as a paragraph any more than a `#` heading does. A bold lead-in
    # followed by prose on the same line stays prose. (21 blocks across the
    # samples, all of them in styled arms, none in control.)
    prose = sum(1 for b in blocks
                if not re.match(r"^\s*([-*+] |\d+\.|\||#)", b)
                and not HEADING.match(b.strip()))

    cov = (round(100 * sum(bool(re.search(c, text, re.I)) for c in coverage)
                 / len(coverage), 1) if coverage else None)

    return {
        "file": path.name,
        "words": n,
        "first_verdict_pct": verdict_pct,
        "trailing_question": "?" in tail_q,
        "restates_verdict": bool(tokens) and any(
            re.search(re.escape(t), tail_r, re.I) for t in tokens
        ),
        "prose_paragraphs": prose,
        "bullets": len(re.findall(r"^\s*[-*+] ", text, re.M)),
        # The bold span has to be the whole line. A bold lead-in to a sentence
        # ("**It has no history.** Code you write carries...") is emphasis
        # inside a paragraph, not a section: 53 of those were counted as
        # headings across the samples.
        "sections": len(HEADING.findall(proseonly)),
        "code_blocks": len(re.findall(r"^```", text, re.M)) // 2,
        "em_dashes_per_100w": round(100 * text.count("—") / max(n, 1), 2),
        "coverage_pct": cov,
    }


NUMERIC = ["words", "first_verdict_pct", "prose_paragraphs", "bullets",
           "sections", "code_blocks", "em_dashes_per_100w", "coverage_pct"]
BOOLEAN = ["trailing_question", "restates_verdict"]

# Metrics a rule is expected to drive down. first_verdict_pct is deliberately
# absent: landing the answer earlier is good, but so is a probe with no verdict.
# bullets is the one entry here whose direction is not obvious. More structure
# is not worse in general, and no-slop-2026.09.06 raised it on tcp-congestion
# without being penalised, because it did not claim it. It sits here because
# every arm measured so far puts control at 2.1 to 3.8 bullets per response and
# no-slop-2026.09.07 at 3.3 to 8.3, so on these probes "fewer" and "closer to
# an unstyled response" are the same direction. A style that wants to claim
# more structure says so with `directions:` in its claims.yaml; see wants_lower.
LOWER_IS_BETTER = {"words", "prose_paragraphs", "sections",
                   "trailing_question", "restates_verdict", "banned_terms",
                   "em_dashes_per_100w", "bullets"}

# A guard probe may drift this much before it counts as collateral damage.
GUARD_TOLERANCE = 0.15

# An owned metric has to clear this on a two-sided permutation test as well as
# move the right way. At n=10 per cell the sign of a difference of means is not
# evidence on its own: two styles shipped a PASS on rows that turned out to be
# p = 0.49 (no-slop-2026.09.08, coverage_pct 76.7 -> 83.3) and p = 0.68
# (no-slop-2026.09.06, prose_paragraphs 5.2 -> 4.9 on ci-permission-denied).
PERM_ALPHA = 0.05
# Above this many distinct splits, enumerating them all costs more than the
# precision is worth. n=10 vs 10 is 184,756 splits, so the shipped cells are
# exact and the fallback is for cells nobody has captured yet.
PERM_EXACT_MAX = 200_000
PERM_SAMPLES = 20_000
PERM_SEED = 20260909    # fixed: see perm_p on why the p-value must not wobble


def perm_p(a, b):
    """Two-sided permutation p-value on the difference of the two means.

    Deterministic by construction. check_style compares a fresh report against
    the stored results.json to decide whether `checked` moves, so a p-value
    that came out differently on every run would rewrite that file on every
    run and date every result to the last time the script was invoked.
    Exact enumeration where the split count allows it, a fixed-seed sample
    otherwise, and rounded to 4 dp either way so the last bit of float noise
    cannot flip the comparison.

    None when either arm has fewer than two samples: there is nothing to
    permute, and a caller that needs significance treats that as not having it.
    """
    a, b = list(a), list(b)
    if len(a) < 2 or len(b) < 2:
        return None
    pool = a + b
    na, n, total = len(a), len(pool), sum(a) + sum(b)
    obs = abs(statistics.mean(a) - statistics.mean(b))

    def diff(idx):
        s = sum(pool[i] for i in idx)
        return abs(s / na - (total - s) / (n - na))

    if math.comb(n, na) <= PERM_EXACT_MAX:
        splits = itertools.combinations(range(n), na)
        trials = math.comb(n, na)
    else:
        rng = random.Random(PERM_SEED)
        splits = (rng.sample(range(n), na) for _ in range(PERM_SAMPLES))
        trials = PERM_SAMPLES
    # >= with a float epsilon: the observed split is one of the splits, and a
    # tie must count as "at least as extreme" or an identical pair reads p=0.
    hits = sum(1 for idx in splits if diff(idx) >= obs - 1e-12)
    return round(hits / trials, 4)


def wants_lower(claims, metric):
    """Which way an owned metric has to move for this style to have kept its word.

    LOWER_IS_BETTER is the default. A style whose claim points the other way —
    the no-slop family deliberately produces two to four times control's
    bullets — declares it in claims.yaml rather than fighting a global constant
    that has no answer for every style at once.
    """
    d = claims.get("directions", {}).get(metric)
    return metric in LOWER_IS_BETTER if d is None else d == "lower"


def summarise(rows):
    out = {}
    for k in NUMERIC:
        vals = [r[k] for r in rows if r[k] is not None]
        out[k] = {
            "mean": round(statistics.mean(vals), 1),
            # Sample sd, at 2 dp because a metric like em_dashes_per_100w
            # rounds to nothing at the mean's 1 dp. None at n=1: one sample has
            # no spread, and 0.0 would claim it had none.
            "sd": round(statistics.stdev(vals), 2) if len(vals) > 1 else None,
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
    tokens, coverage = load_probe(probe_id)
    files = sorted(f for f in d.glob("r*.md"))
    if not files:
        sys.exit(f"no samples in {d}")
    rows = [score_file(f, tokens, coverage) for f in files]
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




# --- style claim checks ----------------------------------------------------

def load_claims(style_dir):
    """Parse styles/<name>/claims.yaml.

    Hand-parsed: the schema is an id and four inline lists, and a YAML
    dependency would not earn its keep.
    """
    path = Path(style_dir) / "claims.yaml"
    if not path.exists():
        sys.exit(f"{style_dir}: no claims.yaml")
    text = re.sub(r"^[ \t]*#.*$", "", path.read_text(), flags=re.M)
    m = re.search(r"^id:\s*(.+)$", text, re.M)
    claims = {"id": m.group(1).strip() if m else Path(style_dir).name}
    # A later version of a style is measured against the version it replaces,
    # not against control: once control already sits near zero on a metric, the
    # only honest question is whether the new text beats the old text.
    b = re.search(r"^baseline:\s*(.+)$", text, re.M)
    claims["baseline"] = b.group(1).strip() if b else "control"
    for key in ("owns", "probes", "guards", "banned"):
        claims[key] = _list_key(text, key)
    # An absolute ceiling, not a relative guard. A relative guard cannot hold a
    # metric whose baseline is already 0.00: every delta against zero is
    # undefined. A style that *relaxes* a rule the previous version drove to
    # zero needs to say how far back up the metric is allowed to come, and that
    # is a number, not a percentage.
    # Absent rather than empty when unset, so adding this key does not perturb
    # the stored claims of every style that predates it and reset its `checked`.
    m = re.search(r"^ceilings:\s*$((?:\n[ \t]+\S.*)*)", text, re.M)
    ceilings = {}
    if m:
        for line in m.group(1).splitlines():
            kv = re.match(r"^[ \t]+([A-Za-z_][\w]*):\s*([0-9.]+)\s*$", line)
            if kv:
                ceilings[kv.group(1)] = float(kv.group(2))
    if ceilings:
        claims["ceilings"] = ceilings
    # Which way an owned metric is supposed to move, where the global default
    # in LOWER_IS_BETTER is wrong for this style. bullets is the case it exists
    # for: the no-slop styles raise it on purpose, so a version claiming it
    # would fail by construction against a constant that says lower is better.
    # Absent rather than empty when unset, for the reason ceilings is.
    m = re.search(r"^directions:\s*$((?:\n[ \t]+\S.*)*)", text, re.M)
    directions = {}
    if m:
        for line in m.group(1).splitlines():
            kv = re.match(r"^[ \t]+([A-Za-z_][\w]*):\s*(lower|higher)\s*$", line)
            if kv:
                directions[kv.group(1)] = kv.group(2)
    if directions:
        claims["directions"] = directions
    return claims


def style_name(style_dir):
    """The frontmatter `name` of style.md — what settings.json references."""
    path = Path(style_dir) / "style.md"
    if not path.exists():
        sys.exit(f"{style_dir}: no style.md")
    m = re.search(r"^---\n(.*?)\n---", path.read_text(), re.S)
    n = re.search(r"^name:\s*(.+)$", m.group(1), re.M) if m else None
    if not n:
        sys.exit(f"{path}: frontmatter needs a 'name'")
    return n.group(1).strip()


def style_version(style_dir):
    """The frontmatter `version` of style.md, or None.

    Claude Code ignores the key: a canary style carrying `version: KTRQ9ZZ`
    applied identically to one without it, and asking the model whether that
    token appeared anywhere in its instructions returned "No". So the field
    identifies an installed copy without changing the text under measurement.
    """
    path = Path(style_dir) / "style.md"
    m = re.search(r"^---\n(.*?)\n---", path.read_text(), re.S)
    v = re.search(r"^version:\s*(.+)$", m.group(1), re.M) if m else None
    return v.group(1).strip() if v else None


def style_digest(style_dir):
    """sha256 of the delivered file. Samples record it; --check enforces it."""
    return hashlib.sha256((Path(style_dir) / "style.md").read_bytes()).hexdigest()


def stale_samples(root, style_dir, sid, probes):
    """Probes whose samples were captured under a different style.md."""
    want = style_digest(style_dir)
    failures = []
    for probe in probes:
        m = root / "samples" / probe / sid / "meta.json"
        if not m.exists():
            continue
        got = json.loads(m.read_text()).get("style_sha256")
        if got is None:
            failures.append(
                f"{probe}: samples predate style hashing (no style_sha256 in "
                f"meta.json) — recapture to bind them to a style.md")
        elif got != want:
            failures.append(
                f"{probe}: samples were captured under style.md {got[:12]}, but "
                f"{style_dir}/style.md is now {want[:12]} — recapture")
    return failures


def banned_counts(sample_dir, terms):
    """Banned-term hits per sample. Word-bounded, so 'genuine' does not also
    match every 'genuinely'."""
    pats = [re.compile(rf"\b{re.escape(x)}\b", re.I) for x in terms]
    return [sum(len(p.findall(f.read_text())) for p in pats)
            for f in sorted(Path(sample_dir).glob("r*.md"))]


def banned_mean(sample_dir, terms):
    """Mean banned-term hits per sample, or None where there are no samples."""
    counts = banned_counts(sample_dir, terms)
    return round(statistics.mean(counts), 2) if counts else None


def metric_mean(result, key):
    s = result["summary"][key]
    if s is None:
        return None
    return s["rate"] if "rate" in s else s["mean"]


def metric_vector(result, sample_dir, key, banned=()):
    """The per-sample values behind a metric's mean.

    A permutation test needs the ten numbers, not the average of them.
    banned_terms is the one metric with no entry in the summary at all — it is
    counted from the raw files against a style's own list — so it is special
    cased here the same way _rows special cases its mean. Booleans come back as
    0/1, which averages to the `rate` metric_mean reports for them.
    """
    if key == "banned_terms":
        return banned_counts(sample_dir, banned)
    if key in BOOLEAN:
        return [1 if r[key] else 0 for r in result["samples"]]
    return [r[key] for r in result["samples"] if r.get(key) is not None]


def provenance(root, sid, probes, baseline="control"):
    """What the compared samples were captured with, read off their meta.json."""
    # model is the alias that was requested ("opus"); model_ids are the exact
    # snapshots that produced the responses, read off modelUsage at capture time
    # as the model with the most output tokens per rep. modelUsage also lists a
    # fixed haiku housekeeping call, which is not what answered. Samples
    # captured before model_ids existed leave it empty, and the record then says
    # the alias is all that is known rather than inventing one.
    seen = {"model": set(), "model_ids": set(), "cli_version": set(),
            "reps": set(), "captured": set()}
    for probe in probes:
        for cond in (baseline, sid):
            m = root / "samples" / probe / cond / "meta.json"
            if not m.exists():
                continue
            d = json.loads(m.read_text())
            for k in seen:
                v = d.get(k)
                if v is None:
                    continue
                seen[k].update(v) if isinstance(v, list) else seen[k].add(v)
    out = {k: sorted(v) for k, v in seen.items()}
    out["captured"] = ([out["captured"][0]] if len(set(out["captured"])) == 1
                       else [out["captured"][0], out["captured"][-1]])
    return out


def _rows(root, claims, sid):
    """Score every declared probe and return (target rows, guard rows, failures)."""
    targets, guards, failures = [], [], []
    measured = {}   # owned metric -> did any probe give it room to move?
    baseline = claims["baseline"]

    for probe in claims["probes"]:
        base_d = root / "samples" / probe / baseline
        style_d = root / "samples" / probe / sid
        if not base_d.exists():
            failures.append(f"{probe}: no samples for baseline '{baseline}' — capture it first")
            continue
        if not style_d.exists():
            failures.append(f"{probe}: no samples for condition '{sid}' — capture it first")
            continue
        base, styled = score_dir(base_d), score_dir(style_d)
        for k in claims["owns"]:
            lower = wants_lower(claims, k)
            if k == "banned_terms":
                b = banned_mean(base_d, claims["banned"])
                r = banned_mean(style_d, claims["banned"])
            else:
                b, r = metric_mean(base, k), metric_mean(styled, k)
            row = {"probe": probe, "metric": k, "baseline": b, "style": r}
            if b is None or r is None:
                row["status"] = "n/a"
                targets.append(row)
                continue
            row["p"] = perm_p(metric_vector(base, base_d, k, claims["banned"]),
                              metric_vector(styled, style_d, k, claims["banned"]))
            if b == 0 and lower:
                # A zero baseline leaves no room to improve, but all the room
                # in the world to regress into. Only zero on both sides is
                # genuinely a metric with no headroom; anything above it is the
                # style putting back what the baseline had driven out.
                if r > 0:
                    row["status"] = "REGRESSED FROM ZERO"
                    failures.append(
                        f"{probe}: owned metric '{k}' rose from a zero baseline "
                        f"to {r:.2f}")
                else:
                    row["status"] = "no headroom"
                # Either way the probe gave the metric no room to improve, so
                # it cannot be what earns the claim; the aggregate check below
                # still has to see that.
                measured.setdefault(k, False)
            else:
                delta = r - b
                better = delta < 0 if lower else delta > 0
                row["delta_pct"] = round(100 * delta / b, 1) if b else None
                measured[k] = True
                if not better:
                    row["status"] = "NO MOVEMENT"
                    failures.append(
                        f"{probe}: owned metric '{k}' did not improve "
                        f"({_delta(row)})")
                elif row["p"] is None or row["p"] >= PERM_ALPHA:
                    # The sign of a difference of means at n=10 is not a
                    # result. A style claiming a metric has to beat the
                    # relabellings of its own samples, not just the baseline.
                    row["status"] = "NOT SIGNIFICANT"
                    failures.append(
                        f"{probe}: owned metric '{k}' moved the right way "
                        f"({_delta(row)}) but not past noise "
                        f"(permutation {_pval(row['p'])}, needs p < {PERM_ALPHA})")
                else:
                    row["status"] = "ok"
            targets.append(row)

    for probe in claims["guards"]:
        base_d = root / "samples" / probe / baseline
        style_d = root / "samples" / probe / sid
        if not base_d.exists():
            failures.append(f"{probe}: no guard samples for baseline '{baseline}'")
            continue
        if not style_d.exists():
            failures.append(f"{probe}: no guard samples for condition '{sid}'")
            continue
        base, styled = score_dir(base_d), score_dir(style_d)
        # Word count is the wrong guard for an explanation: compressing without
        # dropping anything is a pass. Where a probe declares coverage markers,
        # substance is what gets guarded and length is reported for information.
        has_cov = metric_mean(base, "coverage_pct") is not None
        guarded = ("coverage_pct",) if has_cov else ("words",)
        for k in ("coverage_pct", "words", "sections") if has_cov else ("words", "sections"):
            b, r = metric_mean(base, k), metric_mean(styled, k)
            if b is None or r is None:
                continue
            row = {"probe": probe, "metric": k, "baseline": b, "style": r,
                   "delta": round(r - b, 2)}
            if b:
                delta = (r - b) / b
                row["delta_pct"] = round(100 * delta, 1)
                # Only a drop in coverage counts against a style; more is fine.
                bad = (delta < -GUARD_TOLERANCE if k == "coverage_pct"
                       else abs(delta) > GUARD_TOLERANCE)
                moved = f"moved {100 * delta:+.0f}% (tolerance " \
                        f"{int(GUARD_TOLERANCE * 100)}%)"
            else:
                # A zero baseline has no percentage for the tolerance to apply
                # to, and dropping the row entirely hid real movement:
                # no-slop-2026.09.06 took tcp-congestion's sections 0.0 -> 1.1
                # and the report said nothing at all. Report the absolute
                # delta; any movement off zero is outside a relative tolerance.
                row["delta_pct"] = None
                bad = r > 0 and k != "coverage_pct"
                moved = f"moved 0.00 -> {r:.2f}, off a zero baseline"
            row["p"] = perm_p(metric_vector(base, base_d, k),
                              metric_vector(styled, style_d, k))
            # p is reported for the reader and does not gate a guard. A harm
            # alarm should stay sensitive: the point estimate crossing the
            # tolerance is the failure, whether or not ten samples can prove it.
            row["guarded"] = k in guarded
            row["status"] = (("ok" if not bad else "COLLATERAL") if k in guarded
                             else "reported")
            guards.append(row)
            if bad and k in guarded:
                failures.append(f"{probe}: guard metric '{k}' {moved}")

    # Ceilings run over every declared probe, target and guard alike: a metric
    # the style is allowed to give up ground on has to be held everywhere, not
    # only where the style claims an improvement.
    for k, limit in claims.get("ceilings", {}).items():
        for probe in dict.fromkeys(claims["probes"] + claims["guards"]):
            style_d = root / "samples" / probe / sid
            base_d = root / "samples" / probe / baseline
            if not style_d.exists():
                continue
            if k == "banned_terms":
                r = banned_mean(style_d, claims["banned"])
                b = banned_mean(base_d, claims["banned"]) if base_d.exists() else None
            else:
                r = metric_mean(score_dir(style_d), k)
                b = metric_mean(score_dir(base_d), k) if base_d.exists() else None
            if r is None:
                continue
            over = r > limit
            guards.append({
                "probe": probe, "metric": k, "baseline": b, "style": r,
                "delta_pct": None, "guarded": True, "ceiling": limit,
                "status": f"OVER CEILING {limit:g}" if over else f"ok (<= {limit:g})",
            })
            if over:
                failures.append(
                    f"{probe}: '{k}' is {r:.2f}, over the declared ceiling of {limit:g}")

    for k, ok in measured.items():
        if not ok:
            failures.append(
                f"owned metric '{k}' has no headroom on any probe — the control "
                f"already sits at zero, so the style cannot be credited for it")

    return targets, guards, failures


def _cell(v):
    return "n/a" if v is None else f"{v:.2f}"


def _p_cell(row):
    """A row with no p-value has one of two reasons: it is a ceiling, which is
    an absolute cap and not a comparison, or an arm too small to permute."""
    p = row.get("p")
    return "—" if p is None else f"{p:.4f}"


def _delta(row):
    """Relative movement where the baseline gives a percentage a meaning, the
    absolute delta where it is zero, and nothing where there is no comparison
    to make (a ceiling row, or an unmeasurable metric)."""
    d = row.get("delta_pct")
    if d is not None:
        return f"{d:+.0f}%"
    return "—" if row.get("delta") is None else f"{row['delta']:+.2f}"


def _pval(p):
    return "p=n/a" if p is None else f"p={p:.4f}"


def render_md(report):
    """The style's own record, regenerated on every check."""
    c, p = report["claims"], report["provenance"]
    cond, base = report["style"], report["baseline"]
    when = " to ".join(p["captured"]) if len(p["captured"]) > 1 else p["captured"][0]
    L = [
        f"# {cond} — measured result",
        "",
        f"Delivered as output style `{report['name']}`.",
        "",
        f"**{report['result']}.** Last changed {report['checked'][:10]}, "
        f"against `style.md` {report['style_sha256'][:12]}"
        f"{', version ' + report['style_version'] if report.get('style_version') else ''}. "
        f"n={'/'.join(str(x) for x in p['reps'])} per cell, "
        f"model {', '.join(p['model_ids'] or p['model'])}"
        f"{'' if p['model_ids'] else ' (alias only; predates model_ids)'}, "
        f"Claude Code {', '.join(p['cli_version'])}, captured {when}.",
        "",
        f"Regenerated by `bin/score.py --check {report['dir']}`.",
        "",
        "## Claims",
        "",
        f"- **owns** {', '.join(c['owns']) or '(nothing)'}",
        f"- **probes** {', '.join(c['probes']) or '(none)'}",
        f"- **guards** {', '.join(c['guards']) or '(none)'}",
        f"- **baseline** {base}",
    ]
    if c.get("ceilings"):
        L.append("- **ceilings** " + ", ".join(
            f"`{k}` <= {v:g}" for k, v in c["ceilings"].items()))
    if c.get("directions"):
        L.append("- **directions** " + ", ".join(
            f"`{k}` {v} is better" for k, v in c["directions"].items()))
    # p is a two-sided permutation test of the difference of means. On a target
    # it is part of the verdict; on a guard it is for the reader only, because
    # a guard fails on the point estimate crossing GUARD_TOLERANCE.
    L += [
        "",
        "## Targets",
        "",
        f"| probe | metric | {base} | {cond} | delta | p | |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report["targets"]:
        L.append(f"| {r['probe']} | `{r['metric']}` | {_cell(r['baseline'])} | "
                 f"{_cell(r['style'])} | {_delta(r)} | {_p_cell(r)} | "
                 f"{r['status']} |")
    L += ["", "## Guards", "",
          f"| probe | metric | {base} | {cond} | delta | p | |",
          "|---|---|---|---|---|---|---|"]
    for r in report["guards"]:
        L.append(f"| {r['probe']} | `{r['metric']}` | {_cell(r['baseline'])} | "
                 f"{_cell(r['style'])} | {_delta(r)} | {_p_cell(r)} | "
                 f"{r['status']} |")
    if report["failures"]:
        L += ["", "## Failures", ""] + [f"- {f}" for f in report["failures"]]
    return "\n".join(L) + "\n"


def check_style(style_dir):
    root = Path(__file__).resolve().parent.parent
    style_dir = Path(style_dir)
    claims = load_claims(style_dir)
    sid = claims["id"]
    name = style_name(style_dir)
    # A probe may be both a target and a guard; provenance need only see it once.
    probes = list(dict.fromkeys(claims["probes"] + claims["guards"]))

    baseline = claims["baseline"]
    # A version string exists so an installed copy can be traced back here. One
    # that has drifted from the directory it ships in traces back to the wrong
    # thing, so it is checked rather than trusted. Absent is allowed: styles
    # predating the field are not retroactively broken.
    version = style_version(style_dir)
    targets, guards, failures = _rows(root, claims, sid)
    if version is not None and not sid.endswith(f"-{version}"):
        failures.insert(0, f"style.md version '{version}' does not match the "
                            f"condition id '{sid}'")
    failures = stale_samples(root, style_dir, sid, probes) + failures
    # A baseline that is itself a style has a style.md of its own; if that file
    # has moved, the comparison is against text nobody is shipping either.
    if baseline != "control":
        base_dir = root / "styles" / baseline
        if not (base_dir / "style.md").exists():
            failures.insert(0, f"baseline '{baseline}': no styles/{baseline}/style.md")
        else:
            failures = stale_samples(root, base_dir, baseline, probes) + failures
    report = {
        "style": sid,
        "baseline": baseline,
        "name": name,
        "dir": str(style_dir).rstrip("/"),
        "style_sha256": style_digest(style_dir),
        "style_version": version,
        "checked": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "result": "FAIL" if failures else "PASS",
        "claims": claims,
        "provenance": provenance(root, sid, probes, baseline),
        "targets": targets,
        "guards": guards,
        "failures": failures,
    }

    print(f"\nstyle {sid} ({name})")
    print(f"  owns:   {', '.join(claims['owns']) or '(nothing)'}")
    print(f"  probes: {', '.join(claims['probes']) or '(none)'}")
    print(f"  guards: {', '.join(claims['guards']) or '(none)'}")
    print(f"  vs:     {baseline}")
    for section, rows in (("", targets), (" (guard)", guards)):
        last = None
        for r in rows:
            if r["probe"] != last:
                print(f"\n  {r['probe']}{section}")
                last = r["probe"]
            print(f"    {r['metric']:<22} {_cell(r['baseline']):>7} -> "
                  f"{_cell(r['style']):>7}  ({_delta(r)})  "
                  f"{_pval(r.get('p')):<10} {r['status']}")

    # `checked` is the date the result last moved. Rewriting it on every run
    # would churn the diff and lie about when the numbers were established.
    out = style_dir / "results.json"
    if out.exists():
        prev = json.loads(out.read_text())
        if {k: v for k, v in prev.items() if k != "checked"} == \
           {k: v for k, v in report.items() if k != "checked"}:
            report["checked"] = prev["checked"]
            print(f"\n  results unchanged since {report['checked'][:10]}")
        else:
            print(f"\n  results changed -> {style_dir}/results.md")
    out.write_text(json.dumps(report, indent=2) + "\n")
    (style_dir / "results.md").write_text(render_md(report))

    if failures:
        print("\nFAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS  style moved what it owns and left its guards alone")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "--check":
        if len(args) != 2:
            sys.exit("usage: score.py --check <style-dir>")
        sys.exit(check_style(args[1]))
    main(args)
