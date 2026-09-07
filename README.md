# ai-style-guide

An experiment harness that measures whether a written style rule, delivered to Claude Code as an [output style](https://code.claude.com/docs/en/output-styles), actually changes the model's output, and whether it damages anything else in the process.

## Testing a style yourself

Ask Claude Code to run the blind read for you:

> Build a blind read for `styles/no-slop-2026.09.06` and publish it, then score my picks.

It will run `bin/blind.py build`, publish the generated `page.html` as an Artifact, and hand you a link. Read the pairs, pick A, B or no preference on each, and hit **Reveal the key** once all of them are judged. Copy the picks JSON off the reveal screen and paste it back into the session; Claude Code runs `bin/blind.py record` and writes the result to `styles/<name>/blind-read.md`.

## How the experiment is set up

Every probe runs under scaffolding that is byte-identical except for the output style setting, so a measured delta is attributable to a rule rather than to the environment.

**The four probes** live in `prompts/` as markdown files with YAML frontmatter (`id`, `kind`, `intent`, and optionally `tools`, `verdict_tokens`, `coverage`).

| id | kind | what it tests |
|---|---|---|
| `storage-choice` | decision | "Postgres or SQLite for a local-first app", asked with stated anxiety. Verdict tokens: SQLite, Postgres |
| `ci-permission-denied` | debug | A script fails on GitHub Actions with "permission denied". One short correct answer exists; the probe tests whether a settled diagnosis still attracts an essay. Verdict tokens: chmod, executable, +x |
| `tcp-congestion` | explain | "Explain how TCP congestion control works." No verdict to land, and length is legitimate. Guard probe, 10 coverage markers (slow start, congestion avoidance, AIMD, fast retransmit/recovery, CUBIC, BBR, duplicate ACK, RTT, window, packet loss) |
| `cleanup-codebase` | underspecified | "My deploy started failing yesterday and I don't know why. Can you help?" The correct move is a clarifying question. Guard probe, 3 coverage markers (logs/output/error, repo/path/project, platform/pipeline) |

`verdict_tokens` are strings whose first appearance is treated as the point where the response commits to an answer. `coverage` holds regexes; the fraction present becomes `coverage_pct`.

`cleanup-codebase` declares `tools: Read,Glob,Grep`. The reason sits in that probe's `intent` field: with no tools at all, the model emitted hallucinated tool-call markup instead of prose in 5 of 10 samples. Given tools and an empty sandbox, it looks, finds nothing, and asks. Both conditions see the same empty sandbox.

**The clean room.** `bin/capture.sh` creates a throwaway `mktemp -d` run directory, empty and non-git, deleted on exit. Into it, it copies the style's `style.md` unchanged as `.claude/output-styles/<name>.md`, and writes a `.claude/settings.json` that sets `outputStyle`. The control arm writes `{}` for settings instead. Same directory, same scaffold, same flags; only the `outputStyle` key differs.

Each capture writes `samples/<probe-id>/<condition>/rXX.md` files plus a `meta.json` recording probe, condition, rule, delivery, model, CLI version (observed 2.1.263), capture timestamp, reps, tools, the exact flags, and a description of the cwd.

**Nothing is rewritten on the way in.** `styles/<name>/style.md` is an output style and nothing else: `name`, `description`, `keep-coding-instructions`, and the prose. Claude Code keys a style by its frontmatter `name`, so the harness names the copied file after that and points `settings.json` at the same string. The file under measurement is the file a user would copy into their own `.claude/output-styles/`. What the style claims lives beside it in `claims.yaml`, out of the delivered path entirely.

## The metrics

All metrics are deterministic and structural, computed per sample file by `bin/score.py`.

| metric | what it counts |
|---|---|
| `words` | total words |
| `first_verdict_pct` | how far into the response the first verdict token appears |
| `elaboration_ratio` | share of the response that comes after the commit point (100 minus `first_verdict_pct`) |
| `trailing_question` | whether a question appears in the final 15% of words |
| `restates_verdict` | whether the verdict reappears in the final 20% of words |
| `prose_paragraphs`, `bullets`, `sections`, `code_fence_lines` | structural shape |
| `em_dashes_per_100w` | em dash density |
| `coverage_pct` | fraction of the probe's coverage regexes present |
| `banned_terms` | occurrences of the rule's banned list, word-bounded so "genuine" does not also match every "genuinely" |

`scores.json`, written into each sample directory, holds probe, condition, verdict tokens, n, a summary (mean/min/max, or hits/of/rate for the two booleans), and the per-sample rows.

## The contract a style signs

`styles/<name>/claims.yaml` states what a style is accountable for, and `--check` holds it to exactly that.

| key | meaning |
|---|---|
| `id` | also the condition directory name under `samples/<probe>/` |
| `owns` | the metrics the style claims to move |
| `probes` | where those metrics must improve |
| `guards` | probes that must not move |
| `banned` | terms counted for the `banned_terms` metric |

`bin/score.py --check <style-dir>` exits 0 or 1 after four checks:

1. **Provenance.** Every capture records the sha256 of the `style.md` it ran under. If that no longer matches the file on disk, the samples describe text nobody is shipping any more, and the check fails with a recapture instruction instead of reporting stale numbers.
2. **Targets.** For each owned metric on each target probe, control to style must move in the improving direction. Otherwise: FAIL, "owned metric did not improve".
3. **No headroom.** If an owned metric's control is already 0 on every probe, that is reported as "no headroom" and FAILS. The style cannot be credited for moving something that was never there.
4. **Guards.** Tolerance is ±15%. Where a probe declares coverage markers, `coverage_pct` is guarded and word count is reported only; the rationale in the code is that word count is the wrong guard for an explanation, since compressing without dropping anything is a pass. Only a drop in coverage counts against a style, and more coverage is fine. Where a probe declares no coverage markers, `words` is guarded.

`--check` writes its verdict back into the style directory as `results.md` and `results.json`, so a style ships with the record that justifies it. Both are rewritten only when the numbers change, so the date they carry is when the result last moved rather than when the check last ran. The current one is [`styles/no-slop-2026.09.06/results.md`](styles/no-slop-2026.09.06/results.md).

## The human gate

The metrics say a style got shorter and dropped its banned terms. They cannot say the result reads better, so `bin/blind.py` puts a person in the loop under the same discipline the metrics get.

`build` draws `--per-probe` reps from each condition of each probe, pairs one control response with one styled response for the same prompt, and writes three files into `styles/<name>/blind/`:

| file | what it is |
|---|---|
| `pack.json` | what the reader sees: probe, prompt, left text, right text |
| `key.json` | which side was which, the sample file behind each side, and the seed |
| `page.html` | `pack.json` injected into `bin/blind-page.html`, ready to publish as an Artifact |

Three things keep the read honest. Reps are drawn independently per condition, because `r03` in one cell has nothing to do with `r03` in the other and pairing them by number would be a false pairing. Side assignment is balanced rather than coin-flipped: over 12 pairs a fair coin lands 10–2 often enough to matter, and readers favour a column. Pair order is shuffled so probes interleave. Like `--check`, `build` refuses to run against samples captured under a different `style.md`.

The page keeps the key base64-encoded and unlocks it only once every pair has a verdict. That is obfuscation, not secrecy — the reader is blinding themselves, not defending against themselves — and `key.json` in the repo is the copy `record` scores against. Picks persist in the artifact's store as they are made, so the read can be put down and picked up.

`bin/blind.py record` joins the picks back to the key and writes `blind-read.md` and `blind-read.json` beside `results.md`. The record carries a two-sided sign test over the decided pairs, marks which probes were targets and which were guards, and states what the tally cannot show — those lines are written from the numbers, so the file cannot go on claiming a caveat the data stopped supporting. The current one is [`styles/no-slop-2026.09.06/blind-read.md`](styles/no-slop-2026.09.06/blind-read.md).

Nothing here feeds `--check`. A blind read is evidence filed next to the machine verdict, not a second gate that can fail a style.

## Running it

```
# capture 10 control reps (default) for a probe
bin/capture.sh prompts/storage-choice.md control

# capture 10 reps under a style; the condition name becomes the sample directory
bin/capture.sh prompts/storage-choice.md no-slop-2026.09.06 10 styles/no-slop-2026.09.06

# score one or more directories; deltas are shown against the first
bin/score.py samples/storage-choice/control samples/storage-choice/no-slop-2026.09.06

# check the style against its claims, and rewrite its results.md
bin/score.py --check styles/no-slop-2026.09.06

# build a blinded A/B pack, publish styles/no-slop-2026.09.06/blind/page.html, read it
bin/blind.py build styles/no-slop-2026.09.06 --per-probe 3

# score the picks the page hands back
bin/blind.py record styles/no-slop-2026.09.06 --picks picks.json
```

Probe files live in `prompts/`. `bin/capture.sh <probe.md> <condition> [reps] [style-dir]` defaults to 10 reps. Name the condition after the style's `id` so `--check` can find it. `MODEL` defaults to `opus` and `CONCURRENCY` to `3`.

Environment setup is devbox plus direnv (`devbox.json`, `.envrc`). `.envrc` exports `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.

## Repo layout

```
prompts/<probe>.md              probe: frontmatter + prompt body
styles/<style>/
  style.md                      the output style, delivered verbatim
  claims.yaml                   owns / probes / guards / banned
  results.md, results.json      written by --check
  blind-read.md, .json          written by blind.py record
  blind/key.json                the pack's answer key and seed
  blind/pack.json, page.html    generated, gitignored
samples/<probe>/control/        r01.md … r10.md, meta.json, scores.json
samples/<probe>/<style-version>/        the same, captured under that style
bin/capture.sh                  clean-room capture
bin/score.py                    metrics, scores.json, --check
bin/blind.py                    blinded A/B pack, and scoring a human's picks
bin/blind-page.html             the page template blind.py builds into
devbox.json, .envrc             environment
```
