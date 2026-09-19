#!/bin/bash
#
# Stop hook: ask for a portfolio report when a session committed something and
# has not reported it.
#
# A skill cannot trigger itself — it is instructions, loaded when something
# invokes it. The harness runs hooks, so the hook is what makes reporting
# automatic; it nudges, and the model does the writing. Exit 2 with a message on
# stderr is the "not finished yet" signal, the same mechanism the git-check hook
# uses.
#
# Every bail below is silent and exits 0. This hook must never be the reason a
# session in an unrelated repo cannot end.

set -uo pipefail

input=$(cat)

# Recursion guard: we are already inside a stop hook.
if [[ "$(echo "$input" | jq -r '.stop_hook_active' 2>/dev/null)" == "true" ]]; then
  exit 0
fi

# Not a git repo — nothing was committed, nothing to report.
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

# No credentials, no report. CLAUDE.md is explicit that a session missing the
# token skips silently rather than failing.
[[ -n "${INGEST_TOKEN:-}" ]] || exit 0
[[ -n "${CF_ACCESS_CLIENT_ID:-}" ]] || exit 0
[[ -n "${CF_ACCESS_CLIENT_SECRET:-}" ]] || exit 0

# Only nag for repos that could be on the board. Anything else is someone
# else's project, or a scratch clone.
origin="$(git remote get-url origin 2>/dev/null)" || exit 0
[[ "$origin" == *"CodingDutchie/"* ]] || exit 0

# The dashboard's own repo reports nothing: it is measured like any other
# project, and a session here is usually about the dashboard, not a project.
[[ "$origin" == *"AI-project-dashboard"* ]] && exit 0

head_sha="$(git rev-parse HEAD 2>/dev/null)" || exit 0

# The marker records the last commit reported. It lives in .git/, so it is never
# committed and never travels to another clone.
marker="$(git rev-parse --git-dir)/portfolio-dash-report"

# First time in this clone: adopt the current HEAD silently and say nothing.
# Otherwise opening a repo to read something would ask about work finished
# months ago, and the honest answer to "what shipped this session" is nothing.
# From here on the marker means exactly "reported up to this commit".
if [[ ! -f "$marker" ]]; then
  echo "$head_sha" > "$marker" 2>/dev/null
  exit 0
fi

# Nothing new since the last report.
[[ "$(cat "$marker" 2>/dev/null)" == "$head_sha" ]] && exit 0

# Only the commits since the last report — not an arbitrary tail.
range="$(cat "$marker" 2>/dev/null)..HEAD"
subjects="$(git log --format='  - %s' -n 10 "$range" 2>/dev/null)"

# The marker points at a commit this clone does not have (rebased, or a fresh
# shallow clone). Nothing sensible to diff against, so re-adopt and stay quiet.
[[ -n "$subjects" ]] || { echo "$head_sha" > "$marker" 2>/dev/null; exit 0; }

cat >&2 <<MSG
This session committed work that the portfolio dashboard has not been told about.

Commits since the last report:
$subjects

Use the portfolio-report skill to send what actually shipped and what is next,
then write the marker so this is not asked again. If this project should not be
on the dashboard, write the marker and say so:

  git rev-parse HEAD > "\$(git rev-parse --git-dir)/portfolio-dash-report"
MSG
exit 2
