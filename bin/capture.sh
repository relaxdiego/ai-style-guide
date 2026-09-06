#!/usr/bin/env bash
# Capture N clean-room responses to one probe under one condition.
#
#   bin/capture.sh <probe.md> <condition> [reps] [rule.md]
#
# A rule is delivered as an output style, which is how a real user would ship
# one. Output styles are only discovered from a project .claude/ directory, so
# the throwaway run directory gets a synthesized one. Nothing is written to
# ~/.claude, and --setting-sources project keeps user settings out.
#
# NOTE: --safe-mode cannot be used here. It disables output styles silently, so
# every "with rule" capture would be an unlabelled control. Verified with a
# canary token. Skills and plugins stay out anyway because --tools "" removes
# the Skill tool. See README.md.
set -euo pipefail

PROBE="${1:?usage: capture.sh <probe.md> <condition> [reps] [rule.md]}"
CONDITION="${2:?missing condition (e.g. control, 001)}"
REPS="${3:-10}"
RULE="${4:-}"

export MODEL="${MODEL:-opus}"
CONCURRENCY="${CONCURRENCY:-3}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROBE_ID="$(awk '/^id:/{print $2; exit}' "$PROBE")"
export OUT="$ROOT/samples/$PROBE_ID/$CONDITION"
mkdir -p "$OUT"

# Body of a frontmattered file = everything after the closing fence.
body() { awk 'f>1{print} /^---$/{f++}' "$1"; }

export PROMPT="$(body "$PROBE")"
[ -n "$PROMPT" ] || { echo "empty prompt body in $PROBE" >&2; exit 1; }

# Identical scaffold in both conditions; only the outputStyle key differs, so
# the measured delta is the rule as delivered rather than the scaffold.
export RUN_DIR="$(mktemp -d)"
mkdir -p "$RUN_DIR/.claude/output-styles"
trap 'rm -rf "$RUN_DIR"' EXIT

if [ -n "$RULE" ]; then
  STYLE="rule-$(awk '/^id:/{print $2; exit}' "$ROOT/$RULE")"
  # Our bookkeeping frontmatter is stripped; Claude Code gets only what its
  # own output-style schema expects.
  { printf -- '---\nname: %s\ndescription: style-guide rule %s\n---\n' "$STYLE" "$STYLE"
    body "$ROOT/$RULE"; } > "$RUN_DIR/.claude/output-styles/$STYLE.md"
  printf '{"outputStyle":"%s"}\n' "$STYLE" > "$RUN_DIR/.claude/settings.json"
else
  echo '{}' > "$RUN_DIR/.claude/settings.json"
fi

echo "$PROBE_ID / $CONDITION  ($REPS reps, model=$MODEL${RULE:+, rule=$RULE})"

seq 1 "$REPS" | xargs -P "$CONCURRENCY" -I{} bash -c '
  set -euo pipefail
  printf -v out "%s/r%02d.md" "$OUT" "$1"
  ( cd "$RUN_DIR" && claude -p "$PROMPT" \
      --model "$MODEL" \
      --tools "" \
      --strict-mcp-config \
      --setting-sources project \
      --no-session-persistence \
      --output-format text \
  ) > "$out" 2>/dev/null < /dev/null
  printf "  r%02d: %s words\n" "$1" "$(wc -w < "$out")"
' _ {}

cat > "$OUT/meta.json" <<META
{
  "probe": "$PROBE_ID",
  "condition": "$CONDITION",
  "rule": $( [ -n "$RULE" ] && printf '"%s"' "$RULE" || printf 'null' ),
  "delivery": $( [ -n "$RULE" ] && printf '"output-style"' || printf 'null' ),
  "model": "$MODEL",
  "cli_version": "$(claude --version 2>/dev/null | awk '{print $1}')",
  "captured": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "reps": $REPS,
  "flags": "--tools '' --strict-mcp-config --setting-sources project --no-session-persistence",
  "cwd": "empty non-git tmpdir with synthesized .claude/"
}
META
echo "  meta -> $OUT/meta.json"
