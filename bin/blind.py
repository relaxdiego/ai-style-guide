#!/usr/bin/env python3
"""Build a blinded A/B pack from captured samples, and score a human's picks.

    bin/blind.py build styles/no-slop-2026.09.07 [--per-probe 3] [--seed N]
    bin/blind.py record styles/no-slop-2026.09.07 --picks picks.json

The structural metrics in bin/score.py say a style got shorter and dropped its
banned terms. They cannot say the result reads better. This adds the human gate:
pairs of responses to the same prompt, one from each condition, presented
unlabelled and in randomised order, with the key withheld until every pair has
been judged.

The other side of each pair comes from the condition named by `baseline:` in
claims.yaml, which defaults to control. A style that revises an earlier one
points at that earlier one, so the read asks whether the new text is preferred
to the text it replaces rather than to no style at all.

`build` draws --per-probe reps from each condition of each probe, pairs them,
flips a coin per pair for which side is shown first, shuffles the pair order so
probes interleave, and writes three files into <style-dir>/blind/:

    pack.json   what the reader sees: probe, prompt, left text, right text
    key.json    which side was which, and the sample file each side came from
    page.html   pack.json rendered into bin/blind-page.html, ready to publish

The key is base64-encoded inside page.html so that reading the page source does
not spoil the read by accident. That is obfuscation, not secrecy — the reader is
blinding themselves, not defending against themselves. key.json in the repo is
the authoritative copy and is what `record` scores against.

`record` joins the picks back to the key and writes <style-dir>/blind-read.md
and blind-read.json: per-pair outcome plus a tally, alongside the machine
verdict in results.md. Picks are a JSON object of pair id -> "left" | "right" |
"tie", optionally with a `notes` object of pair id -> string.

Everything is seeded and recorded, so a pack can be rebuilt byte-identical, and
a read is bound to the style.md it was captured under exactly as --check binds
its metrics.
"""
import argparse
import base64
import hashlib
import math
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "blind-page.html"


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def claims(style_dir):
    """The style's id and the probes it declares, hand-parsed like score.py."""
    path = Path(style_dir) / "claims.yaml"
    if not path.exists():
        sys.exit(f"{style_dir}: no claims.yaml")
    text = re.sub(r"^[ \t]*#.*$", "", path.read_text(), flags=re.M)
    m = re.search(r"^id:\s*(.+)$", text, re.M)
    out = {"id": m.group(1).strip() if m else Path(style_dir).name}
    b = re.search(r"^baseline:\s*(.+)$", text, re.M)
    out["baseline"] = b.group(1).strip() if b else "control"
    for key in ("probes", "guards"):
        g = re.search(rf"^{key}:\s*\[(.*?)\]", text, re.M | re.S)
        out[key] = ([v.strip().strip("\"'") for v in g.group(1).split(",") if v.strip()]
                    if g and g.group(1).strip() else [])
    return out


def probe_prompt(probe_id):
    """The prompt body of a probe, frontmatter stripped."""
    path = ROOT / "prompts" / f"{probe_id}.md"
    if not path.exists():
        sys.exit(f"no probe file for '{probe_id}'")
    text = path.read_text()
    m = re.match(r"^---\n.*?\n---\n", text, re.S)
    return text[m.end():].strip() if m else text.strip()


def sample_files(probe, condition):
    d = ROOT / "samples" / probe / condition
    files = sorted(d.glob("r*.md"))
    if not files:
        sys.exit(f"no samples in {d}")
    return files


def check_provenance(style_dir, sid, probes):
    """Refuse to build a pack from samples captured under a different style.md.

    Same rule as score.py --check: a read of stale samples is a read of text
    nobody is shipping.
    """
    want = sha256_file(Path(style_dir) / "style.md")
    for probe in probes:
        m = ROOT / "samples" / probe / sid / "meta.json"
        if not m.exists():
            sys.exit(f"{probe}: no samples for condition '{sid}' — capture it first")
        got = json.loads(m.read_text()).get("style_sha256")
        if got != want:
            sys.exit(f"{probe}: samples were captured under style.md "
                     f"{str(got)[:12]}, but {style_dir}/style.md is {want[:12]} "
                     f"— recapture before building a pack")
    return want


def build(style_dir, per_probe, seed):
    style_dir = Path(style_dir)
    c = claims(style_dir)
    sid = c["id"]
    base = c["baseline"]
    probes = list(dict.fromkeys(c["probes"] + c["guards"]))
    style_sha = check_provenance(style_dir, sid, probes)
    # A baseline that is itself a style is held to its own style.md, so a pack
    # cannot pair the new text against a stale capture of the old text.
    if base != "control":
        check_provenance(ROOT / "styles" / base, base, probes)

    rng = random.Random(seed)
    drawn = []
    for probe in probes:
        ctrl = sample_files(probe, base)
        styled = sample_files(probe, sid)
        n = min(per_probe, len(ctrl), len(styled))
        # Independent draws: rep numbers carry no meaning across conditions, so
        # pairing r03 with r03 would be a false pairing, not a matched one.
        for a, b in zip(rng.sample(ctrl, n), rng.sample(styled, n)):
            drawn.append({"probe": probe, base: a, sid: b})

    # Interleave the probes so neither position in the run nor a run of the same
    # prompt tells the reader anything.
    rng.shuffle(drawn)

    # Balance the side assignment rather than flipping a coin per pair. A fair
    # coin over 12 pairs lands 10-2 often enough to matter, and readers favour
    # one column; an exactly even split removes position from the result.
    half = len(drawn) // 2
    order = [base] * half + [sid] * (len(drawn) - half)
    rng.shuffle(order)

    pairs, key = [], {}
    for i, (d, first) in enumerate(zip(drawn, order), 1):
        second = sid if first == base else base
        pid = f"p{i:02d}"
        pairs.append({
            "id": pid,
            "probe": d["probe"],
            "prompt": probe_prompt(d["probe"]),
            "left": d[first].read_text().strip(),
            "right": d[second].read_text().strip(),
        })
        key[pid] = {
            "probe": d["probe"], "left": first, "right": second,
            "left_file": str(d[first].relative_to(ROOT)),
            "right_file": str(d[second].relative_to(ROOT)),
        }

    out = style_dir / "blind"
    out.mkdir(exist_ok=True)

    pack = {
        "style": sid,
        "baseline": base,
        "style_sha256": style_sha,
        "seed": seed,
        "per_probe": per_probe,
        "built": now(),
        "pairs": [{k: p[k] for k in ("id", "probe", "prompt", "left", "right")}
                  for p in pairs],
    }
    (out / "pack.json").write_text(
        json.dumps(pack, indent=2, ensure_ascii=False) + "\n")

    # Over the pairs and the seed, not the whole file: the pack identifies the
    # read, and the read should survive a rebuild that only moves the build
    # timestamp or edits the page template. The hash keys the saved picks.
    pack_sha = hashlib.sha256(json.dumps(
        {"seed": seed, "pairs": pack["pairs"]},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    (out / "key.json").write_text(json.dumps({
        "style": sid,
        "baseline": base,
        "style_sha256": style_sha,
        "seed": seed,
        "pack_sha256": pack_sha,
        "built": pack["built"],
        "key": key,
    }, indent=2) + "\n")

    if not TEMPLATE.exists():
        sys.exit(f"missing page template: {TEMPLATE}")
    page = TEMPLATE.read_text()
    title = "-".join(w.capitalize() for w in sid.split("-")) + " Blind Read"
    for placeholder, value in (
        ("__PACK__", json.dumps(pack, ensure_ascii=False)),
        ("__KEY__", json.dumps(base64.b64encode(
            json.dumps(key).encode()).decode())),
        ("__PACK_SHA__", json.dumps(pack_sha[:12])),
        ("__TITLE__", title),
        ("__STYLE__", sid),
    ):
        if placeholder not in page:
            sys.exit(f"{TEMPLATE}: no {placeholder} placeholder")
        page = page.replace(placeholder, value)
    (out / "page.html").write_text(page)

    print(f"{len(pairs)} pairs, {per_probe} per probe, seed {seed}")
    for probe in probes:
        print(f"  {probe:<22} {sum(1 for p in pairs if p['probe'] == probe)}")
    print(f"\n  {out}/pack.json   pack {pack_sha[:12]}")
    print(f"  {out}/key.json")
    print(f"  {out}/page.html   publish this")
    return 0


PICK_LABEL = {"left": "left", "right": "right", "tie": "no preference"}


def sign_test(a, b):
    """Two-sided sign test over the pairs where the reader had a preference.

    Ties carry no direction, so they are dropped rather than split. The null is
    a reader choosing by coin flip; it is not a null of 'the style does not
    help', because a reader who recognises the treatment breaks the coin.
    """
    n = a + b
    if not n:
        return None
    k = max(a, b)
    tail = sum(math.comb(n, i) for i in range(k, n + 1))
    return round(min(1.0, 2 * tail / 2 ** n), 5)


def record(style_dir, picks_path):
    style_dir = Path(style_dir)
    keyfile = style_dir / "blind" / "key.json"
    if not keyfile.exists():
        sys.exit(f"{keyfile}: build a pack first")
    kd = json.loads(keyfile.read_text())
    key = kd["key"]

    raw = (sys.stdin.read() if picks_path == "-"
           else Path(picks_path).read_text())
    doc = json.loads(raw)
    picks = doc.get("picks", doc)
    notes = doc.get("notes", {})

    unknown = sorted(set(picks) - set(key))
    if unknown:
        sys.exit(f"picks name pairs not in the key: {', '.join(unknown)}")
    missing = sorted(set(key) - set(picks))

    sid = kd["style"]
    # Packs built before baselines existed have no such field and were all
    # control-vs-style, so that is the right default rather than a failure.
    base = kd.get("baseline", "control")
    c = claims(style_dir)
    role = {p: ("target+guard" if p in c["guards"] else "target")
            for p in c["probes"]}
    role.update({p: role.get(p, "guard") for p in c["guards"]})
    rows, tally = [], {sid: 0, base: 0, "tie": 0}
    per_probe = {}
    for pid in sorted(key):
        if pid not in picks:
            continue
        k = key[pid]
        pick = picks[pid]
        if pick not in PICK_LABEL:
            sys.exit(f"{pid}: pick must be left, right or tie (got {pick!r})")
        chose = "tie" if pick == "tie" else k[pick]
        tally[chose] += 1
        t = per_probe.setdefault(k["probe"], {sid: 0, base: 0, "tie": 0})
        t[chose] += 1
        rows.append({
            "pair": pid,
            "probe": k["probe"],
            "role": role.get(k["probe"], "unknown"),
            "pick": pick,
            "chose": chose,
            "left": k["left"],
            "right": k["right"],
            "left_file": k["left_file"],
            "right_file": k["right_file"],
            "note": notes.get(pid, ""),
        })

    n = len(rows)
    decided = n - tally["tie"]
    report = {
        "style": sid,
        "baseline": base,
        "style_sha256": kd["style_sha256"],
        "pack_sha256": kd["pack_sha256"],
        "seed": kd["seed"],
        "read": doc.get("finished") or now(),
        "reader": doc.get("reader"),
        "n": n,
        "unjudged": missing,
        "tally": tally,
        "per_probe": per_probe,
        "preferred_pct": round(100 * tally[sid] / decided, 1) if decided else None,
        "sign_test_p": sign_test(tally[sid], tally[base]),
        "roles": role,
        "pairs": rows,
    }
    (style_dir / "blind-read.json").write_text(json.dumps(report, indent=2) + "\n")
    (style_dir / "blind-read.md").write_text(render(report))

    print(f"\nblind read — {sid}")
    print(f"  {sid:<12} {tally[sid]}")
    print(f"  {base:<12} {tally[base]}")
    print(f"  {'no pref':<12} {tally['tie']}")
    if missing:
        print(f"  unjudged     {', '.join(missing)}")
    print(f"\n  -> {style_dir}/blind-read.md")
    return 0


def render(r):
    sid = r["style"]
    base = r.get("baseline", "control")
    t = r["tally"]
    pct = ("n/a" if r["preferred_pct"] is None
           else f"{r['preferred_pct']:.0f}% of decided pairs")
    L = [
        f"# {sid} — blind read",
        "",
        f"A human read {r['n']} pairs unlabelled, one response per condition per "
        f"prompt, with the key withheld until the last pair. Read {r['read'][:10]} "
        f"against `style.md` {r['style_sha256'][:12]}, pack "
        f"{r['pack_sha256'][:12]}, seed {r['seed']}.",
        "",
        f"**{sid} preferred in {t[sid]} of {r['n']} pairs** ({pct}); {base} in "
        f"{t[base]}; no preference in {t['tie']}.",
        "",
        f"Regenerated by `bin/blind.py record {r.get('dir', 'styles/' + sid)}`.",
        "",
        "## By probe",
        "",
        f"| probe | {sid} | {base} | no preference |",
        "|---|---|---|---|",
    ]
    for probe, c in sorted(r["per_probe"].items()):
        L.append(f"| {probe} | {c[sid]} | {c[base]} | {c['tie']} |")
    L += ["", "## Pairs", "",
          "| pair | probe | chose | shown left | shown right | note |",
          "|---|---|---|---|---|---|"]
    for p in r["pairs"]:
        chose = "no preference" if p["chose"] == "tie" else p["chose"]
        note = p["note"].replace("|", "\\|").replace("\n", " ")
        L.append(f"| {p['pair']} | {p['probe']} | {chose} | `{p['left_file']}` | "
                 f"`{p['right_file']}` | {note} |")
    if r["unjudged"]:
        L += ["", f"Unjudged: {', '.join(r['unjudged'])}."]
    L += ["", "## What this read does and does not show", ""] + limits(r)
    return "\n".join(L) + "\n"


def limits(r):
    """The caveats a tally cannot carry, stated in the record that carries it.

    Written from the numbers rather than fixed prose, so the file cannot go on
    claiming a caveat the data stopped supporting.
    """
    sid = r["style"]
    base = r.get("baseline", "control")
    t = r["tally"]
    decided = t[sid] + t[base]
    guards = sum(1 for p in r["pairs"] if p["role"] == "guard")
    out = []
    if r["sign_test_p"] is not None:
        out.append(
            f"- **Sign test.** {t[sid]}-{t[base]} over {decided} decided "
            f"pairs, two-sided p = {r['sign_test_p']:g}, against a null of a "
            f"reader picking by coin flip. Ties are dropped, not split.")
    if decided and max(t[sid], t[base]) == decided:
        winner = sid if t[sid] > t[base] else base
        out.append(
            f"- **The sweep is the caveat.** {winner} took every decided pair, "
            f"so the reader separated the conditions perfectly. Labels were "
            f"hidden, but shape is not: a reader who can recognise the "
            f"treatment is no longer blind to it, and this read cannot "
            f"separate preferring the style from recognising it. Read by the "
            f"style's own author, that is the reading to assume until a reader "
            f"who has not seen the style reproduces it.")
    if guards:
        out.append(
            f"- **{guards} of {r['n']} pairs are guard probes.** The style "
            f"claims no improvement there, only no damage. A preference on a "
            f"guard probe is not a claim the style made.")
    out.append(
        f"- **One reader, {r['n']} pairs.** No inter-rater agreement, and the "
        f"pairs are a seeded draw from 10 reps per cell, so a different seed "
        f"draws different responses.")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build a blinded pack and its page")
    b.add_argument("style_dir")
    b.add_argument("--per-probe", type=int, default=3)
    b.add_argument("--seed", type=int, default=20260907)

    r = sub.add_parser("record", help="score picks against the key")
    r.add_argument("style_dir")
    r.add_argument("--picks", required=True, help="JSON file, or - for stdin")

    a = ap.parse_args()
    if a.cmd == "build":
        sys.exit(build(a.style_dir, a.per_probe, a.seed))
    sys.exit(record(a.style_dir, a.picks))
