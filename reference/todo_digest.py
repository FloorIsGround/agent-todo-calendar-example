#!/usr/bin/env python3
"""Post open todos from the todo service to a Discord forum thread.

Mirrors the google_calendar_7day_digest delivery pattern: create once,
delete + repost on every run, persist the message id in state. Runs from
a Hermes no_agent cron job on .113 with deliver=local, so the script owns
Discord delivery entirely and emits nothing on success.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

TODO_API_BASE = os.environ.get("TODO_API_BASE", "http://127.0.0.1:8765")
DISCORD_API_BASE = "https://discord.com/api/v10"
# Forum thread where the todo list lives. Override via env if ever needed.
DISCORD_THREAD_ID = os.environ.get("TODO_DIGEST_THREAD_ID", "000000000000000001")
DISCORD_MAX_CONTENT = 2000
DISCORD_HEADERS = {
    "Authorization": "",
    "Content-Type": "application/json",
    "User-Agent": "hermes-todo-digest/1.0",
}


def _hermes_root() -> Path:
    """Profile-aware Hermes home (subprocess env preserves HERMES_HOME)."""
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def load_discord_token() -> str:
    """Read DISCORD_BOT_TOKEN from the Hermes .env file.

    Cron subprocesses get their env scrubbed of secrets, so the token
    must be read from disk, not os.environ - same as the calendar digest.
    """
    env_path = _hermes_root() / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "DISCORD_BOT_TOKEN":
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                if value:
                    return value
    except OSError as exc:
        raise RuntimeError(f"Cannot read Hermes .env at {env_path}: {exc}") from exc
    raise RuntimeError("DISCORD_BOT_TOKEN is missing from the Hermes .env file")


def _discord_request(method: str, url: str, payload: dict | None = None) -> dict:
    headers = dict(DISCORD_HEADERS)
    headers["Authorization"] = f"Bot {load_discord_token()}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    request = urllib.request.Request(
        url, data=body or None, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(
            f"Discord {method} {url} failed (HTTP {exc.code}): {detail}"
        ) from exc


def _discord_state_path() -> Path:
    return _hermes_root() / "cron" / ".todo_digest_state.json"


def _load_discord_state() -> dict:
    path = _discord_state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_discord_state(state: dict) -> None:
    path = _discord_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def fetch_todos() -> list[dict]:
    """Open (non-archived, non-completed) todos from the todo service.

    Auto-created course todos (those with 'itemSourceId:' in their
    description, created by course_todo_sync.py) are excluded - they are
    represented in the calendar digest as [calendar] items and would
    clutter this list with a whole semester of assignments.
    """
    url = f"{TODO_API_BASE}/todos?filter=current"
    request = urllib.request.Request(url, headers={"User-Agent": "hermes-todo-digest/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            todos = json.loads(response.read().decode("utf-8"))
        return [t for t in todos if "itemSourceId:" not in (t.get("description") or "")]
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"Todo API {url} failed (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Todo API unreachable at {TODO_API_BASE}: {exc.reason}") from exc


CATEGORY_ORDER = ["college", "need to do", "want to do", "work"]
CATEGORY_HEADER = {
    "college": "College",
    "need to do": "Need to do",
    "want to do": "Want to do",
    "work": "Work",
}


def _category(todo: dict) -> str:
    """Return the todo's category, normalized to a known header or ''."""
    raw = (todo.get("category") or "").strip().lower()
    if raw in CATEGORY_HEADER:
        return raw
    return ""


def _host_suffix() -> str:
    """Last two octets of the primary LAN IP, e.g. '0.113'."""
    try:
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # UDP connect picks the route without sending packets.
            sock.connect(("127.0.0.1", 9))
            ip = sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        ip = ""
    parts = ip.split(".")
    return f"{parts[-2]}.{parts[-1]}" if len(parts) == 4 else "?.?"


def _script_dir() -> str:
    """Directory of this script, abbreviated with ~ when under $HOME."""
    path = Path(__file__).resolve().parent
    try:
        rel = path.relative_to(Path.home())
        return str(Path("~") / rel)
    except ValueError:
        return str(path)


def _footer() -> str:
    """Small-print source line, e.g. '-# 0.113: ~/.hermes/scripts'."""
    return f"-# {_host_suffix()}: {_script_dir()}"


def format_digest(todos: list[dict]) -> str:
    todos = sorted(todos, key=lambda t: t.get("created_at") or "")
    total = len(todos)

    def build(max_items: int | None = None) -> list[str]:
        lines = ["# Todo List", ""]
        shown = todos if max_items is None else todos[:max_items]
        # Group into ordered buckets; '' = uncategorized, goes last.
        buckets: dict[str, list[dict]] = {cat: [] for cat in CATEGORY_ORDER}
        buckets[""] = []
        for todo in shown:
            buckets[_category(todo)].append(todo)
        for cat in CATEGORY_ORDER + [""]:
            items = buckets[cat]
            if not items:
                continue
            if cat:
                lines.append(f"### {CATEGORY_HEADER[cat]}")
            else:
                lines.append("### Other")
            lines.append("```diff")
            for todo in items:
                title = str(todo.get("title") or "Untitled").strip()
                due = (todo.get("due_date") or "").strip()
                suffix = f"  [due {due}]" if due else ""
                if todo.get("completed"):
                    lines.append(f"- {title}{suffix}")
                else:
                    lines.append(f"+ {title}{suffix}")
            lines.append("```")
            # No blank line after the fence - Discord adds its own padding,
            # and an extra blank reads as double spacing before the next header.
        # Footer: small-print source line (host suffix + script dir)
        if total:
            lines.append(_footer())
        else:
            lines.append("- Nothing open. Enjoy the break.")
        return lines

    digest = "\n".join(build()).rstrip() + "\n"
    if len(digest) <= DISCORD_MAX_CONTENT:
        return digest

    # Too many todos to fit: show as many as fit, note the rest.
    max_items = total
    while max_items > 0:
        digest = "\n".join(build(max_items)).rstrip() + "\n"
        if len(digest) <= DISCORD_MAX_CONTENT:
            return digest
        max_items -= 1
    raise RuntimeError("Todo digest cannot fit in a Discord message")


def deliver_digest(digest: str, content_hash: str) -> None:
    """Post a new digest message, delete the old one, and save the new ID.

    Same rolling-message pattern as the calendar digest cronjob. Emits
    nothing on success - cron delivery is ``local`` for this job.
    """
    state = _load_discord_state()
    old_message_id = state.get("message_id")
    thread_id = state.get("thread_id") or DISCORD_THREAD_ID

    # Delete the old message first (best-effort; ignore 404).
    if old_message_id:
        del_url = f"{DISCORD_API_BASE}/channels/{thread_id}/messages/{old_message_id}"
        try:
            _discord_request("DELETE", del_url, {})
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise

    # Post the new message.
    url = f"{DISCORD_API_BASE}/channels/{thread_id}/messages"
    created = _discord_request("POST", url, {"content": digest})
    new_id = created.get("id")
    if not new_id:
        raise RuntimeError("Discord POST succeeded but returned no message id")
    _save_discord_state(
        {"thread_id": thread_id, "message_id": new_id, "content_hash": content_hash}
    )


def main() -> int:
    try:
        todos = fetch_todos()
        digest = format_digest(todos)
        digest_hash = hashlib.sha256(digest.encode("utf-8")).hexdigest()
        if _load_discord_state().get("content_hash") == digest_hash:
            return 0  # nothing changed; leave the posted message as-is
        sys.stdout.write(digest)
        deliver_digest(digest, digest_hash)
        return 0
    except Exception as exc:
        print(f"Todo digest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
