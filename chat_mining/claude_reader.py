"""
claude_reader.py — Read Claude Code's per-conversation JSONL files.

Claude stores chat history at ~/.claude/projects/<encoded-cwd>/<uuid>.jsonl,
one file per conversation. Each line is a typed record (user, assistant,
ai-title, summary, plus a few sidecars like attachment, system, last-prompt,
permission-mode, file-history-snapshot). This module:

- Walks the projects root and yields per-conversation JSONL paths.
- Loads a JSONL into a ChatRecord (the same dataclass chat_catalog uses for
  Cursor) so all three CLIs can treat both backends identically.
- Yields per-message text records for chat_search's full-text scan.

Notes on the format (discovered by sampling actual files):
- The conversation title is in records of type=ai-title under the field
  `aiTitle` (not `title`).
- Only user records with userType == "external" are real user messages;
  internal/synthetic user records (sidechain, command wrappers) should be
  skipped for query/title extraction.
- Assistant message content is a list of parts; we keep `text` and
  `tool_result` parts and skip `thinking` and `tool_use` parts so search
  results don't get polluted by tool plumbing.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

# Imported lazily inside functions to avoid a circular import — chat_catalog
# defines ChatRecord and imports from this module.

CLAUDE_PROJECTS_ROOT = Path.home() / ".claude" / "projects"


# ----------------------------------------------------------------------------
# Walking the projects tree
# ----------------------------------------------------------------------------
def iter_claude_jsonls(root: Path) -> Iterator[tuple[str, str, Path]]:
    """Yield (cwd_label, conversation_id, jsonl_path) for every conversation.

    cwd_label is the encoded directory name (e.g.
    "-Users-alice-workspace-project-a"). conversation_id is the UUID
    file stem.
    """
    if not root.exists():
        return
    for cwd_dir in sorted(root.iterdir()):
        if not cwd_dir.is_dir():
            continue
        for jsonl in sorted(cwd_dir.glob("*.jsonl")):
            yield cwd_dir.name, jsonl.stem, jsonl


# ----------------------------------------------------------------------------
# Content normalization
# ----------------------------------------------------------------------------
def _content_to_text(content) -> Optional[str]:
    """Flatten a Claude message `content` field into a single string.

    Content can be a str (plain user message) or a list of parts. Parts have
    a `type`:
      - "text"        → keep `.text`
      - "tool_result" → keep `.content` (str or list-of-text-parts)
      - "tool_use"    → skip (we don't want JSON tool args in search hits)
      - "thinking"    → skip (internal reasoning, not user-visible)
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for p in content:
        if isinstance(p, str):
            parts.append(p)
            continue
        if not isinstance(p, dict):
            continue
        ptype = p.get("type")
        if ptype == "text":
            t = p.get("text")
            if isinstance(t, str):
                parts.append(t)
        elif ptype == "tool_result":
            inner = p.get("content")
            if isinstance(inner, str):
                parts.append(inner)
            elif isinstance(inner, list):
                for ip in inner:
                    if isinstance(ip, dict):
                        t = ip.get("text")
                        if isinstance(t, str):
                            parts.append(t)
                    elif isinstance(ip, str):
                        parts.append(ip)
        # tool_use and thinking are intentionally skipped.
    return "\n".join(parts) if parts else None


def _parse_iso_ts(ts: Optional[str]) -> Optional[float]:
    """Parse an ISO 8601 UTC timestamp string into a unix timestamp."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        # Z suffix → +00:00 for fromisoformat
        normalized = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


# ----------------------------------------------------------------------------
# Record loading
# ----------------------------------------------------------------------------
def load_claude_record(jsonl_path: Path, verbose: bool = False):
    """Load one JSONL file and return a ChatRecord, or None on hard failure.

    The record types we care about per file:
      - user (userType=="external")  → cwd, first_user_query, timestamps
      - assistant                    → model, timestamps, message count
      - ai-title                     → conversation title (field is `aiTitle`)
    """
    # Local import to break the chat_catalog → claude_reader → chat_catalog cycle.
    from chat_catalog import ChatRecord

    cwd: Optional[str] = None
    title: Optional[str] = None
    model: Optional[str] = None
    first_user_query: Optional[str] = None
    first_user_ts: Optional[float] = None
    last_record_ts: Optional[float] = None
    message_count = 0  # user + assistant only

    try:
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue

                rtype = obj.get("type")

                if rtype == "ai-title" and not title:
                    t = obj.get("aiTitle")
                    if isinstance(t, str) and t.strip():
                        title = t.strip()
                    continue

                if rtype not in ("user", "assistant"):
                    continue

                ts = _parse_iso_ts(obj.get("timestamp"))
                if ts is not None:
                    last_record_ts = ts

                if rtype == "user":
                    if obj.get("userType") != "external":
                        continue
                    if cwd is None:
                        c = obj.get("cwd")
                        if isinstance(c, str):
                            cwd = c
                    msg = obj.get("message") or {}
                    text = _content_to_text(msg.get("content") if isinstance(msg, dict) else None)
                    # Skip synthetic command wrappers like "<command-message>...</command-message>"
                    # by requiring the first query be substantial real text.
                    if first_user_query is None and text:
                        cleaned = " ".join(text.split())
                        # Strip out command-message envelopes if present.
                        if cleaned.startswith("<command-") or cleaned.startswith("<local-command"):
                            pass
                        elif len(cleaned) >= 4:
                            first_user_query = cleaned
                            first_user_ts = ts
                    message_count += 1
                else:  # assistant
                    if model is None:
                        msg = obj.get("message") or {}
                        if isinstance(msg, dict):
                            m = msg.get("model")
                            if isinstance(m, str):
                                model = m
                    message_count += 1
    except OSError as exc:
        if verbose:
            print(f"  [warn] cannot read {jsonl_path}: {exc}", file=sys.stderr)
        return None

    if message_count == 0 and not title:
        return None

    try:
        mtime = jsonl_path.stat().st_mtime
    except OSError:
        mtime = 0.0

    last_activity_ts = last_record_ts if last_record_ts is not None else mtime
    created_at_ms = int(first_user_ts * 1000) if first_user_ts else None

    return ChatRecord(
        db_path=str(jsonl_path),
        workspace_hash=jsonl_path.parent.name,
        conversation_id=jsonl_path.stem,
        name=title,
        model=model,
        created_at_ms=created_at_ms,
        last_activity_ts=last_activity_ts,
        blob_count=message_count,
        workspace_path=cwd,
        first_user_query=first_user_query,
        source="claude",
    )


def has_activity_on_date(jsonl_path: Path, start_ts: float, end_ts: float) -> int:
    """Return the count of user+assistant records with timestamps in [start_ts, end_ts].

    Used by --date filtering: scans the file only when the session is a
    continuation (created before the target date but still active after it).
    Returns 0 if the file can't be read or has no records in range.
    """
    count = 0
    try:
        with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if obj.get("type") not in ("user", "assistant"):
                    continue
                ts = _parse_iso_ts(obj.get("timestamp"))
                if ts is not None and start_ts <= ts <= end_ts:
                    count += 1
    except OSError:
        pass
    return count


def iter_claude_text_records(
    jsonl_path: Path,
) -> Iterator[tuple[str, str, Optional[float]]]:
    """Yield (role, text, unix_timestamp) for every user/assistant record.

    Filters internal/synthetic user records (userType != "external") so search
    hits represent real conversation content. Tool-use parts are dropped by
    `_content_to_text`.
    """
    try:
        f = jsonl_path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            rtype = obj.get("type")
            if rtype not in ("user", "assistant"):
                continue
            if rtype == "user" and obj.get("userType") != "external":
                continue
            msg = obj.get("message") or {}
            content = msg.get("content") if isinstance(msg, dict) else None
            text = _content_to_text(content)
            if not text:
                continue
            yield rtype, text, _parse_iso_ts(obj.get("timestamp"))
