#!/usr/bin/env bash
# workspace_doctor/setup.sh — verify environment and show discovered workspaces
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== workspace_doctor setup ==="
echo ""

# 1. Python
echo "Python: $(python3 --version 2>&1)"

# 2. GitHub CLI
if command -v gh >/dev/null 2>&1; then
    echo "gh: $(gh --version | head -1)"
    if gh auth status >/dev/null 2>&1; then
        echo "gh auth: ok"
    else
        echo "gh auth: NOT LOGGED IN — run: gh auth login"
    fi
else
    echo "gh: NOT FOUND — install from https://cli.github.com/ (brew install gh)"
fi

echo ""

# 3. State directory
STATE_DIR="${WORKSPACE_DOCTOR_DIR:-$HOME/.config/workspace-doctor}"
echo "State directory: $STATE_DIR"

echo ""

# 4. Workspace discovery
echo "Discovered workspaces:"
python3 "$SCRIPT_DIR/workspace-scan.py" --list-workspaces

echo ""
echo "Setup complete. Run:"
echo "  python3 $SCRIPT_DIR/workspace-scan.py"
echo "  python3 $SCRIPT_DIR/github-check.py"
echo "  # then in Claude: /cleanup-workspace"
