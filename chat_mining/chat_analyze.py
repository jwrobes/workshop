#!/usr/bin/env python3
"""
chat_analyze.py — Where is your time actually going?

Loads chat records from Cursor and Claude, classifies each into a focus area
(via keyword rules and/or LLM), and prints a breakdown of:

  1. Focus area breakdown (count, %, bar)
  2. Weekly activity (last 16 weeks, by source)
  3. Known-items check (items in config that never appear in chats)
  4. Work pattern (weekday/weekend, hour-of-day buckets)
  5. Uncategorized list

Classification:

  - Keyword pass first (fast, offline). Matches workspace_path and the title +
    first user query against `workspace_keywords` for each focus area.
  - LLM pass second (optional). Sends batches of (id, workspace, title,
    first_query) to a pluggable LLM command (see below); receives a JSON list of (id, focus_area).

LLM modes:
  off     — keywords only, fully offline (default)
  gaps    — keywords first; LLM only for "Uncategorized"
  confirm — both run; LLM wins; disagreements flagged in verbose
  full    — LLM classifies every conversation; keyword unused

Results are cached at ~/.cache/chat_mining_classify.json keyed by conversation
id; re-runs are instant. `--no-cache` forces re-classification.

LLM calls go through a CLI via subprocess, selected by CHAT_MINING_LLM_CMD:
  claude (default) -> `claude -p`   (system prompt prepended to stdin)
  llm              -> `llm [-m MODEL] -s SYSTEM`
  anything else    -> treated as a command line; prompt on stdin, the system
                      prompt in $CHAT_MINING_SYSTEM_PROMPT. Must print the
                      model's reply on stdout.

Config lives at ~/.config/chat-mining/config.json (seeded from
config.example.json on first run).

Usage examples:
    chat-analyze
    chat-analyze --since 21 --llm gaps
    chat-analyze --source claude --since 30 --llm full
    chat-analyze --json --since 7
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from chat_catalog import ChatRecord, iter_store_dbs, load_chat_record

UNCATEGORIZED = "Uncategorized"
EXAMPLE_CONFIG_PATH = Path(__file__).parent / "config.example.json"
DEFAULT_CONFIG_PATH = Path(
    os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
) / "chat-mining" / "config.json"


def ensure_config(config_path: Path) -> bool:
    """Seed config_path from config.example.json if missing. True if it exists after."""
    if config_path.exists():
        return True
    if config_path != DEFAULT_CONFIG_PATH or not EXAMPLE_CONFIG_PATH.exists():
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXAMPLE_CONFIG_PATH, config_path)
    print(f"seeded config at {config_path} (edit it to match your work)", file=sys.stderr)
    return True


# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
def load_config(config_path: Path) -> dict:
    """Load and lightly normalize the config. Expands ~ in cache_path."""
    with config_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg.setdefault("focus_areas", [])
    cfg.setdefault("known_items", [])
    llm = cfg.setdefault("llm", {})
    llm.setdefault("default_model", "claude-haiku-4-5")
    llm.setdefault("batch_size", 25)
    cache_raw = llm.setdefault("cache_path", "~/.cache/chat_mining_classify.json")
    llm["cache_path"] = str(Path(cache_raw).expanduser())

    return cfg


# ----------------------------------------------------------------------------
# Record loading (both sources)
# ----------------------------------------------------------------------------
def load_records(source: str, since_days: int, verbose: bool) -> list[ChatRecord]:
    """Load all records from the requested sources, filtered by --since."""
    cutoff_ts: Optional[float] = None
    if since_days and since_days > 0:
        cutoff_ts = (datetime.now() - timedelta(days=since_days)).timestamp()

    records: list[ChatRecord] = []

    if source in ("cursor", "all"):
        from chat_catalog import CHATS_ROOT
        if CHATS_ROOT.exists():
            for db in iter_store_dbs(CHATS_ROOT):
                try:
                    if cutoff_ts is not None and db.stat().st_mtime < cutoff_ts:
                        continue
                except OSError:
                    continue
                rec = load_chat_record(db, verbose=verbose)
                if rec is None:
                    continue
                if rec.blob_count < 4:
                    continue
                records.append(rec)

    if source in ("claude", "all"):
        from claude_reader import (
            CLAUDE_PROJECTS_ROOT,
            iter_claude_jsonls,
            load_claude_record,
        )
        if CLAUDE_PROJECTS_ROOT.exists():
            for _label, _cid, path in iter_claude_jsonls(CLAUDE_PROJECTS_ROOT):
                try:
                    if cutoff_ts is not None and path.stat().st_mtime < cutoff_ts:
                        continue
                except OSError:
                    continue
                rec = load_claude_record(path, verbose=verbose)
                if rec is None:
                    continue
                if rec.blob_count < 2:  # Claude records are sparser; lower bar
                    continue
                records.append(rec)

    return records


# ----------------------------------------------------------------------------
# Classification — keyword pass
# ----------------------------------------------------------------------------
def keyword_classify(record: ChatRecord, focus_areas: list[dict]) -> Optional[str]:
    """Return focus area name if a workspace_keyword matches, else None.

    Match priority:
      1. record.workspace_path (most reliable signal)
      2. record.name + record.first_user_query (fallback for unknown workspaces)

    Matching is case-insensitive substring. First focus area to match wins;
    order in config.json acts as priority.
    """
    ws = (record.workspace_path or "").lower()
    text = " ".join(filter(None, [record.name, record.first_user_query])).lower()

    for fa in focus_areas:
        kws = [k.lower() for k in (fa.get("workspace_keywords") or [])]
        if not kws:
            continue
        if ws and any(k in ws for k in kws):
            return fa["name"]
    for fa in focus_areas:
        kws = [k.lower() for k in (fa.get("workspace_keywords") or [])]
        if not kws:
            continue
        if text and any(k in text for k in kws):
            return fa["name"]
    return None


# ----------------------------------------------------------------------------
# Classification — LLM pass
# ----------------------------------------------------------------------------
def _build_llm_system_prompt(focus_areas: list[dict]) -> str:
    lines = [
        "You are classifying work conversations by focus area. For each",
        "conversation, return the single best-matching focus area from the list",
        'below. If nothing fits, return "Uncategorized". Respond ONLY with a',
        'JSON array of objects: [{"id": "<id>", "focus_area": "<name>"}].',
        "",
        "Focus areas:",
    ]
    for fa in focus_areas:
        name = fa.get("name", "")
        desc = fa.get("description", "")
        lines.append(f"- {name}: {desc}")
    lines.append(f'- {UNCATEGORIZED}: nothing else fits')
    return "\n".join(lines)


def _build_llm_user_prompt(records: list[ChatRecord]) -> str:
    payload = []
    for r in records:
        payload.append({
            "id": r.conversation_id,
            "workspace": r.workspace_path or "",
            "title": r.name or "",
            "first_query": (r.first_user_query or "")[:600],
        })
    return "Classify these conversations:\n" + json.dumps(payload, ensure_ascii=False)


def build_llm_command(system_prompt: str, model: str) -> tuple[list[str], dict, bool]:
    """Return (argv, extra_env, prepend_system) for CHAT_MINING_LLM_CMD.

    prepend_system=True means the system prompt must be prepended to stdin
    because the CLI has no system-prompt flag.
    """
    spec = os.environ.get("CHAT_MINING_LLM_CMD", "claude").strip() or "claude"
    argv = shlex.split(spec)
    name = Path(argv[0]).name
    if name == "claude" and len(argv) == 1:
        return ["claude", "-p"], {}, True
    if name == "llm" and len(argv) == 1:
        return ["llm", "-m", model, "-s", system_prompt], {}, False
    return argv, {"CHAT_MINING_SYSTEM_PROMPT": system_prompt}, False


def run_llm(system_prompt: str, user_prompt: str, model: str, verbose: bool) -> Optional[str]:
    """Single point of LLM access. Returns stdout text, or None on failure."""
    argv, extra_env, prepend = build_llm_command(system_prompt, model)
    stdin = f"{system_prompt}\n\n{user_prompt}" if prepend else user_prompt
    try:
        proc = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, **extra_env},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        if verbose:
            print(f"  [llm error] subprocess failed: {exc}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        if verbose:
            print(
                f"  [llm error] {argv[0]} exit {proc.returncode}: "
                f"{(proc.stderr or '').strip()[:300]}",
                file=sys.stderr,
            )
        return None
    return (proc.stdout or "").strip()


def llm_classify_batch(
    records: list[ChatRecord],
    focus_areas: list[dict],
    model: str,
    verbose: bool,
) -> dict[str, str]:
    """Classify a single batch via the configured LLM command. Returns {id: focus_area}.

    Robustness:
      - If subprocess fails or the output isn't parseable, we leave every id
        in this batch unclassified (caller treats missing ids as Uncategorized).
      - We accept either a bare JSON array or an object with a "results" field
        — Claude sometimes wraps the response.
    """
    if not records:
        return {}

    system_prompt = _build_llm_system_prompt(focus_areas)
    user_prompt = _build_llm_user_prompt(records)

    raw = run_llm(system_prompt, user_prompt, model, verbose)
    if raw is None:
        return {}
    if not raw:
        return {}

    parsed = _parse_llm_json(raw)
    if parsed is None:
        if verbose:
            print(
                f"  [llm error] couldn't parse response: {raw[:200]}",
                file=sys.stderr,
            )
        return {}

    valid_names = {fa["name"] for fa in focus_areas} | {UNCATEGORIZED}
    out: dict[str, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        cid = item.get("id")
        fa = item.get("focus_area")
        if not isinstance(cid, str) or not isinstance(fa, str):
            continue
        if fa not in valid_names:
            fa = UNCATEGORIZED
        out[cid] = fa
    return out


def _parse_llm_json(raw: str) -> Optional[list]:
    """Be lenient about how the model wraps its JSON output."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # Strip common code-fence wrappers and retry.
        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            if stripped.endswith("```"):
                stripped = stripped[:-3]
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            return None
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("results", "classifications", "data"):
            v = obj.get(key)
            if isinstance(v, list):
                return v
    return None


def llm_classify_all(
    records: list[ChatRecord],
    focus_areas: list[dict],
    model: str,
    batch_size: int,
    verbose: bool,
) -> dict[str, str]:
    """Run llm_classify_batch over all records in chunks. Merges results."""
    out: dict[str, str] = {}
    total = len(records)
    if total == 0:
        return out
    for start in range(0, total, batch_size):
        chunk = records[start : start + batch_size]
        if verbose:
            print(
                f"  [llm] batch {start // batch_size + 1}: {len(chunk)} records",
                file=sys.stderr,
            )
        out.update(llm_classify_batch(chunk, focus_areas, model, verbose))
    return out


# ----------------------------------------------------------------------------
# Cache
# ----------------------------------------------------------------------------
def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(path: Path, cache: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError as exc:
        print(f"  [warn] couldn't save cache to {path}: {exc}", file=sys.stderr)


# ----------------------------------------------------------------------------
# Classification orchestrator
# ----------------------------------------------------------------------------
def classify_all(
    records: list[ChatRecord],
    focus_areas: list[dict],
    llm_mode: str,
    model: str,
    batch_size: int,
    cache_path: Path,
    use_cache: bool,
    verbose: bool,
) -> tuple[dict[str, str], list[tuple[ChatRecord, str, str]]]:
    """Return (classifications, disagreements).

    `classifications` is {conversation_id: focus_area_name}. Every record gets
    a value (possibly UNCATEGORIZED). `disagreements` is only populated in
    `confirm` mode — list of (record, keyword_label, llm_label) where the two
    methods disagreed and the LLM label was chosen.
    """
    cache = load_cache(cache_path) if use_cache else {}
    cache_key = f"{llm_mode}:{model}"  # invalidate cache when mode/model changes
    cache_section = cache.get(cache_key, {}) if use_cache else {}

    results: dict[str, str] = {}
    disagreements: list[tuple[ChatRecord, str, str]] = []

    # Phase 1: pull from cache, run keyword pass for the rest.
    needs_llm: list[ChatRecord] = []
    keyword_results: dict[str, Optional[str]] = {}

    for r in records:
        if r.conversation_id in cache_section:
            results[r.conversation_id] = cache_section[r.conversation_id]
            continue

        kw = keyword_classify(r, focus_areas) if llm_mode != "full" else None
        keyword_results[r.conversation_id] = kw

        if llm_mode == "off":
            results[r.conversation_id] = kw or UNCATEGORIZED
        elif llm_mode == "gaps":
            if kw:
                results[r.conversation_id] = kw
            else:
                needs_llm.append(r)
        elif llm_mode == "confirm":
            needs_llm.append(r)
        elif llm_mode == "full":
            needs_llm.append(r)

    # Phase 2: LLM pass.
    if needs_llm and llm_mode != "off":
        if verbose:
            print(
                f"  [llm] classifying {len(needs_llm)} records via {model} "
                f"(mode: {llm_mode})",
                file=sys.stderr,
            )
        llm_results = llm_classify_all(
            needs_llm, focus_areas, model, batch_size, verbose
        )
        for r in needs_llm:
            llm_label = llm_results.get(r.conversation_id, UNCATEGORIZED)
            if llm_mode == "confirm":
                kw_label = keyword_results.get(r.conversation_id) or UNCATEGORIZED
                if kw_label != UNCATEGORIZED and kw_label != llm_label:
                    disagreements.append((r, kw_label, llm_label))
                results[r.conversation_id] = llm_label
            else:
                results[r.conversation_id] = llm_label

    # Phase 3: persist new entries to cache.
    if use_cache:
        cache_section.update(
            {cid: label for cid, label in results.items()}
        )
        cache[cache_key] = cache_section
        save_cache(cache_path, cache)

    return results, disagreements


# ----------------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------------
def _bar(n: int, max_n: int, width: int = 30) -> str:
    if max_n <= 0:
        return ""
    filled = round(n / max_n * width)
    return "█" * filled + "·" * (width - filled)


def build_focus_breakdown(
    records: list[ChatRecord],
    classifications: dict[str, str],
    focus_areas: list[dict],
) -> list[dict]:
    counts: dict[str, int] = {}
    for r in records:
        label = classifications.get(r.conversation_id, UNCATEGORIZED)
        counts[label] = counts.get(label, 0) + 1
    total = sum(counts.values())
    # Order: focus areas in config order, then Uncategorized last.
    ordered: list[str] = [fa["name"] for fa in focus_areas]
    ordered_set = set(ordered)
    extras = sorted(k for k in counts if k not in ordered_set and k != UNCATEGORIZED)
    final_order = ordered + extras + [UNCATEGORIZED]

    max_count = max(counts.values()) if counts else 0
    rows: list[dict] = []
    for name in final_order:
        c = counts.get(name, 0)
        if c == 0:
            continue
        rows.append({
            "name": name,
            "count": c,
            "pct": (c / total * 100) if total else 0,
            "bar": _bar(c, max_count),
        })
    return rows


def build_weekly_activity(records: list[ChatRecord], weeks: int = 16) -> list[dict]:
    """Bucket records by ISO week for the last `weeks` weeks (oldest first)."""
    now = datetime.now()
    cutoff = now - timedelta(weeks=weeks)
    buckets: dict[str, dict[str, int]] = {}
    for r in records:
        ts = r.last_activity_ts
        if ts < cutoff.timestamp():
            continue
        dt = datetime.fromtimestamp(ts)
        # Monday of that week
        monday = dt - timedelta(days=dt.weekday())
        key = monday.strftime("%Y-%m-%d")
        bucket = buckets.setdefault(key, {"cursor": 0, "claude": 0})
        bucket[r.source] = bucket.get(r.source, 0) + 1
    keys = sorted(buckets.keys())
    return [
        {
            "week_label": k,
            "cursor_count": buckets[k].get("cursor", 0),
            "claude_count": buckets[k].get("claude", 0),
            "total": buckets[k].get("cursor", 0) + buckets[k].get("claude", 0),
        }
        for k in keys
    ]


def build_known_items_check(
    records: list[ChatRecord],
    classifications: dict[str, str],
    known_items: list[dict],
) -> list[dict]:
    """For each known item, mark whether it appears in any classified chat.

    A known item maps to either a focus area or a `__text:keyword` token.
    For text tokens, we do a substring search in title + first_user_query.
    """
    classified_areas = set(classifications.values())
    out: list[dict] = []
    for item in known_items:
        name = item.get("name", "")
        target = item.get("focus_area", "")
        if target.startswith("__text:"):
            kw = target[len("__text:"):].lower()
            seen = any(
                kw in (r.name or "").lower() or kw in (r.first_user_query or "").lower()
                for r in records
            )
        else:
            seen = target in classified_areas
        out.append({"name": name, "focus_area": target, "seen_in_chats": seen})
    return out


def build_work_pattern(records: list[ChatRecord]) -> dict:
    """Weekday/weekend split + hour-of-day buckets, by last_activity_ts."""
    if not records:
        return {
            "weekday_pct": 0.0, "weekend_pct": 0.0,
            "hour_buckets": {"morning": 0, "afternoon": 0, "evening": 0, "late": 0},
        }
    weekday = 0
    weekend = 0
    hour_buckets = {"morning": 0, "afternoon": 0, "evening": 0, "late": 0}
    for r in records:
        dt = datetime.fromtimestamp(r.last_activity_ts)
        if dt.weekday() < 5:
            weekday += 1
        else:
            weekend += 1
        h = dt.hour
        if 5 <= h < 12:
            hour_buckets["morning"] += 1
        elif 12 <= h < 17:
            hour_buckets["afternoon"] += 1
        elif 17 <= h < 22:
            hour_buckets["evening"] += 1
        else:
            hour_buckets["late"] += 1
    total = weekday + weekend
    return {
        "weekday_pct": weekday / total * 100 if total else 0,
        "weekend_pct": weekend / total * 100 if total else 0,
        "hour_buckets": hour_buckets,
    }


def build_uncategorized(
    records: list[ChatRecord], classifications: dict[str, str]
) -> list[ChatRecord]:
    return [
        r for r in records
        if classifications.get(r.conversation_id, UNCATEGORIZED) == UNCATEGORIZED
    ]


def build_report(
    records: list[ChatRecord],
    classifications: dict[str, str],
    focus_areas: list[dict],
    known_items: list[dict],
) -> dict:
    return {
        "focus_breakdown": build_focus_breakdown(records, classifications, focus_areas),
        "weekly_activity": build_weekly_activity(records),
        "known_items_check": build_known_items_check(records, classifications, known_items),
        "work_pattern": build_work_pattern(records),
        "uncategorized": build_uncategorized(records, classifications),
    }


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
def print_report(
    report: dict,
    records: list[ChatRecord],
    disagreements: list[tuple[ChatRecord, str, str]],
    verbose: bool,
) -> None:
    total = len(records)
    cursor_n = sum(1 for r in records if r.source == "cursor")
    claude_n = sum(1 for r in records if r.source == "claude")
    print(f"# {total} conversations  (cursor: {cursor_n}, claude: {claude_n})")
    print()

    # 1. Focus area breakdown
    print("=" * 70)
    print("Focus area breakdown")
    print("=" * 70)
    rows = report["focus_breakdown"]
    if not rows:
        print("(no conversations)")
    else:
        name_w = max(len(r["name"]) for r in rows)
        for r in rows:
            print(
                f"  {r['name']:<{name_w}}  "
                f"{r['count']:>4} ({r['pct']:5.1f}%)  {r['bar']}"
            )
    print()

    # 2. Weekly activity
    print("=" * 70)
    print("Weekly activity (last 16 weeks)")
    print("=" * 70)
    weekly = report["weekly_activity"]
    if not weekly:
        print("(no activity in window)")
    else:
        max_total = max(w["total"] for w in weekly) or 1
        for w in weekly:
            bar = _bar(w["total"], max_total, width=30)
            print(
                f"  {w['week_label']}  "
                f"{w['total']:>3} total  "
                f"(cursor: {w['cursor_count']:>3}, claude: {w['claude_count']:>3})  {bar}"
            )
    print()

    # 3. Known items
    print("=" * 70)
    print("Known-items check")
    print("=" * 70)
    known = report["known_items_check"]
    if not known:
        print("(no known items in config)")
    else:
        for k in known:
            mark = "✓" if k["seen_in_chats"] else "·"
            print(f"  [{mark}] {k['name']}  →  {k['focus_area']}")
    print()

    # 4. Work pattern
    print("=" * 70)
    print("Work pattern")
    print("=" * 70)
    wp = report["work_pattern"]
    print(f"  Weekday:  {wp['weekday_pct']:5.1f}%")
    print(f"  Weekend:  {wp['weekend_pct']:5.1f}%")
    hb = wp["hour_buckets"]
    print(
        f"  Hours: morning(5-12)={hb['morning']}  "
        f"afternoon(12-17)={hb['afternoon']}  "
        f"evening(17-22)={hb['evening']}  "
        f"late(22-5)={hb['late']}"
    )
    print()

    # 5. Uncategorized
    print("=" * 70)
    print(f"Uncategorized ({len(report['uncategorized'])})")
    print("=" * 70)
    for r in report["uncategorized"][:25]:
        ws = r.workspace_path or "(unknown)"
        title = r.name or "(unnamed)"
        print(f"  [{r.source:6}] {title}")
        print(f"           {ws}")
        if r.first_user_query:
            preview = " ".join(r.first_user_query.split())[:100]
            print(f"           \"{preview}\"")
    if len(report["uncategorized"]) > 25:
        print(f"  ... and {len(report['uncategorized']) - 25} more")
    print()

    # Verbose: keyword/LLM disagreements
    if verbose and disagreements:
        print("=" * 70)
        print(f"Keyword/LLM disagreements ({len(disagreements)})")
        print("=" * 70)
        for r, kw, llm in disagreements:
            title = r.name or "(unnamed)"
            print(f"  keyword={kw}  llm={llm}  — {title}")
        print()


def print_json_report(
    report: dict,
    records: list[ChatRecord],
    classifications: dict[str, str],
) -> None:
    out = {
        "totals": {
            "all": len(records),
            "cursor": sum(1 for r in records if r.source == "cursor"),
            "claude": sum(1 for r in records if r.source == "claude"),
        },
        "focus_breakdown": report["focus_breakdown"],
        "weekly_activity": report["weekly_activity"],
        "known_items_check": report["known_items_check"],
        "work_pattern": report["work_pattern"],
        "uncategorized": [
            {
                "conversation_id": r.conversation_id,
                "source": r.source,
                "name": r.name,
                "workspace_path": r.workspace_path,
                "first_user_query": r.first_user_query,
                "last_activity_ts": r.last_activity_ts,
            }
            for r in report["uncategorized"]
        ],
        "classifications": classifications,
    }
    print(json.dumps(out, indent=2))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Analyze chat history to surface where time is actually going."
    )
    p.add_argument(
        "--since",
        type=int,
        default=90,
        help="Days of history to analyze (default: 90; use 0 for all)",
    )
    p.add_argument(
        "--source",
        choices=("cursor", "claude", "all"),
        default="all",
        help="Which chat backend to include (default: all)",
    )
    p.add_argument(
        "--llm",
        choices=("off", "gaps", "confirm", "full"),
        default="off",
        help="LLM classification mode (default: off)",
    )
    p.add_argument(
        "--model",
        default=None,
        help="LLM model (default: from config)",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore the classification cache",
    )
    p.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to focus-area config (default: {DEFAULT_CONFIG_PATH})",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON report instead of the human-readable one",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print per-batch progress and keyword/LLM disagreements",
    )
    return p


def main() -> int:
    args = build_arg_parser().parse_args()

    config_path = Path(args.config).expanduser()
    if not ensure_config(config_path):
        print(f"config not found: {config_path}", file=sys.stderr)
        return 1
    cfg = load_config(config_path)

    focus_areas = cfg["focus_areas"]
    known_items = cfg["known_items"]
    llm_cfg = cfg["llm"]
    model = args.model or llm_cfg["default_model"]
    batch_size = int(llm_cfg.get("batch_size", 25))
    cache_path = Path(llm_cfg["cache_path"])

    if args.verbose:
        print(
            f"# loading records (source={args.source}, since={args.since} days)…",
            file=sys.stderr,
        )
    start = time.time()
    records = load_records(args.source, args.since, args.verbose)
    load_elapsed = time.time() - start

    if args.verbose:
        print(
            f"# loaded {len(records)} records in {load_elapsed:.1f}s",
            file=sys.stderr,
        )

    if not records:
        print("(no chats matched)", file=sys.stderr)
        return 0

    classifications, disagreements = classify_all(
        records,
        focus_areas,
        llm_mode=args.llm,
        model=model,
        batch_size=batch_size,
        cache_path=cache_path,
        use_cache=not args.no_cache,
        verbose=args.verbose,
    )

    report = build_report(records, classifications, focus_areas, known_items)

    if args.json:
        print_json_report(report, records, classifications)
    else:
        print_report(report, records, disagreements, verbose=args.verbose)

    return 0


if __name__ == "__main__":
    sys.exit(main())
