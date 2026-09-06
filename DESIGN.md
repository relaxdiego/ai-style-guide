# AI-Writing Eval Harness — Design

Author instructions that suppress AI mannerisms in Claude Code's prose, and prove
the effect with reproducible measurements rather than impressions.

This file is the decision record. Every choice below was settled deliberately;
where a decision has a known weakness, the weakness is stated rather than hidden.

---

## 1. What varies, what is held fixed

The **treatment** is a numbered rule file (`style/rules.md`, rules `R01`–`Rnn`)
assembled into a single prompt and injected with `--append-system-prompt-file`.

Everything else is pinned: the full model ID (`claude-opus-5[1m]`, never the
`opus` alias), the CLI version, the corpus version, and the contents of a
synthesized config directory.

The CLI exposes no temperature, seed, or top-p control. Every measurement is
therefore a distribution, not a value, and no amount of harness care will make a
single run repeatable. This constraint shapes the rest of the design.

## 2. Two substrates

Claude Code's default system prompt is roughly 15k tokens and already contains
substantial anti-mannerism style guidance. A style file appended to it is an
addendum to an existing regime. So every question gets asked twice:

| | **Substrate B** — fast loop | **Substrate A** — the gate |
|---|---|---|
| System prompt | minimal stub via `--system-prompt` | Claude Code default |
| Question | does this rule work *at all*? | does it add anything *on top of the default*? |
| Runs per prompt | N=5 | N=3 |
| Role | drafting aid | acceptance criterion |

B is cheap and gives legible effect sizes, but it measures in a lab that does not
resemble deployment. A rule can pass B and do nothing in A. **B never grants
acceptance; only A does.**

## 3. Corpus

`corpus/v1/` holds 12 frozen prompts: 7 conversational and 5 document.

Conversational prose is where most mannerisms live, but it normally arises after
real work. Tool use adds large variance and cost, so the register is elicited
instead with synthetic staged transcripts ("here is what you just did — report
it") and direct technical questions. Fixtures are synthetic and committed, so the
corpus stays byte-stable for years with no external repo drifting underneath it.

**The corpus is immutable.** New prompts create `corpus/v2/`; `v1` is never
edited. A mutated corpus silently invalidates every historical comparison.

`corpus/v2/` exists as of 2026-09-03. Twelve prompts, the same seven
conversational and five document tasks as v1, written because every v1 sample had
been shown to the copyeditor and a blind read needs text they have never met
(4.4b). It changes one other thing deliberately: v1 was uniformly specialist —
connection pools, row locking, Redis pipelines — which the copyeditor named as a
real obstacle to judging. v2 keeps the writing tasks and the register mix exactly
and moves the subjects to dates, photographs, spreadsheets and uploaded files.
The two corpora are not comparable as absolute numbers and were never meant to
be; v2's control is its own baseline.

## 4. Measurement

Three layers, because no one of them is trustworthy alone.

**4.1 Deterministic detectors.** Regex and heuristic scorers over output text,
reported as **normalized rates per 1,000 words**. Rates rather than counts so
samples of different lengths compare; a **vector of independent metrics with no
composite headline score**, because collapsing eight distinct tics into one
number hides fixing two while worsening three.

Detectors are derived empirically from a real baseline run, not from an a-priori
list of known LLM tells, so they describe the tics this model actually has. The
ratified taxonomy is `TAXONOMY.md`; every detector implements an entry in it.

**Cadence detectors rank above markup detectors.** The two defects that make the
prose tiring to read are prosodic (one-sentence paragraphs at 30% of all
paragraphs; the long-sentence-then-short-verdict close at 10.4%), not
typographic. Markup rates - em-dashes, bold, headers - are real but secondary,
and must never be allowed to stand in for the cadence measures.

**4.2 The Goodhart guard.** A detector that counts what the rules forbid is a
tautology, not a measurement. Two defenses: a **held-out detector set that the
rules are forbidden to name explicitly**, and the pairwise judge below, which
cannot be gamed by token avoidance.

The held-out set must stay large enough to function. Inline bold was proposed
for it and moved to the suppressed set on review: holding a tic out means
nothing instructs against it, so a defect worth fixing cannot also serve as the
guard. The set therefore holds tics real enough to move but low-priority enough
that leaving them uninstructed costs nothing (`TAXONOMY.md`, held-out set).

**4.2b Detector selection is itself a bias.** The first pass at this taxonomy
measured markup - em-dashes, bold, headers - because markup is trivial to regex,
and reported healthy sentence-length variance while missing the staccato
entirely. The staccato is at the paragraph level, invisible to every
sentence-level metric. Had that suite shipped, the harness would have driven the
rules toward suppressing em-dashes while the mannered cadence sailed through
unmeasured, and the numbers would have reported a win.

This is the Goodhart failure arriving from detector *selection* rather than rule
gaming, and the held-out set does not guard against it: held-out detectors are
still detectors someone thought to build. The standing rule: **every detector
must be justified against a quoted passage from a real sample, never invented a
priori**, and each entry in `TAXONOMY.md` carries its evidence.

**4.3 Blinded pairwise judge.** Sonnet, running under a minimal system prompt in
the same clean room, so that Anthropic's own style guidance is not silently one
of the judges. Every pair is judged **twice with positions swapped** and
disagreements counted as ties, because LLM position bias is large enough to
manufacture fake wins. The rubric asks which text reads as though a competent
human wrote it, not which avoids named mannerisms.

Absolute 1-5 rubric scoring was considered and rejected as the least reliable of
the LLM-judge forms.

The judge carries more weight than originally planned. It is the only instrument
that catches defects nobody thought to write a detector for, which 4.2b showed
is a live failure mode rather than a theoretical one.

**4.4 Human spot-check.** Every report carries excerpts: the samples that changed
most since the previous run, plus two fixed samples present in every report so
drift the detectors miss stays visible.

**4.4b The whole-answer blind read, and the reader's exposure budget.** The
detectors and the judge both work on fragments or on aggregates. Neither can
answer whether the prose got better, because a person cannot feel a prose change
from pieces the size of a detector. So the gate is a blind read: one question,
both arms' answers whole, first word to last, no numbers on the page, column
assignment from a hash of the sample key, arm revealed per pair only after the
verdict. "No difference" is a first-class answer and is the one the measurements
cannot give.

**The first attempt at this failed, and the failure is instructive.** The
copyeditor picked the ruled arm 11 times in 12, then said unprompted that they
had read the prose before. They had. `make_verdict_reader.py` had shown the
opening paragraph of every substrate-A sample, in both arms, under explicit
labels. About half of every answer's words had already appeared in one galley or
another. The read was spent and nothing in the harness knew.

**A reader's naivety about a sample is a consumable resource, and it is spent by
looking.** It cannot be restored, it is not visible in any run directory, and a
galley that names an arm spends it completely. `harness/exposure.py` is the
ledger: every galley records the sample keys it showed and whether it named the
arm, and `make_plain_reader.py` refuses to call a read blind over text the ledger
says was already shown. The ledger is committed, because it is evidence about the
reader rather than about the model and cannot be reconstructed from the runs.

The operational consequence: **a blind read needs text no labelled galley has
touched, and lab galleys must therefore not be pointed at a run reserved for
reading.** Generate more repeats than a galley will show and hold the remainder
back.

**4.5 Acceptance.** A change counts only when it moves a metric outside the
measured noise band. Effect sizes against measured variance — at n=12 prompts
there is no power for significance testing, and reporting a p-value would imply
rigor the sample size cannot support.

## 5. Clean room

A scratch `CLAUDE_CONFIG_DIR` is synthesized per run with `.credentials.json`
copied in at mode 600 and removed by an exit trap.

This is required, not stylistic: both stronger isolation levers break
subscription auth. Measured on v2.1.259:

| Setup | Result |
|---|---|
| `claude -p` from an empty dir | works |
| `--bare` | `Not logged in` — reads only `ANTHROPIC_API_KEY`/`apiKeyHelper` |
| `CLAUDE_CONFIG_DIR=/tmp/clean` | `Not logged in` |
| `CLAUDE_CONFIG_DIR` + copied credentials | **works** |
| `--setting-sources "" --strict-mcp-config` | works |

Flags applied on top of the scratch dir, belt-and-braces:

    --setting-sources ""        --strict-mcp-config
    --disable-slash-commands    --permission-mode dontAsk
    --permission-prompts none   --disallowed-tools <all>
    --system-prompt-snapshot off
    --max-budget-usd <cap>

`--system-prompt-snapshot off` matters specifically because the appended prompt
changes between runs, which is the exact case snapshotting would poison.

**Two mechanisms block memory, and each covers a different file.** Re-measured
2026-09-04 with a canary reading "Begin every reply with the exact word
ZEPPELIN", planted in one location at a time, CLI pinned to 2.1.259:

| setup | canary planted in | fires? |
|---|---|---|
| no redirect, no flags | real `~/.claude/CLAUDE.md` | yes |
| `CLAUDE_CONFIG_DIR` redirected, no flags | real `~/.claude/CLAUDE.md` | no |
| `CLAUDE_CONFIG_DIR` redirected, no flags | `$CLAUDE_CONFIG_DIR/CLAUDE.md` | yes |
| `CLAUDE_CONFIG_DIR` redirected, no flags | `cwd/CLAUDE.md` | yes |
| the full clean room | real `~/.claude/CLAUDE.md` | no |

User memory follows `CLAUDE_CONFIG_DIR`. `make_scratch_config()` copies only
`.credentials.json` into the scratch dir, so the shipped guide installed at
`~/.claude/CLAUDE.md` has no route into a sample, and every manifest's
`config_dir_inventory` records that no `CLAUDE.md` was there.
`--setting-sources ""` is load-bearing for the other file: the scratch dir is
created under `.scratch/` inside the repo, so a `CLAUDE.md` at the repo root
sits in the discovery chain of every sample's cwd, and only the flag keeps it
out. Neither mechanism covers both files, so neither is redundant.

**This section has now been wrong in both directions.** It first called the
flags belt-and-braces redundancy around the scratch dir, which understated the
flag. It was then corrected to say the redirect does nothing and the flag is the
only protection, on a canary reading that does not reproduce, which understated
the redirect. A future session that drops the redirect because the flag is "the
only thing" would put the treatment into every arm and the comparisons would
still look healthy.

`harness/check_cleanroom.py` holds the test, and it now probes one route per
mechanism, each with its own positive control planted in the same file it is
protecting:

| route | canary planted in | clean-room arm | positive control |
|---|---|---|---|
| user memory | real `~/.claude/CLAUDE.md` | must stay silent | no redirect, no flags |
| project memory | `<repo>/CLAUDE.md` | must stay silent | redirect, no flags |

A canary that cannot be read anywhere now fails the control rather than passing
as a clean result, which is what the earlier version did: it planted in the real
`~/.claude/CLAUDE.md` and then ran both arms with the redirect in place, so both
came back silent. Run green on 2026-09-06 against CLI 2.1.263 — not the 2.1.259
the frozen arms were measured on, so it is evidence about the mechanisms and not
a re-measurement of an arm. `run.py` also calls the free static check before
spending anything and exits 78 if the flag has gone; that check is a string
search over `cleanroom.sh` plus a leftover-canary sweep, not a proof that the
flag still does what it did. No run to date is contaminated by either route:
every manifest carries the flag in its argv and lists a scratch config dir with
no `CLAUDE.md` in it.

**Upgrade path:** an `ANTHROPIC_API_KEY` enables `--bare`, which skips hooks,
LSP, plugin sync, auto-memory, keychain reads, and CLAUDE.md discovery at the
source rather than by flag. That is the strictest room available and should be
adopted if a key becomes available.

**Provenance.** Every run writes `manifest.json`: full model ID, `claude
--version`, corpus version, SHA-256 of the assembled style prompt, exact argv,
synthesized config dir contents, git SHA, and UTC timestamp. Committed results
without provenance are uninterpretable later.

## 6. Economics

The frozen control arm is measured **once and reused**, so a routine iteration
runs treatment only: 96 samples. The one-time noise floor is 10 repeats across
12 prompts.

**Measured on the step-2 baseline** (96 samples, both substrates, 96/96 ok):

    total          $6.60        wall clock 826s (~14 min) at concurrency 4
    per sample     $0.0688 mean, $0.017 min, $0.2366 max
    output length  627 words mean, 688 median, 42-1452 range

This is materially higher than the pre-run guess of $2-3. The guess extrapolated
from a 14-token test reply; real outputs run 400-1000 words and Opus output
tokens dominate the bill. Prompt caching helps the input side only.

**A routine treatment iteration therefore costs about $6-7, and a full
control-plus-treatment comparison about $13.** The one-time noise floor (10
repeats x 12 prompts on one arm) is roughly $8-14. Budget accordingly: this is
not a harness to re-run casually on every edit, which is the reason substrate B
exists as a cheaper drafting loop and the frozen control is reused rather than
re-measured.

Per-run `modelUsage` gives exact token counts and cost, so spend is tracked
precisely rather than guessed.

## 7. Noise floor

10 repeats per prompt on the control arm, establishing a per-detector variance
band. Re-measured when the pinned model ID changes, the CLI version changes
materially, or the corpus version bumps.

The harness is meant to compare the current manifest against the floor's
manifest and **refuse to report a verdict when they diverge**. The realistic
failure is not a bad estimate but a silently stale one: comparing today's run
against a band measured on a model that no longer exists.

**No code does this.** `run.py` records `cli_version()` and nothing reads it
back, so the pin in section 1 is documentation. It has already drifted: every
run to date, both frozen controls included, is CLI 2.1.259, and 2.1.260 is
installed. The guide-as-shipped run of 2026-09-04 was pinned back by putting a
symlink named `claude` ahead of the real one on `PATH`. Issue #15 carries the
fix.

## 8. Rules and ablation

Rules are numbered and individually addressable, assembled into the injected
prompt at runtime. IDs cost nothing now and are painful to retrofit onto months
of history keyed to unnumbered prose. They also give reports and commit messages
a shared vocabulary.

Single-rule ablation (`--ablate R07`) is supported but **opt-in**, used when a
metric moves and the cause is unclear. Routine full ablation is
`rules x prompts x N` runs and is a bad trade at these prices.

## 9. Run mechanics

Parallelism of 4 with exponential-backoff retry. Failed, refused, and truncated
samples are recorded in the manifest, excluded from metrics, and **reported
loudly**. Silent dropping is the dangerous option: a failure mode correlated with
the treatment would bias results invisibly. If a style rule starts triggering
refusals or truncation, that is a finding about the rule.

No CI. Headless auth is unavailable on push, threshold gating would fail routine
commits, and the runs cost money — spending should be deliberate.

## 10. Results and retention

Results are committed. `runs/<utc>-<sha>/` holds `manifest.json`, `samples/`,
`result.json`, and `report.md`. Comparison is against **both** a permanently
frozen zero-instruction control (absolute effect of the whole style file) and the
previous run (marginal effect of this edit).

**Raw outputs are kept forever, plain text, never gzipped.** The reason is
retroactive re-scoring: a detector written in month three can be backfilled
across all history, but only if the raw text survived. That is worth far more
than the disk. Plain rather than compressed so outputs stay greppable and
diffable.

`report.md` carries a header (style SHA, model, corpus version, cost, sample
count), a metric table (frozen control / previous / current / delta / cleared the
noise band?), the judge record including swap-disagreement rate, any failed
samples listed explicitly, and the excerpt block.

## 11. Layout and stack

Stdlib Python 3.13 and bash, zero dependencies. The detectors are regex and
arithmetic and the statistics are means and standard deviations; scipy buys
nothing and a dependency-free harness still runs in two years.

    corpus/v1/      frozen prompts
    style/rules.md  numbered rules R01..Rnn
    build/          assembled prompt (derived, gitignored, SHA in manifest)
    harness/        cleanroom.sh, run.py, detectors/, judge.py, report.py
    baseline/       frozen control outputs and noise floor
    runs/           committed per-run results

    devbox run eval          full run, both substrates
    devbox run eval-quick    substrate B only
    devbox run baseline      re-measure the noise floor

## 12. Build order

1. Clean-room runner, manifest, corpus v1
2. Baseline run, no style file, both substrates
3. **Hard stop.** Raw outputs handed over for the mannerism taxonomy to be named
   from the evidence, not from a summary of it
4. Detectors implementing `TAXONOMY.md`, including the held-out set
5. Noise floor
6. Pairwise judge and report generation
7. First `style.md`, first scored iteration

Packaging (output-style and `CLAUDE.md` adapters) is deferred until the evals say
the instructions are worth shipping. `build/style.prompt.md` is the manual
escape hatch meanwhile.

**The `CLAUDE.md` adapter is now built, on the strength of the first blind read.**
`harness/package_style.py` writes the shipped rules out as a standalone prose
style guide: the IDs and headings stripped, two closing sections added, and a
check that refuses to emit anything naming a rule ID, a run, a metric, a corpus,
a substrate or a measurement. The guide has to read as though written from
scratch, because what the evidence bought is the wording, not a citation.

**The repo keeps no copy of the guide**, and the packager refuses a path inside
the repo. A second copy is a second thing to drift, and a `CLAUDE.md` at the repo
root sits in the memory-discovery chain of every clean-room sample (section 5).
The guide is installed as the user's own `~/.claude/CLAUDE.md`.

**A release of the guide is a git tag here and a push to a separate repository.**
Cutting one means running the packager to a path outside this repo and tagging
the commit whose `style/rules.md` produced it, so the wording can be rebuilt
from the tag alone. `style-guide-v1.0` is the first, cut from style sha
`daee39bf` at `d1e4d10`. Its tag message names the working directory the release
was assembled in, which no longer exists; the tag is provenance for the wording,
not a path.

The guide is published at **`github.com/relaxdiego/ai-style-guide`**, public,
one file plus a README, versioned by its own tags (`v1.0` is style sha
`daee39bf`). That repository is the thing to hand somebody, and this one still
keeps no copy of the guide, for the reason in section 5. Two repositories now
have to be kept in step: a new release is the packager, then a commit and a tag
there, then a tag here.

**The check that used to guard this was pointed the wrong way.** Diffing the
published file against a fresh package proves only that two copies of the release
agree. It could never notice that the packager's output differed from anything
ever measured, which it did: the release carried 244 words no run had seen, and
those words together with the stripped headings and the rewritten preamble
interacted to give back a quarter of the em-dash win. That is closed at the
source now. `package_style.build` is the only place the wording is assembled and
`run.py --guide` injects it, so the document measured is the document installed.

**Cutting a release is therefore:** a `--guide` run on the acceptance corpus, a
blind read of it against the frozen control, then the packager to a path outside
the repo, a commit and tag there, and a tag here. The published file, a fresh
package, `build/style.prompt.md` and the installed `~/.claude/CLAUDE.md` should
all carry one sha; on 2026-09-04 all four read `f20b1ebd`.

The `style-guide-v1.0` tag message names style sha `daee39bf`, which was the old
assembler's output and is no longer a document this pipeline emits. The guide it
names is unchanged and still rebuilds from the tag with one command, so the sha
is left as written for the reason already applied to the stale directory path it
also carries: the tag is provenance for the wording, and the wording has not
moved.

The output-style adapter is still deferred.

## 13. Known project risk, and what the baseline settled

The design rested on substrate A showing measurable movement, on the worry that
Claude Code's default prompt already does much of this work.

**The baseline settled this, and favourably.** A and B differ by almost nothing
across every metric measured (`TAXONOMY.md`). Stripping the entire default system
prompt barely moves the prose, so the mannerisms are model-intrinsic and there is
room for the rules to act. Appending remains viable; no shift toward replacing
the system prompt is needed.

The same finding costs something. Substrate B is not the cleaner lab the design
assumed - it is nearly the same lab as A. Its value is now cost and speed alone,
not interpretive clarity, and a result that appears in B should be expected to
appear in A rather than treated as a separate question. If B and A ever diverge
sharply on a rule, that divergence is itself the finding.
