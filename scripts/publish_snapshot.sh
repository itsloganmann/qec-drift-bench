#!/bin/bash
# Publish the committed tree (HEAD) as the public snapshot, itsloganmann/qec-drift-bench.
# The snapshot is the private tree without the transcripts (trajectories/) and the archived
# notes (docs/archive/), with the secrets-file line replaced by a placeholder and a note at the
# top of the README. The push happens only when the tree changed and the secret scan is clean.
# Usage: scripts/publish_snapshot.sh [--no-push]   (auto_tick.sh runs it after each refresh)
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1
PUBLIC=https://github.com/itsloganmann/qec-drift-bench.git
pub=.cache/public_snapshot
push=1
[ "${1:-}" = --no-push ] && push=0

if [ ! -d "$pub/.git" ]; then
  mkdir -p .cache
  git clone -q "$PUBLIC" "$pub"
fi
git -C "$pub" fetch -q origin main
git -C "$pub" reset -q --hard FETCH_HEAD
git -C "$pub" clean -fdxq
git -C "$pub" rm -rq .
git archive HEAD | tar -x -C "$pub" --exclude=trajectories --exclude=docs/archive

# The secrets-file line, built in two pieces so that this script does not rewrite itself.
source_line='set -a; source ~/.claude/secrets'
source_line="$source_line.env; set +a"
placeholder='export ANTHROPIC_API_KEY=...   # only the API harness needs it'
find "$pub" -path "$pub/.git" -prune -o -type f \( -name '*.md' -o -name '*.sh' \) -print0 \
  | xargs -0 sed -i '' -e "s|$source_line|$placeholder|"

note='This is a public snapshot of the benchmark: the tasks, the harness, the scoring, the fairness checks and the results. The per-episode transcripts are not in it, because some agents listed files on the machine that ran them; ask the author for access.'
readme="$pub/README.md"
if [ "$(sed -n 1p "$readme" | cut -c1-2)" != "# " ] || [ -n "$(sed -n 2p "$readme")" ]; then
  echo "publish_snapshot: README.md does not start with a title and a blank line" >&2
  exit 1
fi
{ sed -n 1,2p "$readme"; echo "$note"; echo; sed -n '3,$p' "$readme"; } > "$readme.tmp"
mv "$readme.tmp" "$readme"
sed -i '' -e "s|^- \`trajectories/\`:|- \`trajectories/\` (not in this public snapshot):|" "$readme"

git -C "$pub" add -A
if git -C "$pub" diff --cached --quiet; then
  echo "publish_snapshot: the public snapshot is current"
  exit 0
fi
private=$(git rev-parse --short HEAD)
git -C "$pub" -c user.name='Logan Mann' -c user.email='loganmann@ucsb.edu' \
  commit -q -m "Snapshot refresh $(date '+%Y-%m-%d %H:%M %Z') (private $private)"
git -C "$pub" show --stat --format='%h %s' HEAD

scan=$(uv run python scripts/secret_scan.py "$pub")
if [ "$(echo "$scan" | tail -1)" != "hits: 0" ]; then
  echo "publish_snapshot: SECRET SCAN FAILED, nothing pushed" >&2
  echo "$scan" >&2
  git -C "$pub" reset -q --hard FETCH_HEAD
  exit 1
fi
echo "publish_snapshot: secret scan clean ($(echo "$scan" | sed -n 2p))"
if [ "$push" -eq 1 ]; then
  git -C "$pub" push -q origin HEAD:main
  echo "publish_snapshot: pushed $(git -C "$pub" rev-parse --short HEAD) to qec-drift-bench"
else
  echo "publish_snapshot: --no-push, the commit stays local in $pub"
fi
