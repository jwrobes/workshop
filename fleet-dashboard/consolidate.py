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
import subprocess

CLAUDE_CLI = "claude"
TRACKS_FILE = "tracks.json"
OVERRIDES_FILE = "track-overrides.json"

# Only these card sources are "loose" (not yet unified into a real plan track).
LOOSE_SOURCES = ("remote-only", "workbench-only")


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
    }


def _card_id(c):
    """A stable identifier for a card across runs: prefer the GitHub ref
    (repo#number) since slugs/titles drift; fall back to repo/slug."""
    gh = c.get("github") or {}
    if gh.get("number") is not None:
        return f"{c.get('repo') or '?'}#{gh['number']}"
    return f"{c.get('repo') or c.get('product') or '?'}/{c.get('slug') or ''}"


CONSOLIDATE_PROMPT = """\
You group scattered software work artifacts into work-tracks. A "track" is ONE
feature/effort whose artifacts (plan, issues, spec-PRs, impl-PRs) are scattered
with diverging titles. Group items that are clearly the SAME effort.

Rules:
- Only group items you are confident belong together (shared feature/topic).
- A singleton track is fine — do NOT force unrelated items together.
- Prefer a short, human kebab-case track name (e.g. "communications-hub", "email-triage").
- Return ONLY compact JSON, no prose, no markdown fence:
  {"tracks":[{"name":"<kebab>","members":["<id>",...]}]}

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
        if name and members:
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
    """Parse JSON that may be wrapped in a ```json fence or have leading prose."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip().rstrip("`").strip()
    # If there's leading/trailing prose, grab the outermost {...}.
    if not s.startswith("{"):
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
