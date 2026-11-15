# Shared helpers. Sourced by every epic-* script (never executed directly).
EPIC_HOME="${EPIC_CONDUCTOR_HOME:-$HOME/.epic-conductor}"
EPIC_MAX_ATTEMPTS="${EPIC_MAX_ATTEMPTS:-3}"   # 1 first run + 2 respawns

# Accept https://github.com/<owner>/<repo>/issues/<n> or <owner>/<repo>#<n>.
# Sets OWNER, REPO, IID, PROJECT_NAME (= REPO), REPO_SLUG, ISSUE_URL.
parse_issue() {
  local s="$1"
  local url_re='^https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([0-9]+)/?([?#].*)?$'
  local short_re='^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([0-9]+)$'
  if [[ "$s" =~ $url_re || "$s" =~ $short_re ]]; then
    OWNER="${BASH_REMATCH[1]}"; REPO="${BASH_REMATCH[2]}"; IID="${BASH_REMATCH[3]}"
    PROJECT_NAME="$REPO"; REPO_SLUG="$OWNER/$REPO"
    ISSUE_URL="https://github.com/$OWNER/$REPO/issues/$IID"
  else
    echo "not a GitHub issue reference: $s (want https://github.com/<owner>/<repo>/issues/<n> or <owner>/<repo>#<n>)" >&2
    return 1
  fi
}

# Epic names end up in paths, tmux session names and sed expressions.
validate_epic() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo "bad epic name: $1 (letters, digits, . _ - only)" >&2; return 1; }
}

session_name() { printf 'epic-%s-%s-%s' "$1" "$2" "$3" | tr -c 'A-Za-z0-9\n-' '-'; }

workbench_dir() { printf '%s/workspace/%s_workspace/workbench/issue_%s' "$HOME" "$1" "$2"; }

to_epoch() {
  date -j -u -f '%Y-%m-%dT%H:%M:%SZ' "$1" +%s 2>/dev/null || date -u -d "$1" +%s
}

live_file() { printf '%s/%s/live/%s-%s' "$EPIC_HOME" "$1" "$2" "$3"; }

# Echo the tmux target of a live (human-driven) worker, or nothing.
live_target() { local f; f="$(live_file "$1" "$2" "$3")"; [ -f "$f" ] && cat "$f" || true; }

# Number of STARTED lines already logged for <repo>/<n>.
started_count() {
  local log="$EPIC_HOME/$1/UPDATES.log"
  [ -f "$log" ] || { echo 0; return; }
  awk -F'\t' -v i="$2" '$2==i && $3=="STARTED"' "$log" | wc -l | tr -d ' '
}

# Attempt number the next worker for <repo>/<n> would be.
attempt_number() { echo $(( $(started_count "$1" "$2") + 1 )); }

