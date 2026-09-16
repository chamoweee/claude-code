#!/usr/bin/env bash
#
# Move the Opportunity Radar history database between the runner and a
# dedicated `radar-data` branch, so that a weekday of bot commits never lands
# in the code history on main.
#
# This uses git plumbing (hash-object / mktree / commit-tree) rather than
# checking the branch out. That means it never switches branch, never touches
# the working tree, and cannot leave the runner on the wrong ref if it fails
# halfway. The branch ends up holding exactly one file, `radar.db`, with one
# commit per run that changed it.
#
#   radar-history.sh restore          fetch the newest database, if any
#   radar-history.sh save "message"   push the current database, if changed
#
set -euo pipefail

BRANCH="radar-data"
REMOTE_FILE="radar.db"
REPO_ROOT="$(git rev-parse --show-toplevel)"
DB_PATH="$REPO_ROOT/opportunity-radar/data/radar.db"
MAX_BYTES=$((80 * 1024 * 1024))

# Fetch the branch into FETCH_HEAD. Returns non-zero when it does not exist yet,
# which is the normal state before the very first run.
fetch_branch() {
  git fetch --no-tags --depth=1 origin "$BRANCH" >/dev/null 2>&1
}

restore() {
  if ! fetch_branch; then
    echo "No '$BRANCH' branch yet — starting from the baseline committed in the repo."
    return 0
  fi
  if ! git rev-parse --verify --quiet "FETCH_HEAD:$REMOTE_FILE" >/dev/null; then
    echo "Branch '$BRANCH' exists but holds no $REMOTE_FILE — using the repo baseline."
    return 0
  fi
  mkdir -p "$(dirname "$DB_PATH")"
  git cat-file blob "FETCH_HEAD:$REMOTE_FILE" > "$DB_PATH"
  echo "Restored history from '$BRANCH' ($(wc -c < "$DB_PATH") bytes)."
}

save() {
  local message="${1:-radar run}"

  if [ ! -f "$DB_PATH" ]; then
    echo "No database at $DB_PATH — nothing to save."
    return 0
  fi

  local size
  size=$(wc -c < "$DB_PATH")
  if [ "$size" -gt "$MAX_BYTES" ]; then
    echo "Refusing to push: the database is ${size} bytes, over the ${MAX_BYTES} limit." >&2
    return 1
  fi

  # commit-tree needs a committer identity even though nothing is checked out.
  git config user.name "opportunity-radar[bot]"
  git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

  local blob parent="" existing="" tree commit
  blob=$(git hash-object -w "$DB_PATH")

  if fetch_branch; then
    parent=$(git rev-parse FETCH_HEAD)
    existing=$(git rev-parse --verify --quiet "FETCH_HEAD:$REMOTE_FILE" || true)
    if [ "$existing" = "$blob" ]; then
      echo "History unchanged — nothing to push."
      return 0
    fi
  fi

  # A tree containing just the database, so the branch stays a pure data log.
  tree=$(printf '100644 blob %s\t%s\n' "$blob" "$REMOTE_FILE" | git mktree)

  if [ -n "$parent" ]; then
    commit=$(git commit-tree "$tree" -p "$parent" -m "$message ($(date -u +%Y-%m-%dT%H:%MZ))")
  else
    echo "Creating the '$BRANCH' branch."
    commit=$(git commit-tree "$tree" -m "$message ($(date -u +%Y-%m-%dT%H:%MZ))")
  fi

  git push origin "$commit:refs/heads/$BRANCH"
  echo "Saved history to '$BRANCH' (${size} bytes)."
}

case "${1:-}" in
  restore) restore ;;
  save)    save "${2:-radar run}" ;;
  *)
    echo "usage: $0 {restore|save [message]}" >&2
    exit 2
    ;;
esac
