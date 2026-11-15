#!/usr/bin/env bash
# Put a status line at the top of a release's notes, replacing the one already there.
#   release-status.sh TAG "text"     writes "**Status:** text" as the first line
# Needs GH_TOKEN and GITHUB_REPOSITORY (set in every workflow job that calls it).
set -euo pipefail

TAG=$1
LINE="**Status:** $2"

gh release view "$TAG" -R "$GITHUB_REPOSITORY" --json body -q .body > body.md
LINE="$LINE" python3 - > notes-with-status.md <<'PY'
import os

lines = open("body.md").read().splitlines()
if lines and lines[0].startswith("**Status:**"):
    lines = lines[1:]
while lines and not lines[0].strip():
    lines = lines[1:]
print(os.environ["LINE"] + "\n\n" + "\n".join(lines))
PY
gh release edit "$TAG" -R "$GITHUB_REPOSITORY" --notes-file notes-with-status.md
echo "$LINE"
