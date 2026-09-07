#!/usr/bin/env python3
"""Score captured samples for wall-of-text structure.

    bin/score.py samples/storage-choice/control [more/dirs ...]
    bin/score.py --check styles/no-slop-2026.09.06

Writes scores.json into each directory and prints a table. Given more than one
directory, prints deltas against the first (the baseline).

--check reads a style's claims.yaml and verifies the two claims it makes: that
the metrics it *owns* improved on the probes it targets, and that its guard
probes did not move. A style that shortens an explanation probe is over-firing.

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
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

TAIL_QUESTION = 0.15   # final fraction of words searched for a trailing question
TAIL_RESTATE = 0.20    # final fraction searched for a restated verdict


def _list_key(text, key):
    """Parse a possibly multi-line inline YAML list from frontmatter."""
    m = re.search(rf"^{key}:\s*\[(.*?)\]", text, re.M | re.S)
    if not m or not m.group(1).strip():
        return []
    return [v.strip().strip('"\'') for v in m.group(1).split(",") if v.strip()]


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


def score_file(path, tokens, coverage=()):
    text = path.read_text()
    words = text.split()
    n = len(words)
    tail_q = " ".join(words[int(n * (1 - TAIL_QUESTION)):])
    tail_r = " ".join(words[int(n * (1 - TAIL_RESTATE)):])
    verdict_pct = first_token_pct(text, words, tokens)

    blocks = [b for b in re.split(r"\n\s*\n", text.strip()) if b.strip()]
    prose = sum(1 for b in blocks
                if not re.match(r"^\s*([-*+]|\d+\.|\||#|```)", b))

    cov = (round(100 * sum(bool(re.search(c, text, re.I)) for c in coverage)
                 / len(coverage), 1) if coverage else None)

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
        "coverage_pct": cov,
    }


NUMERIC = ["words", "first_verdict_pct", "elaboration_ratio", "prose_paragraphs",
           "bullets", "sections", "code_fence_lines", "em_dashes_per_100w",
           "coverage_pct"]
BOOLEAN = ["trailing_question", "restates_verdict"]

# Metrics a rule is expected to drive down. first_verdict_pct is deliberately
# absent: landing the answer earlier is good, but so is a probe with no verdict.
LOWER_IS_BETTER = {"words", "elaboration_ratio", "prose_paragraphs", "sections",
                   "trailing_question", "restates_verdict", "banned_terms",
                   "em_dashes_per_100w"}

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


def banned_mean(sample_dir, terms):
    """Mean banned-term hits per sample. Word-bounded, so 'genuine' does not
    also match every 'genuinely'."""
    pats = [re.compile(rf"\b{re.escape(x)}\b", re.I) for x in terms]
    files = sorted(Path(sample_dir).glob("r*.md"))
    if not files:
        return None
    return round(statistics.mean(
        sum(len(p.findall(f.read_text())) for p in pats) for f in files), 2)


def metric_mean(result, key):
    s = result["summary"][key]
    if s is None:
        return None
    return s["rate"] if "rate" in s else s["mean"]


def provenance(root, sid, probes, baseline="control"):
    """What the compared samples were captured with, read off their meta.json."""
    # model is the alias that was requested ("opus"); model_ids are the exact
    # snapshots the requests actually ran on, read off modelUsage at capture
    # time. Samples captured before model_ids existed leave it empty, and the
    # record then says the alias is all that is known rather than inventing one.
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
            if k == "banned_terms":
                b = banned_mean(base_d, claims["banned"])
                r = banned_mean(style_d, claims["banned"])
            else:
                b, r = metric_mean(base, k), metric_mean(styled, k)
            row = {"probe": probe, "metric": k, "baseline": b, "style": r}
            if b is None or r is None:
                row["status"] = "n/a"
            elif b == 0 and k in LOWER_IS_BETTER:
                row["status"] = "no headroom"
                measured.setdefault(k, False)
            else:
                delta = r - b
                better = delta < 0 if k in LOWER_IS_BETTER else delta > 0
                row["delta_pct"] = round(100 * delta / b, 1) if b else None
                row["status"] = "ok" if better else "NO MOVEMENT"
                measured[k] = True
                if not better:
                    failures.append(
                        f"{probe}: owned metric '{k}' did not improve "
                        f"({row['delta_pct']:+.0f}%)")
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
            if not b:
                continue
            delta = (r - b) / b
            # Only a drop in coverage counts against a style; more is fine.
            bad = (delta < -GUARD_TOLERANCE if k == "coverage_pct"
                   else abs(delta) > GUARD_TOLERANCE)
            guards.append({
                "probe": probe, "metric": k, "baseline": b, "style": r,
                "delta_pct": round(100 * delta, 1),
                "guarded": k in guarded,
                "status": ("ok" if not bad else "COLLATERAL") if k in guarded
                          else "reported",
            })
            if bad and k in guarded:
                failures.append(
                    f"{probe}: guard metric '{k}' moved {100 * delta:+.0f}% "
                    f"(tolerance {int(GUARD_TOLERANCE * 100)}%)")

    for k, ok in measured.items():
        if not ok:
            failures.append(
                f"owned metric '{k}' has no headroom on any probe — the control "
                f"already sits at zero, so the style cannot be credited for it")

    return targets, guards, failures


def _cell(v):
    return "n/a" if v is None else f"{v:.2f}"


def _delta(row):
    d = row.get("delta_pct")
    return "—" if d is None else f"{d:+.0f}%"


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
        "",
        "## Targets",
        "",
        f"| probe | metric | {base} | {cond} | delta | |",
        "|---|---|---|---|---|---|",
    ]
    for r in report["targets"]:
        L.append(f"| {r['probe']} | `{r['metric']}` | {_cell(r['baseline'])} | "
                 f"{_cell(r['style'])} | {_delta(r)} | {r['status']} |")
    L += ["", "## Guards", "",
          f"| probe | metric | {base} | {cond} | delta | |",
          "|---|---|---|---|---|---|"]
    for r in report["guards"]:
        L.append(f"| {r['probe']} | `{r['metric']}` | {_cell(r['baseline'])} | "
                 f"{_cell(r['style'])} | {_delta(r)} | {r['status']} |")
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
                  f"{_cell(r['style']):>7}  ({_delta(r)})  {r['status']}")

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
