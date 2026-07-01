#!/usr/bin/env python3
"""Work-track consolidation (Phase 5).

A single track of work has artifacts scattered across the workflow — a plan card,
issues, spec-PRs, a merged impl PR, a worktree — that often DON'T share a clean
slug, so deterministic matching (Phase 1/4a) can't unify them. This module groups
the *loose* cards into work-tracks using an LLM, then lets manual UI corrections
override the grouping.

Design (no server; portable):
  * The LLM call shells out to the `claude` CLI in print mode (`claude -p`), which
    reuses the user's existing Claude Code auth — no API key to manage. It is a
    SEPARATE, on-demand step (collector runs `--consolidate`), cached to
    `tracks.json` so the normal `./run.sh` stays fast and offline.
  * `track-overrides.json` (downloaded from the dashboard UI) holds user
    corrections. Overrides ALWAYS win over the LLM grouping and are applied
    deterministically every run — so a wrong grouping you fixed stays fixed, and
    the whole thing is reversible (edit/delete the file to undo).

Public entry points:
  * run_llm_consolidation(loose_cards) -> tracks list           (the LLM pass)
  * apply_overrides(tracks, overrides) -> tracks list           (corrections win)
  * load_tracks(out_dir) / save_tracks(out_dir, tracks)         (cache I/O)
  * attach_tracks_to_cards(cards, tracks)                       (stamp card.track)
"""

import json
import re
import subprocess

CLAUDE_CLI = "claude"
TRACKS_FILE = "tracks.json"
OVERRIDES_FILE = "track-overrides.json"
RUNLOG_FILE = "llm-runlog.json"

# Card sources the LLM should try to group into tracks: not-yet-unified plan
# fragments (remote-only, workbench-only) AND shipped-but-unmatched merged PRs
# (merged-unmatched) — the latter is how #115/#117/#119 rejoin their feature
# instead of vanishing. A card already on a real plan (source local) is its own
# track anchor and is left alone.
LOOSE_SOURCES = ("remote-only", "workbench-only", "merged-unmatched")


def loose_cards(cards):
    """The cards the LLM should try to group: remote-only + workbench-only. A
    card already attached to a product/repo plan (source local) is its own
    track anchor and is left alone."""
    return [c for c in cards if c.get("source") in LOOSE_SOURCES]


def _card_brief(c):
    """A compact, stable view of a card for the LLM — id + the signals that
    indicate which track it belongs to. Kept small so grouping is cheap."""
    gh = c.get("github") or {}
    return {
        "id": _card_id(c),
        "title": (c.get("title") or c.get("slug") or "")[:120],
        "slug": c.get("slug"),
        "repo": c.get("repo"),
        "product": c.get("product"),
        "pr": gh.get("number"),
        # State helps the LLM group AND lets the UI show a track's reality
        # (merged code vs open work). Branch names are often useless (auto-gen),
        # so the title is the real grouping signal.
        "state": "merged" if c.get("shipped") else (gh.get("state") or "").lower(),
    }


def _card_id(c):
    """A stable identifier for a card across runs: prefer the GitHub ref
    (repo#number) since slugs/titles drift; fall back to repo/slug. A product-
    level PR has repo=None — use product#number (e.g. magic-me#113), NOT the
    ambiguous ?#113, so its id is stable and doesn't collide across products."""
    gh = c.get("github") or {}
    scope = c.get("repo") or c.get("product") or "?"
    if gh.get("number") is not None:
        return f"{scope}#{gh['number']}"
    return f"{scope}/{c.get('slug') or ''}"


CONSOLIDATE_PROMPT = """\
You group scattered software work artifacts that belong to the SAME feature/effort
into work-tracks. A "track" is ONE feature whose artifacts (plan, issues, spec-PRs,
merged impl-PRs) are scattered with diverging titles (branch names are often
auto-generated and useless — group by TITLE meaning).

Rules:
- ONLY return tracks that group 2+ items that clearly belong to the same feature.
- DO NOT return singletons. An item with no sibling is omitted entirely.
- Be CONSERVATIVE: when unsure two items are the same effort, leave them apart.
  Wrongly merging unrelated work is worse than leaving it ungrouped.
- Prefer a short kebab-case track name (e.g. "communications-hub", "email-triage").
- Return ONLY compact JSON, no prose, no markdown fence:
  {"tracks":[{"name":"<kebab>","members":["<id>","<id>",...]}]}

Items:
%s
"""


def run_llm_consolidation(cards, runner=None):
    """Group loose cards into tracks via the `claude` CLI. `runner` is an
    injectable callable(prompt)->str for testing (defaults to the real CLI).
    Returns a list of {name, members:[card_id]} dicts. On any failure (CLI
    missing, bad JSON) returns [] — consolidation is best-effort, never fatal."""
    items = [_card_brief(c) for c in loose_cards(cards)]
    if not items:
        return []
    prompt = CONSOLIDATE_PROMPT % json.dumps(items, indent=0)
    run = runner or _claude_cli
    try:
        raw = run(prompt)
        data = _parse_json(raw)
    except (OSError, ValueError):
        return []
    tracks = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(tracks, list):
        return []
    # Keep only well-formed tracks referencing known ids.
    known = {it["id"] for it in items}
    out = []
    for t in tracks:
        if not isinstance(t, dict):
            continue
        members = [m for m in (t.get("members") or []) if m in known]
        name = (t.get("name") or "").strip()
        # A track must group 2+ real items — singletons aren't consolidations and
        # only add board noise (the 77-track wall was 37 singletons). Drop them.
        if name and len(members) >= 2:
            out.append({"name": name, "members": members, "source": "llm"})
    return out


def _claude_cli(prompt):
    """Invoke the claude CLI in print mode. Raises OSError if unavailable."""
    r = subprocess.run([CLAUDE_CLI, "-p"], input=prompt,
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise OSError(f"claude CLI failed: {r.stderr[:200]}")
    return r.stdout


def _parse_json(raw):
    """Parse the JSON object out of an LLM response that may have leading prose,
    a ```json fence, prose-THEN-fence, or trailing text. Strategy: if there's a
    fenced block, take its contents; otherwise take the whole string. Then grab
    the outermost {...}. (The CLI sometimes prefixes 'Here is the output:' before
    the fence — earlier this silently produced 0 tracks.)"""
    s = (raw or "").strip()
    # Prefer a fenced block anywhere in the response.
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    # Grab the outermost JSON object (drops any surrounding prose).
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        s = s[i:j + 1]
    return json.loads(s)


# ---------------------------------------------------------------------------
# PASS 1 — TRIAGE (fleet/product altitude). Sweep the Ungrouped artifacts and,
# per item, propose ONE of: attach to an existing track / create a new track /
# archive (stale). Each carries a confidence (high/medium/low).
#
# The trust rule (decided with Jonathan):
#   * HIGH-confidence ATTACH auto-applies — written into track-overrides.json as
#     a real reassign marked _source:'llm-triage' (visible, editable, undoable).
#   * medium/low attaches, and ALL create/archive proposals (regardless of
#     confidence — creating/removing structure is higher-stakes), are
#     SUGGESTIONS the human accepts/dismisses in the UI.
# Best-effort + offline-safe: a failed pass returns empty (no auto changes),
# never fatal. The runner is injectable for offline/deterministic tests.
# ---------------------------------------------------------------------------

TRIAGE_PROMPT = """\
You are triaging SCATTERED software work artifacts (loose PRs/issues that belong
to no work-track yet) against the EXISTING work-tracks. For EACH ungrouped item,
propose exactly ONE action:
- "attach": it clearly belongs to an existing track (match by TITLE/BODY meaning
  — branch names are often auto-generated and useless). Give the track name.
- "create": it (with 1+ other ungrouped items) clearly forms a NEW distinct
  effort not covered by any existing track. Give a short kebab-case track name.
  Be CONSERVATIVE — only when items clearly pair; never a singleton track.
- "archive": it is stale / superseded / not live and should be decluttered.

Give each a "confidence": "high" | "medium" | "low", and a one-line "reason".
Prefer "attach" to an existing track over "create". When unsure, use lower
confidence — do not assert a shaky match as high.

Return ONLY compact JSON, no prose, no markdown fence:
  {"proposals":[{"id":"<id>","action":"attach|create|archive",
    "track":"<name-or-null>","confidence":"high|medium|low","reason":"<why>"}]}

EXISTING TRACKS (name -> member titles):
%s

UNGROUPED ITEMS to triage:
%s
"""


def _triage_track_brief(track, cards):
    """Compact view of an existing track for the triage prompt: name + the
    member TITLES (the real matching signal), so the LLM can attach by meaning."""
    by_id = {_card_id(c): c for c in cards}
    titles = []
    for m in (track.get("members") or []):
        c = by_id.get(m)
        if c is not None:
            gh = c.get("github") or {}
            titles.append((gh.get("title") or c.get("title") or m)[:80])
    return {"name": track.get("name"), "members": titles}


def _triage_item_brief(c):
    """Compact view of an ungrouped artifact — id + title + a body snippet, the
    'what is this trying to do' signal that makes fuzzy attach tractable."""
    gh = c.get("github") or {}
    body = (gh.get("body") or c.get("body") or "").strip()
    return {
        "id": _card_id(c),
        "title": (gh.get("title") or c.get("title") or c.get("slug") or "")[:120],
        "repo": c.get("repo"),
        "product": c.get("product"),
        "state": "merged" if c.get("shipped") else (gh.get("state") or "").lower(),
        "body": body[:400],
    }


def run_triage(ungrouped, tracks, runner=None, cards=None):
    """Triage the Ungrouped artifacts against the existing tracks via the
    `claude` CLI. Returns a dict:
      {"proposals":[...raw...],
       "auto":[{id,track,confidence,reason}],        # high-conf attaches -> apply
       "suggestions":[{id,action,track,confidence,reason}]}  # human resolves

    `ungrouped` are the loose forge-backed cards (from ungroupedCards). `tracks`
    are the existing multi-member tracks (for attach matching). `cards` is the
    full card list used to resolve member titles (defaults to `ungrouped`).
    `runner` is an injectable callable(prompt)->str for offline tests.

    Validation is strict: an attach must target a KNOWN track and a KNOWN
    ungrouped id, or it's dropped (never corrupt membership on a hallucination).
    On ANY failure (CLI missing, bad JSON) returns empty auto+suggestions."""
    empty = {"proposals": [], "auto": [], "suggestions": []}
    if not ungrouped:
        return empty
    all_cards = cards if cards is not None else ungrouped
    track_briefs = [_triage_track_brief(t, all_cards)
                    for t in tracks if len(t.get("members") or []) >= 2]
    item_briefs = [_triage_item_brief(c) for c in ungrouped]
    prompt = TRIAGE_PROMPT % (json.dumps(track_briefs, indent=0),
                              json.dumps(item_briefs, indent=0))
    run = runner or _claude_cli
    try:
        data = _parse_json(run(prompt))
    except (OSError, ValueError):
        return empty
    proposals = data.get("proposals") if isinstance(data, dict) else None
    if not isinstance(proposals, list):
        return empty

    known_ids = {b["id"] for b in item_briefs}
    known_tracks = {b["name"] for b in track_briefs}
    auto, suggestions, kept = [], [], []
    seen_ids = set()                      # one proposal per artifact (first wins)
    for p in proposals:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        action = (p.get("action") or "").lower()
        conf = (p.get("confidence") or "").lower()
        if pid not in known_ids or action not in ("attach", "create", "archive"):
            continue                      # hallucinated id/action -> drop
        if pid in seen_ids:
            continue                      # dup proposal for one id -> ignore
        seen_ids.add(pid)
        track = (p.get("track") or "").strip() or None
        reason = (p.get("reason") or "").strip()
        item = {"id": pid, "action": action, "track": track,
                "confidence": conf, "reason": reason}
        if action == "attach" and track not in known_tracks:
            continue                      # attach must target a real track
        kept.append(item)
        # High-confidence ATTACH is the ONLY auto case. create/archive are
        # always suggestions (higher stakes); medium/low attaches too.
        if action == "attach" and conf == "high":
            auto.append({"id": pid, "track": track, "confidence": conf,
                         "reason": reason})
        else:
            suggestions.append(item)
    return {"proposals": kept, "auto": auto, "suggestions": suggestions}


def apply_triage_auto(overrides, auto):
    """Fold high-confidence triage attaches INTO the overrides dict as real
    `reassign` entries, marked `_source[id]='llm-triage'` so the UI can show them
    as auto-applied (vs a human reassign). Returns a NEW overrides dict.

    A HUMAN reassign already present for that id WINS — the human's correction is
    never overwritten by the LLM (the file is the source of truth Jonathan
    trusts). Idempotent: re-running with the same auto list is a no-op."""
    out = dict(overrides or {})
    reassign = dict(out.get("reassign") or {})
    source = dict(out.get("_source") or {})
    for a in auto or []:
        cid, track = a.get("id"), a.get("track")
        if not cid or not track:
            continue
        # Only apply if the human hasn't already reassigned this card by hand.
        if cid in reassign and source.get(cid) != "llm-triage":
            continue
        reassign[cid] = track
        source[cid] = "llm-triage"
    out["reassign"] = reassign
    out["_source"] = source
    return out


def apply_overrides(tracks, overrides):
    """Apply user corrections (from track-overrides.json) OVER the LLM tracks.
    Overrides win. Supported corrections (all by stable card id):
      - reassign: {card_id: track_name}  -> move a card to a (new or existing) track
      - split:    [card_id, ...]         -> force each into its own singleton track
      - archive:  [card_id, ...]         -> soft-hide (handled by stamp_archived,
        not here — archive doesn't change track grouping)
    Returns a new tracks list. Deterministic; reversible by editing the file."""
    overrides = overrides or {}
    reassign = overrides.get("reassign") or {}
    split = set(overrides.get("split") or [])

    # Start from a deep-ish copy of LLM tracks as {name: set(members)}.
    by_name = {}
    for t in tracks:
        by_name.setdefault(t["name"], set()).update(t.get("members") or [])

    # 1. Remove any reassigned/split card from wherever the LLM put it.
    moved = set(reassign) | split
    for name in list(by_name):
        by_name[name] -= moved
        if not by_name[name]:
            del by_name[name]

    # 2. Reassign: put each card in its target track (created if needed).
    for card_id, target in reassign.items():
        if not target:
            continue
        by_name.setdefault(target, set()).add(card_id)

    # 3. Split: each becomes its own singleton track named for the card.
    for card_id in split:
        by_name.setdefault(f"track:{card_id}", set()).add(card_id)

    out = []
    for name, members in by_name.items():
        is_override = name in set(reassign.values()) or any(
            m in moved for m in members)
        out.append({"name": name, "members": sorted(members),
                    "source": "override" if is_override else "llm"})
    return sorted(out, key=lambda t: t["name"])


def _norm_slug(s):
    """Normalize a slug/branch/name for matching: lowercase, unify -/_ /space,
    collapse repeats. So 'Communications_Hub  Morning' ~ 'communications-hub-
    morning'."""
    s = re.sub(r"[\s_]+", "-", (s or "").strip().lower())
    return re.sub(r"-+", "-", s).strip("-")


def _branch_slug(branch):
    """The feature slug of a build-<slug> branch, stripped of common prefixes.
    'build-communications-hub-morning-briefing' -> 'communications-hub-morning-
    briefing'. Auto-generated branches (claude/…) yield the raw tail (rarely a
    track name), so they won't false-match."""
    if not branch:
        return ""
    tail = branch.split("/")[-1]
    for pref in ("build-spec-", "build-", "spec-"):
        if tail.lower().startswith(pref):
            tail = tail[len(pref):]
            break
    return _norm_slug(tail)


def _closes_numbers(body):
    """PR/issue numbers this card closes/fixes/resolves, from its body:
    'closes #112', 'fixes #90', 'resolves #7'. Returns a set of ints."""
    if not body:
        return set()
    return {int(n) for n in re.findall(
        r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", body, re.I)}


def attach_strays_to_tracks(cards, tracks):
    """DETERMINISTIC stray-attach (no LLM): a LOOSE card that is obviously part
    of an existing track — but wasn't grouped (often a product-level PR the LLM
    pass never saw) — is added to that track's members. Two signals, per
    TRACK-MODEL's deterministic-join rule:
      1. its build-<slug> branch normalizes to the track NAME, OR
      2. its body 'closes/fixes #N' where #N is a member of that track.
    Mutates `tracks` in place (extends members) and returns it. Idempotent:
    a card already in a track is skipped; overrides still win (they ran first).
    """
    multi = [t for t in tracks if len(t.get("members") or []) >= 2]
    if not multi:
        return tracks
    already = {m for t in multi for m in (t.get("members") or [])}
    # Index tracks by normalized name, and each member number -> its track.
    by_name = {_norm_slug(t["name"]): t for t in multi}
    num_to_track = {}
    for t in multi:
        for m in (t.get("members") or []):
            mo = re.search(r"#(\d+)$", str(m))
            if mo:
                num_to_track[int(mo.group(1))] = t
    for c in cards:
        cid = _card_id(c)
        if cid in already or c.get("track"):
            continue
        gh = c.get("github") or {}
        target = None
        # 1. build-<slug> branch matches a track name.
        bslug = _branch_slug(gh.get("branch") or c.get("branch"))
        if bslug and bslug in by_name:
            target = by_name[bslug]
        # 2. 'closes #N' where #N is a track member (same repo/product scope).
        if target is None:
            body = gh.get("body") or c.get("body") or ""
            for n in _closes_numbers(body):
                cand = num_to_track.get(n)
                if cand is not None:
                    target = cand
                    break
        if target is not None:
            target.setdefault("members", []).append(cid)
            already.add(cid)
    return tracks


def attach_tracks_to_cards(cards, tracks):
    """Stamp each card with its track name (card['track']) so the UI can render
    unified work-tracks. Cards not in any multi-member track are left untracked
    (a singleton isn't a 'consolidation' worth showing as a group).

    IDEMPOTENT across rebuilds: clears any prior `track` stamp first, then
    re-derives from `tracks`. This matters because the collector rebuilds tracks
    twice when a triage auto-attach fires (build → auto-attach → REBUILD). Build
    2 reloads tracks.json fresh (no deterministic strays), and
    `attach_strays_to_tracks` skips cards already stamped — so if we didn't clear
    here, a deterministically-attached stray (e.g. #113) would keep a dangling
    stamp yet be dropped from the rebuilt track's members. Clearing makes each
    build recompute membership from scratch, keeping strays attached."""
    member_to_track = {}
    for t in tracks:
        if len(t.get("members") or []) >= 2:  # only real groupings
            for m in t["members"]:
                member_to_track[m] = t["name"]
    for c in cards:
        tn = member_to_track.get(_card_id(c))
        c["track"] = tn if tn else None
    return cards


# ---------------------------------------------------------------------------
# Deterministic strand facts (Phase 1). No LLM, no judgment — pure code derived
# from labels/title/branch/state, so it is always shown and never wrong. The
# unified card's layer 1 (see UNIFIED-CARD-MODEL.md). The LLM verdict (layer 2)
# is Phase 3+4 and lives elsewhere.
# ---------------------------------------------------------------------------

# Pipeline stage keys — MUST match template.html STAGES so the strand map and
# the pipeline map speak the same language.
_STAGE_SPEC = "spec"
_STAGE_REVIEW = "review"
_STAGE_SHIPPED = "shipped"


def _is_build_spec_card(card):
    """A build-spec strand: build-spec label, or a spec-y title. Mirrors the
    collector's _is_build_spec but reads off the card's github object."""
    gh = card.get("github") or {}
    labels = {(l or "").lower() for l in (gh.get("labels") or [])}
    if "build-spec" in labels or "build_spec" in labels:
        return True
    title = gh.get("title") or card.get("title") or ""
    if re.search(r"\bbuild[\s_-]?spec\b", title, re.I):
        return True
    # "Specs: Stage 2 ..." — a PR whose job is to land the spec, not the impl.
    return bool(re.match(r"\s*specs?\b", title, re.I))


def strand_role(card):
    """What kind of artifact this member is (deterministic):
    spec-PR | impl-PR | issue | plan | worktree."""
    if card.get("kind") == "worktree":
        return "worktree"
    gh = card.get("github") or {}
    kind = gh.get("kind")
    if kind == "issue":
        return "issue"
    if kind == "pr":
        return "spec-PR" if _is_build_spec_card(card) else "impl-PR"
    # No github object -> a local plan card is the anchor.
    return "plan"


def strand_state(card):
    """The member's state (deterministic): merged | open | closed | dirty | stale.
    Worktrees carry local git state; PRs/issues carry forge state."""
    if card.get("kind") == "worktree":
        flags = card.get("flags") or []
        if (card.get("dirty_files") or 0) > 0:
            return "dirty"
        if "stale" in flags:
            return "stale"
        return "clean"
    if card.get("shipped"):
        return "merged"
    gh = card.get("github") or {}
    st = (gh.get("state") or "").upper()
    if st == "MERGED":
        return "merged"
    if st == "CLOSED":
        return "closed"
    if st == "OPEN":
        return "open"
    # A local plan card with no forge state: reflect its column.
    status = (card.get("status") or "").lower()
    if status in ("completed", "done", "shipped"):
        return "merged"
    return "open"


def strand_source(card):
    """Best-effort deterministic origin: bosque | web | dev | —.

    What's actually detectable (documented honestly, per the plan):
      * branch prefix, when present — `claude/...` (Claude-on-web),
        `build-<slug>` / a `bosque/...` prefix (Bosque cloud agent),
        a plain local branch (dev machine);
      * a `feat(bosque):`-style title marker as a fallback when branch is absent.
    When neither signal exists we return '—' rather than guessing — the card
    data does not always carry the branch (issues never do; older cached runs
    predate branch plumbing)."""
    gh = card.get("github") or {}
    branch = (gh.get("branch") or "").lower()
    if branch:
        if branch.startswith("claude/") or "claude.ai" in branch:
            return "web"
        if branch.startswith("bosque/") or branch.startswith("build-spec"):
            return "bosque"
        if branch.startswith("build-"):
            return "dev"
    title = (gh.get("title") or card.get("title") or "").lower()
    if re.search(r"\bbosque\b", title):
        return "bosque"
    if card.get("kind") == "worktree":
        return "dev"  # a worktree is a local checkout on the dev machine
    return "—"


def strand_stage(card):
    """Pipeline stage of the member (deterministic), matching template STAGES.
    merged/shipped -> shipped; open PR -> in-review; open issue/spec -> spec'd."""
    if strand_state(card) in ("merged",):
        return _STAGE_SHIPPED
    gh = card.get("github") or {}
    if gh.get("kind") == "pr" and (gh.get("state") or "").upper() == "OPEN":
        return _STAGE_REVIEW
    return _STAGE_SPEC


def strand_activity(card):
    """How 'live' a strand is, for deciding a track's board column:
      - 'active':  work is in flight — an open PR (spec or impl, sitting
        in-review), a dirty/ahead worktree, or a plan card marked active.
      - 'backlog': queued but not started — an open ISSUE (spec'd, nobody's
        picked it up), or a plan card marked backlog.
      - 'done':    merged / closed / shipped — nothing left on this strand.
    The point (Jonathan's rule): a track is only truly Completed when ALL its
    strands are done; if anything's active it's Active; if the rest are just
    backlog it's Backlog. (Whether an active strand is REALLY needed — vs a
    duplicate/supplanted loose end to clip — is a fuzzy call left to the LLM.)"""
    role = strand_role(card)
    state = strand_state(card)
    if state in ("merged", "closed"):
        return "done"
    if role == "worktree":
        return "active" if state in ("dirty", "ahead") else "done"
    if role == "issue":
        return "backlog" if state == "open" else "done"
    if role in ("spec-PR", "impl-PR"):
        return "active" if state == "open" else "done"
    # A local plan card: reflect its column.
    status = (card.get("status") or "").lower()
    if status == "backlog":
        return "backlog"
    if status in ("completed", "done", "shipped"):
        return "done"
    return "active"


def strand_detail(card):
    """The full deterministic fact-row for one member — plus every helpful field
    we can surface to describe what the strand is TRYING TO DO (body, labels,
    dates, branch). The strand detail panel renders these; the Phase-3 LLM reads
    the same block."""
    gh = card.get("github") or {}
    # Description: prefer the PR/issue body (the real intent); fall back to the
    # local plan card's body/goal when there's no forge object (a plan strand).
    body = (gh.get("body") or card.get("body") or card.get("goal") or "").strip()
    return {
        "id": _card_id(card),
        "title": gh.get("title") or card.get("title") or card.get("slug")
        or _card_id(card),
        "role": strand_role(card),
        "state": strand_state(card),
        "source": strand_source(card),
        "stage": strand_stage(card),
        "activity": strand_activity(card),
        "url": gh.get("url") or card.get("path") or "",
        "body": body[:2000],
        "labels": gh.get("labels") or [],
        "branch": gh.get("branch") or card.get("branch") or "",
        "created_at": gh.get("createdAt"),
        "merged_at": gh.get("mergedAt"),
    }


# Stage ordering for "furthest-along" — decides which board column the unified
# card lands in (a mostly-shipped track goes to Completed).
_STAGE_ORDER = {_STAGE_SPEC: 0, "routed": 1, "executing": 2, _STAGE_REVIEW: 3,
                _STAGE_SHIPPED: 4}


def track_stage(details):
    """Where the WHOLE track sits on the pipeline map, as ONE unit (Jonathan's
    rule):
      - all strands at spec'd            -> spec'd (nothing has moved past it),
      - all strands shipped              -> shipped (nothing left),
      - otherwise (the middle)           -> the furthest-along stage among the
        UNSHIPPED strands — the leading edge of what's still moving. So a track
        with impl-PRs shipped but a spec-PR in-review and issues spec'd reads
        'in-review', not 'shipped'. (This is a DIFFERENT axis from the board
        column, which is by activity — 'is there work left'.)"""
    stages = [d.get("stage") or _STAGE_SPEC for d in details]
    if not stages:
        return _STAGE_SPEC
    if all(s == _STAGE_SPEC for s in stages):
        return _STAGE_SPEC
    if all(s == _STAGE_SHIPPED for s in stages):
        return _STAGE_SHIPPED
    # Middle: furthest-along of the strands that aren't already shipped. (If the
    # only unshipped strands are all spec'd, that's where the leading edge is.)
    unshipped = [s for s in stages if s != _STAGE_SHIPPED] or stages
    return max(unshipped, key=lambda s: _STAGE_ORDER.get(s, 0))


def track_facts(details):
    """Derive the fact SUMMARY for a track from its member details (no verdict):
    counts by role/state, the furthest-along stage, and useful factual flags
    like 'impl merged AND spec-PR still open'."""
    roles, states, sources = {}, {}, set()
    for d in details:
        roles[d["role"]] = roles.get(d["role"], 0) + 1
        states[d["state"]] = states.get(d["state"], 0) + 1
        if d["source"] and d["source"] != "—":
            sources.add(d["source"])
    merged = states.get("merged", 0)
    open_spec = any(d["role"] == "spec-PR" and d["state"] == "open"
                    for d in details)
    furthest = _STAGE_SPEC
    for d in details:
        if _STAGE_ORDER.get(d["stage"], 0) > _STAGE_ORDER.get(furthest, 0):
            furthest = d["stage"]
    # Board column (Jonathan's rule): a track is Completed only when EVERY strand
    # is done; any active strand -> Active; else any backlog strand -> Backlog.
    # `furthest_stage` (kept for the pipeline map) is NOT the placement signal —
    # a track with a shipped strand but open issues is still live, not done.
    activities = {strand_activity_of(d) for d in details}
    if "active" in activities:
        placement = "active"
    elif "backlog" in activities:
        placement = "backlog"
    else:
        placement = "completed"
    return {
        "count": len(details),
        "roles": roles,
        "states": states,
        "sources": sorted(sources),
        "merged": merged,
        "impl_merged_spec_open": bool(open_spec and merged),
        "furthest_stage": furthest,
        "pipeline_stage": track_stage(details),
        "placement": placement,
        "activity_counts": {a: sum(1 for d in details
                                   if strand_activity_of(d) == a)
                            for a in ("active", "backlog", "done")},
    }


def strand_activity_of(detail):
    """Read a strand's activity from an already-computed detail dict, falling
    back to 'done' for placeholder rows (unknown members) so they don't wrongly
    keep a finished track out of Completed."""
    a = detail.get("activity")
    return a if a in ("active", "backlog", "done") else "done"


def stamp_track_facts(tracks, cards):
    """Stamp each track with `members_detail` (per-member deterministic facts)
    and a `facts` summary, so the template just renders. Members not resolvable
    to a card are still listed by id (best-effort). Returns the tracks list."""
    by_id = {_card_id(c): c for c in cards}
    for t in tracks:
        details = []
        for m in (t.get("members") or []):
            c = by_id.get(m)
            if c is not None:
                details.append(strand_detail(c))
            else:
                details.append({"id": m, "title": m, "role": "?",
                                "state": "?", "source": "—", "stage": _STAGE_SPEC,
                                "url": ""})
        t["members_detail"] = details
        t["facts"] = track_facts(details)
    return tracks


def stamp_archived(cards, overrides):
    """Mark each card as `archived:true` if its id is in the overrides `archive`
    list — a SOFT, REVERSIBLE flag (mirrors `split`). The collector drops
    archived cards from the board/pipeline/Ungrouped surfaces but KEEPS them in
    status.json, so unarchiving (removing the id from the list) brings them back.
    Fully re-computed each run: a card NOT in the list is un-archived. Returns
    the set of archived ids actually applied."""
    archive = set((overrides or {}).get("archive") or [])
    applied = set()
    for c in cards:
        cid = _card_id(c)
        # Archive is for decluttering STRAYS (ungrouped artifacts). A card that
        # belongs to a track lives inside that track — archiving it would leave a
        # member listed but its card hidden (a confusing half-state). So archive
        # is a no-op for track members: it only hides loose cards. (This can only
        # arise from hand-editing overrides; the UI/triage only archive strays.)
        if cid in archive and not c.get("track"):
            c["archived"] = True
            applied.add(cid)
        elif c.get("archived"):
            # No longer in the list (or now a member) -> unarchive (restore).
            c["archived"] = False
    return applied


def load_runlog(out_dir):
    """The most recent LLM run's change-log (what triage/analysis did). Powers
    the dashboard 'Since last analysis' panel. Missing/bad -> None (no panel)."""
    p = out_dir / RUNLOG_FILE
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_runlog(out_dir, runlog):
    (out_dir / RUNLOG_FILE).write_text(json.dumps(runlog, indent=2))


def build_runlog(now_iso, triage_result):
    """Assemble the change-log entry for a triage run: a timestamp + a flat list
    of changes, each tagged auto|suggest so the panel can distinguish what
    already happened (undoable) from what's pending review. Also carries counts
    for the panel headline."""
    changes = []
    for a in triage_result.get("auto") or []:
        changes.append({"kind": "auto", "action": "attach", "id": a["id"],
                        "track": a.get("track"), "confidence": a.get("confidence"),
                        "reason": a.get("reason", "")})
    for s in triage_result.get("suggestions") or []:
        changes.append({"kind": "suggest", "action": s["action"], "id": s["id"],
                        "track": s.get("track"), "confidence": s.get("confidence"),
                        "reason": s.get("reason", "")})
    return {
        "generated_at": now_iso,
        "pass": "triage",
        "changes": changes,
        "counts": {
            "auto": len(triage_result.get("auto") or []),
            "suggestions": len(triage_result.get("suggestions") or []),
        },
    }


def load_tracks(out_dir):
    p = out_dir / TRACKS_FILE
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_tracks(out_dir, tracks):
    (out_dir / TRACKS_FILE).write_text(json.dumps(tracks, indent=2))


def load_overrides(out_dir, repo_dir):
    """Overrides may live next to the output (where the UI download lands) OR
    next to the collector (committed defaults). Output dir wins."""
    for base in (out_dir, repo_dir):
        p = base / OVERRIDES_FILE
        try:
            return json.loads(p.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return {}
