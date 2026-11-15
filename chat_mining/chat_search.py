#!/usr/bin/env python3
"""
chat_search.py — Full-text search across Claude Code AND Cursor chat sessions.

Answers the "which chat did I discuss X in?" question. Walks every
~/.cursor/chats/*/*/store.db (Cursor) and every
~/.claude/projects/<cwd>/<uuid>.jsonl (Claude), searches message content for
all provided terms, and returns a ranked list with match counts, context
snippets, and the same metadata as chat_catalog.py.

Search rules:
  * Case-insensitive by default (use -s for case-sensitive).
  * All terms must appear somewhere in the chat by default (AND).
    Use --any for OR.
  * Each term is a substring match. Use -w for whole-word matching.
  * Snippets are extracted from user and assistant text — tool-call JSON,
    thinking blocks, and binary structural blobs are skipped.

Performance notes:
  * Cursor: a DB-level LIKE pre-filter skips store.db files that can't
    contain any term.
  * Claude: a raw byte-level pre-filter on the JSONL file does the same job.
  * Matching chats are fully scanned to count hits and pull snippets.

Usage examples:
    chat-search -w "FDA" "validate"
    chat-search --workspace project-a "parser" "schema"
    chat-search --since 30 "judge concurrency"
    chat-search --any "Project A" "Docs" "Tooling"
    chat-search --source claude --since 14 "amplitude"
    chat-search --json "FoodData" > /tmp/hits.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Reuse the catalog's readers + annotators so behavior stays consistent.
from chat_catalog import (
    CHATS_ROOT,
    ChatRecord,
    annotate_unclosed,
    fmt_ms,
    fmt_ts,
    iter_store_dbs,
    iter_text_blobs,
    load_chat_record,
    open_readonly,
    truncate,
)


@dataclass
class SearchHit:
    record: ChatRecord
    total_matches: int
    per_term_matches: dict  # term -> int
    snippets: list  # list of (term, snippet_text)


# ----------------------------------------------------------------------------
# Matching / snippet helpers
# ----------------------------------------------------------------------------
def build_term_patterns(
    terms: list[str], case_sensitive: bool, word_boundary: bool
) -> list[re.Pattern]:
    flags = 0 if case_sensitive else re.IGNORECASE
    patterns = []
    for t in terms:
        escaped = re.escape(t)
        if word_boundary:
            escaped = rf"\b{escaped}\b"
        patterns.append(re.compile(escaped, flags))
    return patterns


def has_any_term_sql(
    conn: sqlite3.Connection, terms: list[str], case_sensitive: bool
) -> bool:
    """DB-level pre-filter: does ANY blob contain ANY term?"""
    placeholders = []
    params = []
    for t in terms:
        if case_sensitive:
            placeholders.append("instr(CAST(data AS TEXT), ?) > 0")
            params.append(t)
        else:
            placeholders.append("instr(LOWER(CAST(data AS TEXT)), LOWER(?)) > 0")
            params.append(t)
    sql = (
        "SELECT EXISTS(SELECT 1 FROM blobs WHERE "
        + " OR ".join(placeholders)
        + ")"
    )
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.DatabaseError:
        return True
    return bool(row and row[0])


def has_any_term_file(jsonl_path: Path, terms: list[str], case_sensitive: bool) -> bool:
    """File-level pre-filter for JSONL: does the raw file contain ANY term?

    Reads the whole file as bytes (these are typically a few hundred KB to a
    few MB; cheap compared to JSON parsing every line).
    """
    try:
        data = jsonl_path.read_bytes()
    except OSError:
        return True  # fail open
    if case_sensitive:
        haystack = data
        for t in terms:
            if t.encode("utf-8") in haystack:
                return True
    else:
        haystack = data.lower()
        for t in terms:
            if t.lower().encode("utf-8") in haystack:
                return True
    return False


def extract_snippet(text: str, pattern: re.Pattern, window: int = 110) -> Optional[str]:
    """Return one-line snippet around the first match of `pattern` in `text`."""
    m = pattern.search(text)
    if not m:
        return None
    start = max(0, m.start() - window)
    end = min(len(text), m.end() + window)
    snippet = text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return " ".join(snippet.split())


# ----------------------------------------------------------------------------
# Cursor scan
# ----------------------------------------------------------------------------
def scan_db_for_hits(
    db_path: Path,
    terms: list[str],
    patterns: list[re.Pattern],
    case_sensitive: bool,
    role_filter: Optional[str],
    require_all: bool,
    max_snippets: int,
    verbose: bool,
) -> Optional[SearchHit]:
    """Return a SearchHit if the Cursor chat matches, else None."""
    conn: Optional[sqlite3.Connection] = None
    try:
        conn = open_readonly(db_path)
        if not has_any_term_sql(conn, terms, case_sensitive):
            return None

        per_term_counts = {t: 0 for t in terms}
        snippets: list[tuple[str, str]] = []
        seen_snippet_terms: set[str] = set()

        for _bid, role, content in iter_text_blobs(conn):
            if role_filter and role != role_filter:
                continue
            for term, pat in zip(terms, patterns):
                count = len(pat.findall(content))
                if count == 0:
                    continue
                per_term_counts[term] += count
                if (
                    term not in seen_snippet_terms
                    and len(snippets) < max_snippets
                ):
                    snip = extract_snippet(content, pat)
                    if snip:
                        snippets.append((term, snip))
                        seen_snippet_terms.add(term)

        if require_all and any(c == 0 for c in per_term_counts.values()):
            return None
        total = sum(per_term_counts.values())
        if total == 0:
            return None
    except sqlite3.DatabaseError as exc:
        if verbose:
            print(f"  [warn] skipping {db_path}: {exc}", file=sys.stderr)
        return None
    finally:
        if conn is not None:
            conn.close()

    record = load_chat_record(db_path, verbose=verbose)
    if record is None:
        return None
    return SearchHit(
        record=record,
        total_matches=total,
        per_term_matches=per_term_counts,
        snippets=snippets,
    )


# ----------------------------------------------------------------------------
# Claude scan
# ----------------------------------------------------------------------------
def scan_jsonl_for_hits(
    jsonl_path: Path,
    terms: list[str],
    patterns: list[re.Pattern],
    case_sensitive: bool,
    role_filter: Optional[str],
    require_all: bool,
    max_snippets: int,
    verbose: bool,
) -> Optional[SearchHit]:
    """Return a SearchHit if the Claude chat matches, else None."""
    from claude_reader import iter_claude_text_records, load_claude_record

    if not has_any_term_file(jsonl_path, terms, case_sensitive):
        return None

    per_term_counts = {t: 0 for t in terms}
    snippets: list[tuple[str, str]] = []
    seen_snippet_terms: set[str] = set()

    try:
        for role, content, _ts in iter_claude_text_records(jsonl_path):
            if role_filter and role != role_filter:
                continue
            for term, pat in zip(terms, patterns):
                count = len(pat.findall(content))
                if count == 0:
                    continue
                per_term_counts[term] += count
                if (
                    term not in seen_snippet_terms
                    and len(snippets) < max_snippets
                ):
                    snip = extract_snippet(content, pat)
                    if snip:
                        snippets.append((term, snip))
                        seen_snippet_terms.add(term)
    except OSError as exc:
        if verbose:
            print(f"  [warn] skipping {jsonl_path}: {exc}", file=sys.stderr)
        return None

    if require_all and any(c == 0 for c in per_term_counts.values()):
        return None
    total = sum(per_term_counts.values())
    if total == 0:
        return None

    record = load_claude_record(jsonl_path, verbose=verbose)
    if record is None:
        return None
    return SearchHit(
        record=record,
        total_matches=total,
        per_term_matches=per_term_counts,
        snippets=snippets,
    )


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
def print_table(hits: list[SearchHit], show_unclosed: bool, terms: list[str]) -> None:
    if not hits:
        print("(no chats matched)")
        return
    for idx, hit in enumerate(hits, 1):
        r = hit.record
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
        print(f"      name:    {r.name or '(unnamed)'}")
        term_summary = ", ".join(
            f"{c}× \"{t}\"" for t, c in hit.per_term_matches.items() if c > 0
        )
        print(f"      matches: {hit.total_matches} total ({term_summary})")
        if r.first_user_query:
            print(f"      prompt:  \"{truncate(r.first_user_query, 120)}\"")
        for term, snippet in hit.snippets:
            print(f"      [{term}]: {truncate(snippet, 200)}")
        print(f"      file:    {r.db_path}")
        print()


def print_json(hits: list[SearchHit]) -> None:
    out = []
    for hit in hits:
        d = asdict(hit.record)
        d["total_matches"] = hit.total_matches
        d["per_term_matches"] = hit.per_term_matches
        d["snippets"] = [{"term": t, "snippet": s} for t, s in hit.snippets]
        if hit.record.last_activity_ts:
            d["last_activity_iso"] = datetime.fromtimestamp(
                hit.record.last_activity_ts
            ).isoformat()
        if hit.record.created_at_ms:
            d["created_at_iso"] = datetime.fromtimestamp(
                hit.record.created_at_ms / 1000
            ).isoformat()
        out.append(d)
    print(json.dumps(out, indent=2))


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    from claude_reader import CLAUDE_PROJECTS_ROOT

    p = argparse.ArgumentParser(
        description="Search across Claude Code and Cursor chat sessions for terms."
    )
    p.add_argument(
        "terms",
        nargs="+",
        help="One or more search terms. Multi-word phrases should be quoted. "
        "By default all terms must appear (AND).",
    )
    p.add_argument(
        "--source",
        choices=("cursor", "claude", "all"),
        default="all",
        help="Which chat backend to search (default: all)",
    )
    p.add_argument(
        "--any",
        dest="any_term",
        action="store_true",
        help="Match chats where ANY term appears (OR instead of AND).",
    )
    p.add_argument(
        "-s",
        "--case-sensitive",
        action="store_true",
        help="Case-sensitive matching (default: case-insensitive).",
    )
    p.add_argument(
        "-w",
        "--word",
        dest="word_boundary",
        action="store_true",
        help="Require whole-word matches (wraps each term with \\b).",
    )
    p.add_argument(
        "--role",
        choices=("user", "assistant", "system", "tool"),
        default=None,
        help="Restrict search to a specific message role (default: all roles).",
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
        "--since",
        type=int,
        default=None,
        help="Only search chats active in the last N days",
    )
    p.add_argument(
        "--workspace",
        default=None,
        help="Filter to chats whose workspace path contains this substring",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Max matching chats to show (default: 15)",
    )
    p.add_argument(
        "--snippets",
        type=int,
        default=3,
        help="Max snippets to show per matching chat (default: 3)",
    )
    p.add_argument(
        "--unclosed",
        action="store_true",
        help="Annotate Cursor hits with closed/unclosed status",
    )
    p.add_argument(
        "--sort",
        choices=("score", "activity", "created"),
        default="score",
        help="Sort key: 'score' (match count, default), 'activity' (mtime), 'created'.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the table",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print progress and warnings",
    )
    return p


def main() -> int:
    args = build_arg_parser().parse_args()
    terms = args.terms
    patterns = build_term_patterns(terms, args.case_sensitive, args.word_boundary)

    cutoff_ts = None
    if args.since is not None:
        cutoff_ts = (datetime.now() - timedelta(days=args.since)).timestamp()

    hits: list[SearchHit] = []
    skipped_date = 0
    skipped_workspace = 0
    cursor_scanned = 0
    claude_scanned = 0
    start = time.time()

    # ---- Cursor ----
    if args.source in ("cursor", "all"):
        chats_root = Path(args.chats_root).expanduser()
        if chats_root.exists():
            for db in iter_store_dbs(chats_root):
                try:
                    if cutoff_ts is not None and db.stat().st_mtime < cutoff_ts:
                        skipped_date += 1
                        continue
                except OSError:
                    continue
                cursor_scanned += 1
                hit = scan_db_for_hits(
                    db_path=db,
                    terms=terms,
                    patterns=patterns,
                    case_sensitive=args.case_sensitive,
                    role_filter=args.role,
                    require_all=not args.any_term,
                    max_snippets=args.snippets,
                    verbose=args.verbose,
                )
                if hit is None:
                    continue
                if args.workspace:
                    ws = hit.record.workspace_path or ""
                    if args.workspace not in ws:
                        skipped_workspace += 1
                        continue
                hits.append(hit)
                if args.verbose:
                    print(
                        f"  [hit cursor] {hit.total_matches:>4} — {hit.record.name!r} ({db})",
                        file=sys.stderr,
                    )
        elif args.source == "cursor":
            print(f"chats root not found: {chats_root}", file=sys.stderr)
            return 1

    # ---- Claude ----
    if args.source in ("claude", "all"):
        from claude_reader import iter_claude_jsonls
        claude_root = Path(args.claude_root).expanduser()
        if claude_root.exists():
            for _cwd_label, _conv_id, path in iter_claude_jsonls(claude_root):
                try:
                    if cutoff_ts is not None and path.stat().st_mtime < cutoff_ts:
                        skipped_date += 1
                        continue
                except OSError:
                    continue
                claude_scanned += 1
                hit = scan_jsonl_for_hits(
                    jsonl_path=path,
                    terms=terms,
                    patterns=patterns,
                    case_sensitive=args.case_sensitive,
                    role_filter=args.role,
                    require_all=not args.any_term,
                    max_snippets=args.snippets,
                    verbose=args.verbose,
                )
                if hit is None:
                    continue
                if args.workspace:
                    ws = hit.record.workspace_path or ""
                    if args.workspace not in ws:
                        skipped_workspace += 1
                        continue
                hits.append(hit)
                if args.verbose:
                    print(
                        f"  [hit claude] {hit.total_matches:>4} — {hit.record.name!r} ({path})",
                        file=sys.stderr,
                    )
        elif args.source == "claude":
            print(f"claude projects root not found: {claude_root}", file=sys.stderr)
            return 1

    elapsed = time.time() - start

    if args.unclosed:
        for h in hits:
            annotate_unclosed(h.record)

    if args.sort == "score":
        hits.sort(
            key=lambda h: (h.total_matches, h.record.last_activity_ts),
            reverse=True,
        )
    elif args.sort == "created":
        hits.sort(
            key=lambda h: (h.record.created_at_ms or 0, h.record.last_activity_ts),
            reverse=True,
        )
    else:
        hits.sort(key=lambda h: h.record.last_activity_ts, reverse=True)

    limited = hits[: args.limit]

    if args.json:
        print_json(limited)
    else:
        mode = "ANY" if args.any_term else "ALL"
        term_desc = " ".join(f'"{t}"' for t in terms)
        print(
            f"# Searched Cursor: {cursor_scanned} DBs, Claude: {claude_scanned} files "
            f"for {mode} of {term_desc} in {elapsed:.1f}s"
        )
        print(
            f"# {len(hits)} chats matched, showing {len(limited)}  "
            f"(sort: {args.sort}, date-skipped: {skipped_date}, "
            f"workspace-filtered: {skipped_workspace})"
        )
        print()
        print_table(limited, show_unclosed=args.unclosed, terms=terms)

    return 0


if __name__ == "__main__":
    sys.exit(main())
