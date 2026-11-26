#!/bin/bash
# Publish the committed tree (HEAD) as the public snapshot, itsloganmann/quantum-bench.
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1
PUBLIC=https://github.com/itsloganmann/quantum-bench.git
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

readme="$pub/README.md"
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
  echo "publish_snapshot: pushed $(git -C "$pub" rev-parse --short HEAD) to quantum-bench"
else
  echo "publish_snapshot: --no-push, the commit stays local in $pub"
fi
