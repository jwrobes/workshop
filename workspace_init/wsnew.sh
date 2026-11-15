#!/usr/bin/env bash
# Headless invocation of the scaffold-workspace skill, seeded from a GitHub issue URL,
# a GitHub repo URL, or a bare owner/repo slug. (Ported from a GitLab version.)
# Usage: wsnew.sh <target> [--project NAME] [--initiative NAME] [--ref repo1,repo2] [--yes]
set -euo pipefail

TARGET=""
PROJECT_OVERRIDE=""
INITIATIVE_OVERRIDE=""
REF_PROJECTS=""
DESCRIPTION=""
ASSUME_YES=false
NO_TMUX=false
SESSION_OVERRIDE=""

usage() {
  cat <<'EOF'
Usage: wsnew.sh <target> [options]

<target> is one of:
  - a GitHub issue URL      (https://github.com/<owner>/<repo>/issues/<n>)  -> issue mode
  - an issue shorthand      (<owner>/<repo>#<n>)                            -> issue mode
  - a GitHub repo URL       (repo root, /tree/..., /pull/<n>, etc.)         -> project mode
  - a bare repo slug        (e.g. myorg/myrepo, or just myrepo)             -> project mode

In project mode there's no issue to derive an initiative name/description from,
so pass --initiative (required) and optionally --description.

Options:
  --project NAME       Local project folder under ~/workspace/ (default: inferred from URL/path)
  --initiative NAME    Workbench initiative name, lowercase_with_underscores
                        (default: from issue title in issue mode; required in project mode)
  --description TEXT   Freeform blurb to seed the workbench README's "Why" section (project mode only)
  --ref repo1,repo2    Comma-separated reference project names to grant access to
  --yes                Skip the confirmation prompt and run immediately
  --no-tmux            Skip creating the tmux session after scaffolding
  --session NAME       Override the tmux session name (default: <project>-<initiative-hyphenated>)
  -h, --help           Show this help

Examples:
  wsnew.sh https://github.com/myorg/myrepo/issues/123
  wsnew.sh myorg/myrepo#123
  wsnew.sh https://github.com/myorg/myrepo/tree/main --initiative explore_feature
  wsnew.sh myorg/myrepo --initiative explore_feature
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project) PROJECT_OVERRIDE="$2"; shift 2 ;;
    --initiative) INITIATIVE_OVERRIDE="$2"; shift 2 ;;
    --description) DESCRIPTION="$2"; shift 2 ;;
    --ref) REF_PROJECTS="$2"; shift 2 ;;
    --yes) ASSUME_YES=true; shift ;;
    --no-tmux) NO_TMUX=true; shift ;;
    --session) SESSION_OVERRIDE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      if [[ -z "$TARGET" ]]; then TARGET="$1"; shift; else echo "Unexpected arg: $1" >&2; usage; exit 1; fi
      ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  echo "Error: missing target (issue URL, repo URL, or owner/repo slug)" >&2
  usage
  exit 1
fi

ISSUE_URL=""
ISSUE_TITLE=""
ISSUE_DESC=""

slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+|_+$//g' | cut -c1-40 | sed 's/_$//'
}

ISSUE_REPO=""
ISSUE_IID=""
if [[ "$TARGET" =~ ^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([0-9]+)/?$ ]]; then
  ISSUE_REPO="${BASH_REMATCH[1]}"; ISSUE_IID="${BASH_REMATCH[2]}"; ISSUE_URL="$TARGET"
elif [[ "$TARGET" =~ ^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#([0-9]+)$ ]]; then
  ISSUE_REPO="${BASH_REMATCH[1]}"; ISSUE_IID="${BASH_REMATCH[2]}"
  ISSUE_URL="https://github.com/$ISSUE_REPO/issues/$ISSUE_IID"
fi

if [[ -n "$ISSUE_REPO" ]]; then
  # Issue mode
  PROJECT_PATH="$ISSUE_REPO"

  PROJECT_SLUG="$(basename "$PROJECT_PATH")"
  PROJECT_NAME="${PROJECT_OVERRIDE:-$PROJECT_SLUG}"
  PROJECT_DIR="$HOME/workspace/$PROJECT_NAME"

  if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    echo "Error: $PROJECT_DIR is not a git repo. Clone it first, or pass --project NAME to point at the right local folder." >&2
    exit 1
  fi

  if ! command -v gh >/dev/null 2>&1; then
    echo "Error: the GitHub CLI (gh) is required to fetch issues. Install it and run 'gh auth login'." >&2
    exit 1
  fi

  echo "Fetching issue $PROJECT_PATH#$ISSUE_IID..."
  ISSUE_JSON="$(gh issue view "$ISSUE_IID" -R "$PROJECT_PATH" --json title,body)"
  ISSUE_TITLE="$(echo "$ISSUE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["title"])')"
  ISSUE_DESC="$(echo "$ISSUE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("body") or "")')"

  INITIATIVE_NAME="$(slugify "${INITIATIVE_OVERRIDE:-$ISSUE_TITLE}")"
else
  # Project mode: a GitHub repo URL (root, /tree/..., /blob/..., /pull/N, etc.) or a bare slug.
  if [[ "$TARGET" =~ ^https?://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(/.*)?$ ]]; then
    PROJECT_PATH="${BASH_REMATCH[1]%.git}"
  elif [[ "$TARGET" =~ ^https?:// ]]; then
    echo "Error: only github.com URLs are supported (got '$TARGET')" >&2
    exit 1
  else
    PROJECT_PATH="${TARGET%/}"
  fi

  if [[ -z "$PROJECT_PATH" ]]; then
    echo "Error: couldn't determine a repo from from '$TARGET'" >&2
    exit 1
  fi

  PROJECT_SLUG="$(basename "$PROJECT_PATH")"
  PROJECT_NAME="${PROJECT_OVERRIDE:-$PROJECT_SLUG}"
  PROJECT_DIR="$HOME/workspace/$PROJECT_NAME"

  if [[ ! -d "$PROJECT_DIR/.git" ]]; then
    echo "Error: $PROJECT_DIR is not a git repo. Clone it first, or pass --project NAME to point at the right local folder." >&2
    exit 1
  fi

  if [[ -z "$INITIATIVE_OVERRIDE" ]]; then
    echo "Error: project mode has no issue title to derive an initiative name from — pass --initiative NAME." >&2
    exit 1
  fi
  INITIATIVE_NAME="$(slugify "$INITIATIVE_OVERRIDE")"
fi

INITIATIVE_HYPHENATED="$(echo "$INITIATIVE_NAME" | tr '_' '-')"
WORKBENCH_DIR="$HOME/workspace/${PROJECT_NAME}_workspace/workbench/$INITIATIVE_NAME"
SESSION_NAME="${SESSION_OVERRIDE:-${PROJECT_NAME}-${INITIATIVE_HYPHENATED}}"

echo
echo "Project:      $PROJECT_NAME  (~/workspace/$PROJECT_NAME)"
echo "Initiative:   $INITIATIVE_NAME"
if [[ -n "$ISSUE_URL" ]]; then
  echo "Issue:        $ISSUE_TITLE"
  echo "Issue URL:    $ISSUE_URL"
else
  echo "Issue:        (none — project mode)"
  [[ -n "$DESCRIPTION" ]] && echo "Description:  $DESCRIPTION"
fi
[[ -n "$REF_PROJECTS" ]] && echo "Ref projects: $REF_PROJECTS"
echo

# Decide up front whether to create the tmux session, before doing anything.
if [[ "$NO_TMUX" == true ]]; then
  WANT_TMUX=false
elif [[ "$ASSUME_YES" == true ]]; then
  WANT_TMUX=true
else
  read -r -p "Create a tmux session at the workbench root when done (2 panes, bottom running claude --permission-mode bypassPermissions)? [Y/n] " TMUX_CONFIRM
  if [[ "$TMUX_CONFIRM" =~ ^[Nn]$ ]]; then
    WANT_TMUX=false
  else
    WANT_TMUX=true
  fi
fi

if [[ "$WANT_TMUX" == true ]]; then
  echo "Tmux session: $SESSION_NAME  (at $WORKBENCH_DIR)"
  echo
fi

if [[ "$ASSUME_YES" != true ]]; then
  read -r -p "Run scaffold-workspace headlessly with these values? [y/N] " CONFIRM
  [[ "$CONFIRM" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

REF_LINE=""
[[ -n "$REF_PROJECTS" ]] && REF_LINE="Reference projects: $REF_PROJECTS."

if [[ -n "$ISSUE_URL" ]]; then
  CONTEXT_BLOCK=$(cat <<EOF
GitHub issue: $ISSUE_URL

Issue title: $ISSUE_TITLE

Issue description:
$ISSUE_DESC

Populate the workbench README summary paragraph, the Issue link, and the "Why" section
from the issue title/description above. Leave "Work to Do" as sensible first steps inferred
from the bug/feature description.
EOF
)
else
  CONTEXT_BLOCK=$(cat <<EOF
No GitHub issue for this initiative — it's exploratory/project-driven work, not
issue-driven. Do not fabricate an issue link.
${DESCRIPTION:+
Description: $DESCRIPTION
}
Populate the workbench README's summary paragraph and "Why" section from the description
above (or leave them as sensible placeholders if no description was given). Leave "Work to
Do" as sensible first steps for exploring/working on this project. Omit the Issue link
field from the README, or mark it "N/A".
EOF
)
fi

PROMPT=$(cat <<EOF
/scaffold-workspace

Run the feature/bug initiative flow non-interactively with these values already decided —
do not ask me any clarifying questions, just proceed:

- Project name: $PROJECT_NAME
- Initiative name: $INITIATIVE_NAME
- Branch name: use the default convention from the skill
- $REF_LINE

$CONTEXT_BLOCK

If the workspace already exists, follow the "Add Initiative to Existing Workspace" path
instead of re-creating it.
EOF
)

claude -p "$PROMPT" --dangerously-skip-permissions --permission-mode bypassPermissions

if [[ "$WANT_TMUX" != true ]]; then
  exit 0
fi

if [[ ! -d "$WORKBENCH_DIR" ]]; then
  echo "Warning: expected workbench dir $WORKBENCH_DIR not found — skipping tmux setup." >&2
  exit 1
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "Warning: tmux not installed — skipping session setup." >&2
  exit 0
fi

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
  echo "Tmux session '$SESSION_NAME' already exists — reusing it."
else
  echo "Creating tmux session '$SESSION_NAME' at $WORKBENCH_DIR..."
  tmux new-session -d -s "$SESSION_NAME" -c "$WORKBENCH_DIR"
  TOP_PANE="$(tmux list-panes -t "$SESSION_NAME" -F '#{pane_id}' | head -1)"
  BOTTOM_PANE="$(tmux split-window -v -t "$SESSION_NAME" -c "$WORKBENCH_DIR" -P -F '#{pane_id}')"
  tmux send-keys -t "$BOTTOM_PANE" "claude --permission-mode bypassPermissions" C-m
  tmux select-pane -t "$TOP_PANE"
fi

if [[ -n "${TMUX:-}" ]]; then
  tmux switch-client -t "$SESSION_NAME"
else
  tmux attach-session -t "$SESSION_NAME"
fi
