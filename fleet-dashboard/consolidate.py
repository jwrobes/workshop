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
    (repo#number) since slugs/titles drift; fall back to repo/slug."""
    gh = c.get("github") or {}
    if gh.get("number") is not None:
        return f"{c.get('repo') or '?'}#{gh['number']}"
    return f"{c.get('repo') or c.get('product') or '?'}/{c.get('slug') or ''}"


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


def apply_overrides(tracks, overrides):
    """Apply user corrections (from track-overrides.json) OVER the LLM tracks.
    Overrides win. Supported corrections (all by stable card id):
      - reassign: {card_id: track_name}  -> move a card to a (new or existing) track
      - split:    [card_id, ...]         -> force each into its own singleton track
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


def attach_tracks_to_cards(cards, tracks):
    """Stamp each card with its track name (card['track']) so the UI can render
    unified work-tracks. Cards not in any multi-member track are left untracked
    (a singleton isn't a 'consolidation' worth showing as a group)."""
    member_to_track = {}
    for t in tracks:
        if len(t.get("members") or []) >= 2:  # only real groupings
            for m in t["members"]:
                member_to_track[m] = t["name"]
    for c in cards:
        tn = member_to_track.get(_card_id(c))
        if tn:
            c["track"] = tn
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


def strand_detail(card):
    """The full deterministic fact-row for one member."""
    return {
        "id": _card_id(card),
        "title": (card.get("github") or {}).get("title") or card.get("title")
        or card.get("slug") or _card_id(card),
        "role": strand_role(card),
        "state": strand_state(card),
        "source": strand_source(card),
        "stage": strand_stage(card),
        "url": (card.get("github") or {}).get("url") or card.get("path") or "",
    }


# Stage ordering for "furthest-along" — decides which board column the unified
# card lands in (a mostly-shipped track goes to Completed).
_STAGE_ORDER = {_STAGE_SPEC: 0, "routed": 1, "executing": 2, _STAGE_REVIEW: 3,
                _STAGE_SHIPPED: 4}


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
    return {
        "count": len(details),
        "roles": roles,
        "states": states,
        "sources": sorted(sources),
        "merged": merged,
        "impl_merged_spec_open": bool(open_spec and merged),
        "furthest_stage": furthest,
    }


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
