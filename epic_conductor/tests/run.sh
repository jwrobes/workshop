#!/usr/bin/env bash
# Tests for epic_conductor. No network: tmux, gh and wsnew are stubs from tests/stubs.
# usage: tests/run.sh
set -uo pipefail
T="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$T")"
pass=0; fail=0
ok()   { pass=$((pass+1)); echo "  ok   $1"; }
bad()  { fail=$((fail+1)); echo "  FAIL $1${2:+: $2}"; }
eq()   { [ "$2" = "$3" ] && ok "$1" || bad "$1" "want [$3] got [$2]"; }
has()  { case "$2" in *"$3"*) ok "$1" ;; *) bad "$1" "[$3] not in [$2]" ;; esac; }
hasnt(){ case "$2" in *"$3"*) bad "$1" "[$3] unexpectedly in [$2]" ;; *) ok "$1" ;; esac; }

new_env() {
  TMP="$(mktemp -d)"
  export HOME="$TMP/home"; mkdir -p "$HOME"
  export FAKE_TMUX_DIR="$TMP/tmux" FAKE_GH_DIR="$TMP/gh"; mkdir -p "$FAKE_TMUX_DIR" "$FAKE_GH_DIR"
  export PATH="$T/stubs:$ROOT/bin:$BASE_PATH"
  unset EPIC_CONDUCTOR_HOME EPIC_MAX_ATTEMPTS EPIC_WSNEW
  LOG="$HOME/.epic-conductor/e1/UPDATES.log"
}
BASE_PATH="$PATH"
ago() { date -u -v-"$1"M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "$1 minutes ago" +%Y-%m-%dT%H:%M:%SZ; }
tab() { local IFS=$'\t'; echo "$*"; }

echo "# url parsing"
new_env
source "$ROOT/bin/_common.sh"
parse_issue "https://github.com/acme/widgets/issues/42"
eq "url owner" "$OWNER" acme; eq "url repo" "$REPO" widgets; eq "url iid" "$IID" 42
eq "url canonical" "$ISSUE_URL" "https://github.com/acme/widgets/issues/42"
parse_issue "acme/wid.gets-x#7"
eq "short repo" "$REPO" "wid.gets-x"; eq "short iid" "$IID" 7; eq "short slug" "$REPO_SLUG" "acme/wid.gets-x"
parse_issue "https://github.com/acme/widgets/issues/9/?x=1#c"; eq "url with trailing junk" "$IID" 9
parse_issue "https://example.com/g/p/-/issues/3" 2>/dev/null; eq "non-github url rejected" "$?" 1
parse_issue "https://github.com/acme/widgets/pull/3" 2>/dev/null; eq "pr url rejected" "$?" 1
parse_issue "acme/widgets" 2>/dev/null; eq "bare slug rejected" "$?" 1
validate_epic 'good-name_1.0'; eq "epic ok" "$?" 0
validate_epic 'bad|name' 2>/dev/null; eq "epic with | rejected" "$?" 1
validate_epic '../x' 2>/dev/null; eq "epic path rejected" "$?" 1

echo "# session naming"
eq "session name" "$(session_name my-epic widgets 42)" "epic-my-epic-widgets-42"
eq "session name sanitized" "$(session_name e1 wid.gets 5)" "epic-e1-wid-gets-5"
eq "workbench dir" "$(workbench_dir widgets 42)" "$HOME/workspace/widgets_workspace/workbench/issue_42"

echo "# attempt counting"
new_env; source "$ROOT/bin/_common.sh"
eq "no log" "$(attempt_number e1 widgets/1)" 1
mkdir -p "$(dirname "$LOG")"
{ tab "$(ago 90)" widgets/1 STARTED "attempt 1"; tab "$(ago 80)" widgets/2 STARTED "attempt 1"
  tab "$(ago 70)" widgets/1 PHASE "x"; tab "$(ago 60)" widgets/1 STARTED "attempt 2"; } > "$LOG"
eq "two starts -> 3" "$(attempt_number e1 widgets/1)" 3
eq "one start -> 2" "$(attempt_number e1 widgets/2)" 2
eq "other issue untouched" "$(attempt_number e1 widgets/9)" 1
eq "widgets/1 vs widgets/10 not confused" "$(attempt_number e1 widgets/10)" 1

echo "# epic-log"
new_env
epic-log e1 widgets/1 PHASE $'two\nlines\tand tab'
eq "one line written" "$(wc -l < "$LOG" | tr -d ' ')" 1
eq "fields" "$(awk -F'\t' '{print NF" "$2" "$3" "$4}' "$LOG")" "4 widgets/1 PHASE two lines and tab"
epic-log e1 widgets/1 BOGUS x 2>/dev/null; eq "unknown event rejected" "$?" 2
EPIC_CONDUCTOR_HOME="$TMP/alt" epic-log e1 widgets/1 DONE x; [ -f "$TMP/alt/e1/UPDATES.log" ] && ok "EPIC_CONDUCTOR_HOME honoured" || bad "EPIC_CONDUCTOR_HOME honoured"

echo "# epic-status"
new_env
mkdir -p "$(dirname "$LOG")"
{ tab "$(ago 50)" widgets/1 STARTED "attempt 1"; tab "$(ago 40)" widgets/1 DONE "https://x"
  tab "$(ago 31)" widgets/2 STARTED "attempt 1"; tab "$(ago 30)" widgets/2 PHASE "enrich PASS"
  tab "$(ago 20)" widgets/3 STARTED "attempt 1"; tab "$(ago 15)" widgets/3 BLOCKED "open deps"
  tab "$(ago 10)" widgets/4 STARTED "attempt 1, LIVE"
  tab "$(ago 9)" widgets/5 STARTED "attempt 1, LIVE"
  tab "$(ago 8)" widgets/6 STARTED "attempt 1"; tab "$(ago 7)" widgets/6 STARTED "attempt 2"; } > "$LOG"
echo epic-e1-widgets-2 > "$FAKE_TMUX_DIR/sessions"
mkdir -p "$HOME/.epic-conductor/e1/live"
printf 'mysess:2' > "$HOME/.epic-conductor/e1/live/widgets-4"; echo mysess:2 > "$FAKE_TMUX_DIR/panes"
printf 'gone:9' > "$HOME/.epic-conductor/e1/live/widgets-5"
out="$(epic-status e1)"
row() { printf '%s\n' "$out" | awk -v k="$1" '$1==k'; }
has "header" "$out" "ALIVE"
r="$(row widgets/1)"; has "done event" "$r" " DONE "; has "done not alive" "$r" " no "
r="$(row widgets/2)"; has "alive session" "$r" " yes "; has "alive age ~30" "$r" " 30 "; has "alive message" "$r" "enrich PASS"
r="$(row widgets/3)"; has "blocked event" "$r" " BLOCKED "
r="$(row widgets/4)"; has "live" "$r" " live "
r="$(row widgets/5)"; has "live-gone" "$r" " live-gone "
r="$(row widgets/6)"; has "attempt count 2" "$(echo "$r" | awk '{print $5}')" 2
eq "one row per issue" "$(printf '%s\n' "$out" | tail -n +2 | wc -l | tr -d ' ')" 6
eq "no log" "$(epic-status nope)" "no log for epic 'nope'"

echo "# epic-check (stub gh)"
new_env
printf 'OPEN\tready,orchestrator-blocked\n' > "$FAKE_GH_DIR/issue_view"
printf '#3\n#4\n' > "$FAKE_GH_DIR/blockers"
printf 'https://github.com/acme/widgets/pull/50\tOPEN\ttrue\n' > "$FAKE_GH_DIR/pr_list"
printf 'pass,fail\n' > "$FAKE_GH_DIR/checks"
out="$(epic-check acme/widgets#42)"
has "state" "$out" "state: OPEN"; has "blocked label" "$out" "orchestrator-blocked: yes"
has "blockers" "$out" "open-blockers: #3,#4"; has "draft pr" "$out" "pr-state: draft"
has "checks fail" "$out" "checks: fail"; has "pr url" "$out" "pr: https://github.com/acme/widgets/pull/50"
has "gh used -R" "$(cat "$FAKE_GH_DIR/calls")" "-R acme/widgets"
printf 'OPEN\tready\n' > "$FAKE_GH_DIR/issue_view"; : > "$FAKE_GH_DIR/blockers"
printf 'https://github.com/acme/widgets/pull/50\tOPEN\tfalse\n' > "$FAKE_GH_DIR/pr_list"; printf 'pass\n' > "$FAKE_GH_DIR/checks"
out="$(epic-check https://github.com/acme/widgets/issues/42)"
has "no label" "$out" "orchestrator-blocked: no"; has "no blockers" "$out" "open-blockers: none"
has "ready pr" "$out" "pr-state: ready"; has "checks pass" "$out" "checks: pass"
: > "$FAKE_GH_DIR/pr_list"; touch "$FAKE_GH_DIR/blockers.fail"
out="$(epic-check acme/widgets#42)"
has "no pr" "$out" "pr-state: none"; has "unknown blockers" "$out" "open-blockers: unknown"

echo "# epic-spawn / adopt / kill"
new_env
out="$(epic-spawn e1 acme/widgets#42 --dry-run 2>&1)"
has "dry wsnew" "$out" "DRY: wsnew --yes --no-tmux https://github.com/acme/widgets/issues/42 --initiative issue_42"
has "dry tmux" "$out" "DRY: tmux new-session -d -s epic-e1-widgets-42"
has "dry bypass" "$out" "--permission-mode bypassPermissions"
[ -f "$LOG" ] && bad "dry run writes no log" || ok "dry run writes no log"
out="$(epic-spawn e1 https://github.com/acme/widgets/issues/42 2>&1)"; has "spawned" "$out" "spawned epic-e1-widgets-42 (attempt 1)"
has "wsnew called" "$(cat "$FAKE_TMUX_DIR/wsnew_calls")" "--initiative issue_42"
has "log STARTED" "$(cat "$LOG")" "STARTED"
p="$HOME/.epic-conductor/e1/prompts/widgets-42-attempt1.md"
has "prompt rendered" "$(cat "$p")" "https://github.com/acme/widgets/issues/42"
hasnt "no unfilled placeholders" "$(cat "$p")" "{{"
has "prompt names skill" "$(cat "$p")" "full-path-github"
has "prompt log path" "$(cat "$p")" "$ROOT/bin/epic-log e1 widgets/42"
out="$(epic-spawn e1 acme/widgets#42 2>&1)"; eq "second worker refused" "$?" 1
epic-kill e1 acme/widgets#42 "stuck"; eq "kill ok" "$?" 0
has "KILLED logged" "$(cat "$LOG")" "KILLED"
epic-spawn e1 acme/widgets#42 >/dev/null; epic-kill e1 acme/widgets#42 x >/dev/null
epic-spawn e1 acme/widgets#42 >/dev/null; epic-kill e1 acme/widgets#42 x >/dev/null
out="$(epic-spawn e1 acme/widgets#42 2>&1)"; eq "4th attempt refused" "$?" 4
has "limit message" "$out" "respawn limit"
epic-spawn e1 acme/widgets#42 --force >/dev/null 2>&1; eq "--force overrides" "$?" 0
echo brief > "$TMP/b.md"; epic-spawn e1 acme/widgets#7 --brief "$TMP/b.md" >/dev/null
has "brief appended" "$(cat "$HOME/.epic-conductor/e1/prompts/widgets-7-attempt1.md")" "brief"
epic-spawn e1 acme/widgets#8 --live >/dev/null
[ -f "$HOME/.epic-conductor/e1/live/widgets-8" ] && ok "live registered" || bad "live registered"
hasnt "live has no bypass flag" "$(tail -1 "$FAKE_TMUX_DIR/calls")" "bypassPermissions"
has "live prompt" "$(cat "$HOME/.epic-conductor/e1/prompts/widgets-8-attempt1.md")" "LIVE worker"
epic-kill e1 acme/widgets#8 nope 2>/dev/null; eq "kill refuses live" "$?" 3
echo mysess:3 > "$FAKE_TMUX_DIR/panes"
out="$(epic-adopt e1 acme/widgets#9 mysess:3)"; has "adopt prints cmd" "$out" "claude \"\$(cat '"
has "adopt logged" "$(cat "$LOG")" "adopted mysess:3"
epic-adopt e1 acme/widgets#9 mysess:3 2>/dev/null; eq "double adopt refused" "$?" 1
epic-adopt e1 acme/widgets#10 nowhere:1 2>/dev/null; eq "bad target refused" "$?" 1
epic-spawn 'bad|e' acme/widgets#1 2>/dev/null; eq "bad epic refused" "$?" 1

echo "# symlinked invocation"
new_env; mkdir "$TMP/bin"; ln -s "$ROOT/bin/epic-status" "$TMP/bin/epic-status"; ln -s "$ROOT/bin/epic-log" "$TMP/bin/epic-log"
PATH="$TMP/bin:$PATH" epic-log e1 widgets/1 PHASE x && PATH="$TMP/bin:$PATH" epic-status e1 >/dev/null; eq "works via symlink" "$?" 0

echo "# setup.sh"
new_env
export BIN_DIR="$TMP/lb" SKILLS_DIR="$TMP/sk"
out="$("$ROOT/setup.sh" --dry-run 2>&1)"; has "dry-run says DRY" "$out" "DRY link"
[ -e "$BIN_DIR" ] && bad "dry-run writes nothing" || ok "dry-run writes nothing"
"$ROOT/setup.sh" >/dev/null 2>&1
eq "bin link" "$(readlink "$BIN_DIR/epic-spawn")" "$ROOT/bin/epic-spawn"
eq "skill link" "$(readlink "$SKILLS_DIR/conducting-epics")" "$ROOT/skills/conducting-epics"
out="$("$ROOT/setup.sh" 2>&1)"; has "idempotent" "$out" "ok       $BIN_DIR/epic-spawn"; hasnt "no relink" "$out" "linked   "
unset BIN_DIR SKILLS_DIR

echo
echo "passed: $pass  failed: $fail"
[ "$fail" -eq 0 ]
