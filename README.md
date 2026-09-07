# ai-style-guide

An experimental harness that measures whether an [output style](https://code.claude.com/docs/en/output-styles) improves a model's output. Each style is versioned under `styles/**/style.md`

## Testing a style yourself

Ask Claude Code to run the blind read for you. Example:

> Build a blind read for `styles/no-slop-2026.09.07` and publish it, then score my picks.

It will publish an artifact, and hand you a link. Read the pairs, pick A, B or no preference on each, and hit **Reveal the key** once all of them are judged. Copy the picks JSON off the reveal screen and paste it back into the session; Claude Code runs `bin/blind.py record` and writes the result to `styles/<name>/blind-read.md`.

## Want to know more?

Just ask Claude to explain the rest of the repo.
