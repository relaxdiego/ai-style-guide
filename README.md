# Prose style guide for Claude Code

This repository holds a set of writing rules for Claude Code, and the eval
harness that produced them. The guide governs prose: replies in the terminal,
documents, commit bodies, comments, anything a person reads. It does not govern
code, and it says so in its own opening lines. Each rule names a habit worth
suppressing and says what to do instead, and the wording is deliberate, because
the wording is what was measured, so prefer deleting a rule whole over
paraphrasing it.

The guide is built rather than stored. `style/rules.md` is the source of truth,
`harness/package_style.py` assembles it, and CI attaches the assembled file to a
GitHub release. There is deliberately no `CLAUDE.md` in this repository: a second
copy is a second thing to drift, and a `CLAUDE.md` at the root would sit in the
memory-discovery chain of every clean-room sample the harness takes.

## Installing it

The guide is the single file `CLAUDE.md`, attached to every release. Take a copy
of the current one with:

    curl -LO https://github.com/relaxdiego/ai-style-guide/releases/latest/download/CLAUDE.md

Every release is a git tag here, so a tagged version is that wording exactly and
`main` is the latest. For a specific version, name its tag in place of `latest`:

    curl -LO https://github.com/relaxdiego/ai-style-guide/releases/download/v1.1/CLAUDE.md

Then put the file in one of two places, depending on how widely you want it to
apply. For every project you work on, put it in your own configuration
directory:

    mkdir -p ~/.claude
    cp CLAUDE.md ~/.claude/CLAUDE.md

For one repository, and for everyone who works in that repository, put it at the
repository root as `CLAUDE.md` and commit it. Claude Code reads both, so a
project copy adds to your personal one rather than replacing it.

If you already have a `CLAUDE.md` in either place, append instead of
overwriting, or the rest of your instructions go with it:

    cat CLAUDE.md >> ~/.claude/CLAUDE.md

The guide takes effect on the next session. It does not need a restart of
anything else, and nothing else needs configuring.

## What changes

Paragraphs get longer and fewer, because the rule against the one-sentence
paragraph is the one doing the most work. Headings and tables stay in documents
and drop out of conversational replies, while lists, tables and worked examples
survive wherever the content is genuinely a set, a grid or an example. Em-dashes
nearly disappear. Answers stop at the answer rather than closing with an offer of
further work.

The last two sections of the guide are different in kind from the rest. One says
what to do when the rule about developing a paragraph pulls against the rule
about keeping structure, which is the conflict you will hit most often. The other
is a short list of words and habits to look at twice, and it is explicitly not a
set of rules.

## Editing it

The rules are independent of each other, apart from the conflict section near
the end, which refers to the others. If one is wrong for your work, delete it
whole from your installed copy. If you want to add your own, the useful shape is
the one already there: name the habit, then say what to do instead, in enough
words that the instruction survives being applied to a case you did not think of.

To change what ships, edit `style/rules.md` rather than a built guide. Each rule
carries an ID so that an ablation can attribute a metric change to a specific
instruction, and the packager strips those IDs on the way out, since an ID is an
address in this project and means nothing to a reader elsewhere.

## Building it yourself

    python3 harness/package_style.py --out ~/.claude/CLAUDE.md

The packager reads the rule text verbatim, adds the preamble and the two closing
sections, and refuses to emit a guide that names a rule ID, a run, a metric, a
corpus, a substrate or a measurement. It also refuses any path inside this
repository, for the reasons given above. `package_style.build` is the only place
the wording is assembled, and `harness/run.py --guide` builds it in process, so
the document that is measured and the document that ships cannot differ.

## Cutting a release

Push an annotated tag matching `v*`. CI builds the guide from `style/rules.md` at
that commit, fails the run if the packager reports leaked project vocabulary, and
publishes a release with `CLAUDE.md` attached and the provenance in the notes:
the source commit, the SHA-256 of `style/rules.md`, the SHA-256 of the built
guide, and the rule IDs in file order.

    git tag -s v1.1 -m 'Prose style guide 1.1'
    git push origin v1.1

The tag `style-guide-v1.0` predates this convention and has no release attached;
it remains the provenance of the 1.0 wording.

## The research

| file | what it holds |
|---|---|
| `DESIGN.md` | the decision record, and the authority where documents disagree |
| `HARNESS.md` | how the harness is operated, and what its numbers can and cannot say |
| `TAXONOMY.md` | the mannerisms measured, and the held-out set |
| `style/rules.md` | the shipped rules, each with the evidence it is attributed to |
