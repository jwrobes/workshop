#!/usr/bin/env python3
"""
chat_catalog.py — Summarize Claude Code and Cursor chat sessions.

Walks ~/.cursor/chats/*/*/store.db AND ~/.claude/projects/<cwd>/<uuid>.jsonl,
extracts conversation metadata, the workspace path, and the first user query
preview. Both backends produce the same ChatRecord so the rest of the tool is
source-agnostic.

All Cursor reads use read-only SQLite URIs so the tool never locks a running
Cursor instance's database.

Usage examples:
    chat-catalog                          # top 30 most recent across both
    chat-catalog --source claude          # only Claude Code
    chat-catalog --source cursor          # only Cursor
    chat-catalog --since 7                # last 7 days
    chat-catalog --workspace project-a    # filter by workspace substring
    chat-catalog --unclosed               # Cursor only: chats without a close-out
    chat-catalog --json                   # machine-readable

Exit codes: 0 on success, 1 on fatal error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

CHATS_ROOT = Path.home() / ".cursor" / "chats"

# Regexes used to mine context out of the injected user-message payload (Cursor).
WORKSPACE_RE = re.compile(r"Workspace Path:\s*(\S+)")
USER_QUERY_RE = re.compile(
    r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL
)


@dataclass
class ChatRecord:
    db_path: str           # store.db path (Cursor) or .jsonl path (Claude)
    workspace_hash: str    # workspace dir name (Cursor hash, Claude encoded cwd)
    conversation_id: str   # UUID
    name: Optional[str]
    model: Optional[str]
    created_at_ms: Optional[int]
    last_activity_ts: float
    blob_count: int        # Cursor: blob count, Claude: user+assistant message count
    workspace_path: Optional[str]
    first_user_query: Optional[str]
    source: str = "cursor"  # "cursor" or "claude"
    unclosed: Optional[bool] = None  # Cursor-only annotation
    newest_continuation_prompt: Optional[str] = None
    newest_continuation_mtime: Optional[float] = None


# ----------------------------------------------------------------------------
# SQLite helpers (Cursor)
# ----------------------------------------------------------------------------
def open_readonly(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite DB in read-only mode so live Cursor sessions stay unlocked."""
    uri = f"file:{db_path}?mode=ro&immutable=1"
    try:
        return sqlite3.connect(uri, uri=True, timeout=1.0)
    except sqlite3.DatabaseError:
        return sqlite3.connect(str(db_path), timeout=1.0)


def decode_meta(raw_value: str) -> dict:
    """Cursor stores the meta.value as hex-encoded UTF-8 JSON."""
    try:
        return json.loads(bytes.fromhex(raw_value).decode("utf-8", errors="replace"))
    except (ValueError, json.JSONDecodeError):
        return {}


def _content_to_text(content) -> Optional[str]:
    """Normalize a Cursor message blob's `content` field to a single string."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                t = p.get("text")
                if isinstance(t, str):
                    parts.append(t)
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join(parts) if parts else None
    return None


def iter_text_blobs(conn: sqlite3.Connection):
    """Yield `(blob_id, role, text)` tuples for every Cursor message blob."""
    try:
        rows = conn.execute("SELECT id, data FROM blobs WHERE length(data) > 40")
    except sqlite3.DatabaseError:
        return
    for blob_id, data in rows:
        if not data:
            continue
        if isinstance(data, bytes):
            if not data.startswith(b"{"):
                continue
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                continue
        else:
            text = data
        if '"role"' not in text[:80]:
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            continue
        role = obj.get("role")
        content_str = _content_to_text(obj.get("content"))
        if not content_str:
            continue
        yield blob_id, role, content_str


def extract_context_from_blobs(conn: sqlite3.Connection) -> tuple[Optional[str], Optional[str]]:
    """Scan all user-role blobs and return (workspace_path, first_user_query)."""
    workspace: Optional[str] = None
    query_candidates: list[str] = []

    for _blob_id, role, content_str in iter_text_blobs(conn):
        if role != "user":
            continue
        if workspace is None:
            m = WORKSPACE_RE.search(content_str)
            if m:
                workspace = m.group(1)
        for m in USER_QUERY_RE.finditer(content_str):
            q = m.group(1).strip()
            if q:
                query_candidates.append(q)

    first_query = next((q for q in query_candidates if len(q) > 3), None)
    if first_query:
        first_query = " ".join(first_query.split())
    return workspace, first_query


# ----------------------------------------------------------------------------
# Cursor catalog walk
# ----------------------------------------------------------------------------
def iter_store_dbs(chats_root: Path) -> Iterable[Path]:
    """Yield every store.db under ~/.cursor/chats/*/*/."""
    if not chats_root.exists():
        return
    for workspace_dir in sorted(chats_root.iterdir()):
        if not workspace_dir.is_dir():
            continue
        for conv_dir in sorted(workspace_dir.iterdir()):
            if not conv_dir.is_dir():
                continue
            db = conv_dir / "store.db"
            if db.exists():
                yield db


def load_chat_record(db_path: Path, verbose: bool = False) -> Optional[ChatRecord]:
    """Open one Cursor store.db and extract a ChatRecord."""
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = open_readonly(db_path)
        meta_row = conn.execute("SELECT value FROM meta LIMIT 1").fetchone()
        blob_count_row = conn.execute("SELECT COUNT(*) FROM blobs").fetchone()
        workspace, first_query = extract_context_from_blobs(conn)
    except sqlite3.DatabaseError as exc:
        if verbose:
            print(f"  [warn] skipping {db_path}: {exc}", file=sys.stderr)
        return None
    finally:
        if conn is not None:
            conn.close()

    meta = decode_meta(meta_row[0]) if meta_row and meta_row[0] else {}
    blob_count = blob_count_row[0] if blob_count_row else 0

    return ChatRecord(
        db_path=str(db_path),
        workspace_hash=db_path.parent.parent.name,
        conversation_id=db_path.parent.name,
        name=meta.get("name"),
        model=meta.get("lastUsedModel"),
        created_at_ms=meta.get("createdAt"),
        last_activity_ts=db_path.stat().st_mtime,
        blob_count=blob_count,
        workspace_path=workspace,
        first_user_query=first_query,
        source="cursor",
    )


# ----------------------------------------------------------------------------
# Close-out detection (Cursor concept; Claude records skip this)
# ----------------------------------------------------------------------------
_WALK_SKIP_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".pytest_cache", "dist", "build", "target", ".next",
    ".cache", "vendor", "tmp",
})

_continuation_cache: dict[str, tuple[Optional[str], Optional[float]]] = {}


def find_newest_continuation_prompt(workspace_path: Path) -> tuple[Optional[Path], Optional[float]]:
    """Walk the workspace and return the newest CONTINUATION_PROMPT*.md (path, mtime)."""
    key = str(workspace_path)
    if key in _continuation_cache:
        path_str, mtime = _continuation_cache[key]
        return (Path(path_str) if path_str else None), mtime

    candidates: list[tuple[Path, float]] = []
    roots = [workspace_path / "workbench", workspace_path]
    for root in roots:
        if not root.exists():
            continue
        try:
            for dirpath, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in _WALK_SKIP_DIRS]
                depth = len(Path(dirpath).relative_to(root).parts)
                if depth > 4:
                    dirs[:] = []
                    continue
                for fname in files:
                    if fname.startswith("CONTINUATION_PROMPT") and fname.endswith(".md"):
                        p = Path(dirpath) / fname
                        try:
                            candidates.append((p, p.stat().st_mtime))
                        except OSError:
                            pass
        except OSError:
            continue

    if not candidates:
        _continuation_cache[key] = (None, None)
        return None, None
    candidates.sort(key=lambda pair: pair[1], reverse=True)
    best_path, best_mtime = candidates[0]
    _continuation_cache[key] = (str(best_path), best_mtime)
    return best_path, best_mtime


def annotate_unclosed(record: ChatRecord) -> None:
    """Populate `unclosed`/`newest_continuation_*` on a ChatRecord (Cursor only)."""
    if record.source != "cursor":
        return  # Claude records skip the close-out annotation
    if not record.workspace_path:
        record.unclosed = None
        return
    ws = Path(record.workspace_path)
    if not ws.exists():
        record.unclosed = None
        return
    newest_prompt, newest_mtime = find_newest_continuation_prompt(ws)
    record.newest_continuation_prompt = str(newest_prompt) if newest_prompt else None
    record.newest_continuation_mtime = newest_mtime
    if newest_mtime is None:
        record.unclosed = True
        return
    grace = 5 * 60
    record.unclosed = (record.last_activity_ts - newest_mtime) > grace


# ----------------------------------------------------------------------------
# Formatting
# ----------------------------------------------------------------------------
def fmt_ts(ts: Optional[float]) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def fmt_ms(ms: Optional[int]) -> str:
    if not ms:
        return "—"
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M")


def truncate(text: Optional[str], n: int) -> str:
    if not text:
        return "—"
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def print_table(records: list[ChatRecord], show_unclosed: bool) -> None:
    if not records:
        print("(no chats matched)")
        return
    for idx, r in enumerate(records, 1):
        ws_label = r.workspace_path or f"(unknown, hash={r.workspace_hash[:8]})"
        unclosed_tag = ""
        if show_unclosed and r.source == "cursor":
            if r.unclosed is True:
                unclosed_tag = "  [UNCLOSED]"
            elif r.unclosed is False:
                unclosed_tag = f"  [closed {fmt_ts(r.newest_continuation_mtime)}]"
            else:
                unclosed_tag = "  [?]"
        created = fmt_ms(r.created_at_ms)
        active = fmt_ts(r.last_activity_ts)
        time_label = active if active == created else f"{active}  (started {created})"
        src_tag = "claude" if r.source == "claude" else "cursor"
        print(
            f"[{idx:>3}] {time_label}  "
            f"[{src_tag:6}]  "
            f"{(r.model or '—')[:28]:<28}  "
            f"{r.blob_count:>5} msgs  "
            f"{ws_label}{unclosed_tag}"
        )
        name = r.name or "(unnamed)"
        print(f"      name:   {name}")
        if r.first_user_query:
            print(f"      prompt: \"{truncate(r.first_user_query, 140)}\"")
        if show_unclosed and r.unclosed is False and r.newest_continuation_prompt:
            print(f"      close:  {r.newest_continuation_prompt}")
        print(f"      file:   {r.db_path}")
        print()


def print_json(
    records: list[ChatRecord],
    messages_on_date: Optional[dict[str, int]] = None,
) -> None:
    serializable = []
    for r in records:
        d = asdict(r)
        d["last_activity_iso"] = (
            datetime.fromtimestamp(r.last_activity_ts).isoformat()
            if r.last_activity_ts
            else None
        )
        if r.created_at_ms:
            d["created_at_iso"] = datetime.fromtimestamp(
                r.created_at_ms / 1000
            ).isoformat()
        if messages_on_date is not None:
            d["messages_on_date"] = messages_on_date.get(r.conversation_id, 0)
        serializable.append(d)
    print(json.dumps(serializable, indent=2))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    # Import here so help text shows the resolved default path.
    from claude_reader import CLAUDE_PROJECTS_ROOT

    p = argparse.ArgumentParser(
        description="Summarize Claude Code and Cursor chat sessions to find ones worth resuming."
    )
    p.add_argument(
        "--source",
        choices=("cursor", "claude", "all"),
        default="all",
        help="Which chat backend to include (default: all)",
    )
    p.add_argument(
        "--chats-root",
        default=str(CHATS_ROOT),
        help=f"Override the Cursor chats root (default: {CHATS_ROOT})",
    )
    p.add_argument(
        "--claude-root",
        default=str(CLAUDE_PROJECTS_ROOT),
        help=f"Override the Claude projects root (default: {CLAUDE_PROJECTS_ROOT})",
    )
    p.add_argument(
        "--limit", type=int, default=30, help="Max rows to show (default: 30)"
    )
    p.add_argument(
        "--since",
        type=int,
        default=None,
        help="Only show chats active in the last N days",
    )
    p.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Only show sessions with activity on this specific local-time date. "
            "Multi-day continuation sessions are included if they have any "
            "user/assistant records timestamped on that date. "
            "Implies --since automatically."
        ),
    )
    p.add_argument(
        "--workspace",
        default=None,
        help="Filter to chats whose workspace path contains this substring",
    )
    p.add_argument(
        "--min-blobs",
        type=int,
        default=4,
        help="Hide chats with fewer than N messages (default: 4 — skips trivial starts)",
    )
    p.add_argument(
        "--unclosed",
        action="store_true",
        help="Mark each Cursor chat as closed/unclosed via CONTINUATION_PROMPT*.md "
        "and filter to unclosed only (Claude chats are kept regardless).",
    )
    p.add_argument(
        "--include-closed",
        action="store_true",
        help="With --unclosed, also show closed chats (annotated) rather than filtering them out",
    )
    p.add_argument(
        "--json", action="store_true", help="Emit JSON instead of the table"
    )
    p.add_argument(
        "--db",
        default=None,
        help="Inspect a single store.db or .jsonl path and print its record",
    )
    p.add_argument(
        "--sort",
        choices=("activity", "created"),
        default="activity",
        help="Sort key: 'activity' (mtime, default) or 'created' (started time).",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print warnings for files that can't be opened (default: quiet)",
    )
    return p


def _load_single_path(path: Path, verbose: bool = True) -> Optional[ChatRecord]:
    """Dispatch a single --db path to the right loader by suffix."""
    if path.suffix == ".jsonl":
        from claude_reader import load_claude_record
        return load_claude_record(path, verbose=verbose)
    return load_chat_record(path, verbose=verbose)


def main() -> int:
    args = build_arg_parser().parse_args()

    if args.db:
        rec = _load_single_path(Path(args.db), verbose=True)
        if rec is None:
            print("failed to load", file=sys.stderr)
            return 1
        if args.unclosed:
            annotate_unclosed(rec)
        if args.json:
            print_json([rec])
        else:
            print_table([rec], show_unclosed=args.unclosed)
        return 0

    records: list[ChatRecord] = []
    cursor_count = 0
    claude_count = 0
    skipped = 0
    start = time.time()

    # ---- Cursor ----
    if args.source in ("cursor", "all"):
        chats_root = Path(args.chats_root).expanduser()
        if chats_root.exists():
            dbs = list(iter_store_dbs(chats_root))
            cursor_count = len(dbs)
            for db in dbs:
                rec = load_chat_record(db, verbose=args.verbose)
                if rec is None:
                    skipped += 1
                    continue
                records.append(rec)
        elif args.source == "cursor":
            print(f"chats root not found: {chats_root}", file=sys.stderr)
            return 1

    # ---- Claude ----
    if args.source in ("claude", "all"):
        from claude_reader import iter_claude_jsonls, load_claude_record
        claude_root = Path(args.claude_root).expanduser()
        if claude_root.exists():
            jsonls = list(iter_claude_jsonls(claude_root))
            claude_count = len(jsonls)
            for _cwd_label, _conv_id, path in jsonls:
                rec = load_claude_record(path, verbose=args.verbose)
                if rec is None:
                    skipped += 1
                    continue
                records.append(rec)
        elif args.source == "claude":
            print(f"claude projects root not found: {claude_root}", file=sys.stderr)
            return 1

    elapsed = time.time() - start

    # --date implies --since covering the target day plus one buffer day.
    date_start_ts: Optional[float] = None
    date_end_ts: Optional[float] = None
    if args.date:
        try:
            from datetime import date as _date
            target_date = _date.fromisoformat(args.date)
            date_start_ts = datetime.combine(target_date, datetime.min.time()).timestamp()
            date_end_ts = datetime.combine(target_date, datetime.max.time()).timestamp()
            # Widen --since if not explicitly set or too narrow.
            days_ago = (datetime.now().date() - target_date).days + 1
            if args.since is None or args.since < days_ago:
                args.since = days_ago + 1
        except ValueError:
            print(f"--date: invalid date '{args.date}', expected YYYY-MM-DD", file=sys.stderr)
            return 1

    cutoff_ts = None
    if args.since is not None:
        cutoff = datetime.now() - timedelta(days=args.since)
        cutoff_ts = cutoff.timestamp()

    # Per-record messages-on-date count (populated when --date is used).
    messages_on_date: dict[str, int] = {}

    filtered: list[ChatRecord] = []
    for r in records:
        if r.blob_count < args.min_blobs:
            continue
        if cutoff_ts is not None and r.last_activity_ts < cutoff_ts:
            continue
        if args.workspace and (
            not r.workspace_path or args.workspace not in r.workspace_path
        ):
            continue

        # --date filtering: only include sessions active on the target date.
        if date_start_ts is not None:
            created_ts = (r.created_at_ms / 1000) if r.created_at_ms else None
            if created_ts is not None and created_ts > date_end_ts:
                continue  # Session started after target date.
            if r.last_activity_ts < date_start_ts:
                continue  # Session's last activity was before target date.

            # Fast path: session was created on this date.
            if created_ts is not None and date_start_ts <= created_ts <= date_end_ts:
                messages_on_date[r.conversation_id] = r.blob_count
            elif r.source == "claude":
                # Continuation session: scan JSONL for records on target date.
                from claude_reader import has_activity_on_date
                count = has_activity_on_date(
                    Path(r.db_path), date_start_ts, date_end_ts
                )
                if count == 0:
                    continue
                messages_on_date[r.conversation_id] = count
            else:
                # Cursor: no per-record timestamps; include if window overlaps.
                messages_on_date[r.conversation_id] = r.blob_count

        filtered.append(r)

    if args.unclosed:
        for r in filtered:
            annotate_unclosed(r)
        if not args.include_closed:
            # Cursor: filter to unclosed; Claude: keep all (no close-out concept)
            filtered = [
                r for r in filtered
                if r.source == "claude" or r.unclosed is True or r.unclosed is None
            ]

    if args.sort == "created":
        filtered.sort(
            key=lambda r: (r.created_at_ms or 0, r.last_activity_ts), reverse=True
        )
    else:
        filtered.sort(key=lambda r: r.last_activity_ts, reverse=True)
    limited = filtered[: args.limit]

    if args.json:
        print_json(limited, messages_on_date if date_start_ts is not None else None)
    else:
        print(
            f"# Cursor: {cursor_count} DBs, Claude: {claude_count} files in {elapsed:.1f}s — "
            f"{len(filtered)} matched, {skipped} skipped, showing {len(limited)}"
            f"  (sort: {args.sort})"
        )
        print()
        print_table(limited, show_unclosed=args.unclosed)

    return 0


if __name__ == "__main__":
    sys.exit(main())
