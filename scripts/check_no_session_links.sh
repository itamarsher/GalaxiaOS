#!/usr/bin/env bash
#
# Guardrail: no Claude session links may be committed.
#
# The autonomous pipeline (and Claude Code in general) appends a per-session
# trailer of the form
#
#     Claude-Session: https://claude.ai/code/session_XXXXXXXX
#
# to commit messages. Those links are private to one account, add nothing for a
# public reader, and were scrubbed from history when the repo was opened up. This
# check keeps them out — of commit messages AND of tracked files — so they can't
# creep back in.
#
# Usage:
#   scripts/check_no_session_links.sh [GIT_RANGE]
#
#   GIT_RANGE  optional revision range (e.g. "$before..$after" or
#              "origin/main..HEAD"). When given, every commit MESSAGE in the
#              range is checked. When omitted, only HEAD's message is checked.
#   Tracked file CONTENTS are always checked at the current tree.
#
# Exit status: 0 when clean, 1 when a link is found.

set -euo pipefail

# Matches the "Claude-Session:" trailer and any claude.ai/.../session URL.
# (Assembled from parts so this file does not match its own pattern.)
PATTERN="[Cc]laude-[Ss]ession:|claude\.ai/[A-Za-z0-9._/-]*""session"

SELF="scripts/check_no_session_links.sh"
fail=0

# 1) Commit messages in the range (new commits only, when a range is supplied).
range="${1:-}"
commits=""
if [ -n "$range" ]; then
  commits="$(git rev-list "$range" 2>/dev/null || true)"
else
  commits="$(git rev-parse HEAD 2>/dev/null || true)"
fi

for c in $commits; do
  if git log -1 --format='%B' "$c" | grep -qE "$PATTERN"; then
    echo "::error::Claude session link in commit message of ${c:0:12}"
    git log -1 --format='    %h %s' "$c"
    fail=1
  fi
done

# 2) Tracked file contents at the current tree (exclude this checker itself).
if hits="$(git grep -nIE "$PATTERN" -- . ":(exclude)$SELF" 2>/dev/null)"; then
  echo "::error::Claude session link found in tracked files:"
  echo "$hits" | sed 's/^/    /'
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo ""
  echo "Remove the Claude session link(s) above before committing."
  echo "  - In a commit message: amend/rebase to drop the 'Claude-Session:' trailer."
  echo "  - Configure Claude Code / the GitHub Action to not append the trailer."
  exit 1
fi

echo "no-session-links OK"
