#!/usr/bin/env bash
# Capture N clean-room responses to one probe under one condition.
#
#   bin/capture.sh <probe.md> <condition> [reps] [style-dir]
#
# A style is delivered as a Claude Code output style, which is how a real user
# would ship one: styles/<name>/style.md is copied verbatim into the run
# directory. Output styles are only discovered from a project .claude/
# directory, so the throwaway run directory gets one. Nothing is written to
# ~/.claude, and --setting-sources project keeps user settings out.
#
# NOTE: --safe-mode cannot be used here. It disables output styles silently, so
# every "with style" capture would be an unlabelled control. Verified with a
# canary token. Skills and plugins stay out anyway because --tools "" removes
# the Skill tool. See README.md.
set -euo pipefail

PROBE="${1:?usage: capture.sh <probe.md> <condition> [reps] [style-dir]}"
CONDITION="${2:?missing condition (e.g. control, no-slop)}"
REPS="${3:-10}"
STYLE_DIR="${4:-}"
STYLE_SHA=""

export MODEL="${MODEL:-opus}"
CONCURRENCY="${CONCURRENCY:-3}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROBE_ID="$(awk '/^id:/{print $2; exit}' "$PROBE")"
export OUT="$ROOT/samples/$PROBE_ID/$CONDITION"
mkdir -p "$OUT"

# Body of a frontmattered file = everything after the closing fence.
body() { awk 'f>1{print} /^---$/{f++}' "$1"; }

# Probes that read as a task make the model reach for tools even when it has
# none, and it emits hallucinated tool-call markup instead of prose. Such a
# probe declares read-only tools and gets an empty sandbox to find nothing in.
export TOOLS="$(awk -F': *' '/^tools:/{print $2; exit}' "$PROBE")"
export PERM_MODE=""
[ -n "$TOOLS" ] && PERM_MODE="bypassPermissions"

export PROMPT="$(body "$PROBE")"
[ -n "$PROMPT" ] || { echo "empty prompt body in $PROBE" >&2; exit 1; }

# Identical scaffold in both conditions; only the outputStyle key differs, so
# the measured delta is the style as delivered rather than the scaffold.
export RUN_DIR="$(mktemp -d)"
mkdir -p "$RUN_DIR/.claude/output-styles"
trap 'rm -rf "$RUN_DIR"' EXIT

if [ -n "$STYLE_DIR" ]; then
  SRC="$ROOT/${STYLE_DIR#"$ROOT/"}/style.md"
  [ -f "$SRC" ] || { echo "no style.md in $STYLE_DIR" >&2; exit 1; }
  # Claude Code keys the style by its frontmatter `name`, and settings.json has
  # to reference that same name. Nothing is stripped or rewritten on the way in:
  # the file measured here is the file a user would copy into .claude/.
  STYLE="$(awk '/^---$/{f++; next} f==1 && /^name:/{sub(/^name: */, ""); print; exit}' "$SRC")"
  [ -n "$STYLE" ] || { echo "$SRC: frontmatter needs a 'name'" >&2; exit 1; }
  cp "$SRC" "$RUN_DIR/.claude/output-styles/$STYLE.md"
  # Recorded so score.py can refuse to score samples against a style.md that
  # has been edited since they were captured.
  STYLE_SHA="$(sha256sum "$SRC" 2>/dev/null || shasum -a 256 "$SRC")"
  STYLE_SHA="${STYLE_SHA%% *}"
  printf '{"outputStyle":"%s"}\n' "$STYLE" > "$RUN_DIR/.claude/settings.json"
else
  echo '{}' > "$RUN_DIR/.claude/settings.json"
fi

echo "$PROBE_ID / $CONDITION  ($REPS reps, model=$MODEL${STYLE_DIR:+, style=$STYLE_DIR})"

seq 1 "$REPS" | xargs -P "$CONCURRENCY" -I{} bash -c '
  set -euo pipefail
  printf -v out "%s/r%02d.md" "$OUT" "$1"
  args=(-p "$PROMPT" --model "$MODEL" --tools "$TOOLS" --strict-mcp-config
        --setting-sources project --no-session-persistence --output-format text)
  [ -n "$PERM_MODE" ] && args+=(--permission-mode "$PERM_MODE")
  ( cd "$RUN_DIR" && claude "${args[@]}" ) > "$out" 2>/dev/null < /dev/null
  printf "  r%02d: %s words\n" "$1" "$(wc -w < "$out")"
' _ {}

cat > "$OUT/meta.json" <<META
{
  "probe": "$PROBE_ID",
  "condition": "$CONDITION",
  "style": $( [ -n "$STYLE_DIR" ] && printf '"%s"' "${STYLE_DIR%/}" || printf 'null' ),
  "delivery": $( [ -n "$STYLE_DIR" ] && printf '"output-style"' || printf 'null' ),
  "style_sha256": $( [ -n "$STYLE_SHA" ] && printf '"%s"' "$STYLE_SHA" || printf 'null' ),
  "model": "$MODEL",
  "cli_version": "$(claude --version 2>/dev/null | awk '{print $1}')",
  "captured": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "reps": $REPS,
  "tools": "${TOOLS:-none}",
  "flags": "--tools '$TOOLS' --strict-mcp-config --setting-sources project --no-session-persistence${PERM_MODE:+ --permission-mode $PERM_MODE}",
  "cwd": "empty non-git tmpdir with synthesized .claude/"
}
META
echo "  meta -> $OUT/meta.json"
