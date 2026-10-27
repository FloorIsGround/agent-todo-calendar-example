#!/usr/bin/env python3
"""Create or archive todos from simple-calendar-proxy course items.

Polls the per-course JSON snapshots written by simple-calendar-proxy on
127.0.0.1 and reconciles them against the todo service (8765):

- For each course item (due-date or calendar item) that is "actionable"
  (not a lecture/class), create a todo titled "{course} - {item title}"
  with due_date from the item date and category "college".
- Dedupe by 'itemSourceId' (Blackboard id) per course, so a re-sync never
  creates a duplicate.
- Todos are never hard-deleted: when an item disappears from the proxy, the
  matching todo is archived instead.

Good:   course_todo_sync.py            # normal run, idempotent
Good:   course_todo_sync.py --dry-run  # show what would change, change nothing
Bad:    course_todo_sync.py --force    # (not implemented) - always non-destructive

Uses the same conventions as google_calendar_7day_digest.py: local HTTP is
fine on this LAN; paths and tokens are read from the running services, not
hardcoded secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROXY_DATA_DIR = Path.home() / "Desktop/servers/simple-calendar-proxy/data/courses"
TODO_API = os.environ.get("TODO_API", "http://127.0.0.1:8765")
# Item types we consider worth a todo (exclude lectures / pure info).
ACTIONABLE_EVENT_TYPES = {
    "Assignment", "Test", "Quiz", "Exam", "Lab", "Project", "Homework",
    "Discussion", "Task", "Module", "Unit", "Worksheet",
}
# If eventType is missing or unknown, fall back to title keyword scan.
ACTIONABLE_TITLE_HINTS = (
    "assignment", "quiz", "exam", "test", "lab", "project", "homework",
    "discussion", "worksheet", "module", "unit",
)
NON_ACTIONABLE_TITLE_HINTS = (
    "lecture", "class", "seminar", "orientation", "welcome", "introduction",
)
COURSE_CODE = __import__("re").compile(r"[A-Z]{3,4}\d{3}")


def _get_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _todo_query() -> list[dict]:
    return list(_get_json(f"{TODO_API}/todos"))


def _todo_create(title: str, *, description: str = "", due_date: str | None = None,
                 category: str = "college") -> dict:
    body = json.dumps({
        "title": title,
        "description": description or "",
        "due_date": due_date or "",
        "category": category,
    }).encode("utf-8")
    req = urllib.request.Request(f"{TODO_API}/todos", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _todo_update(todo_id: str, **fields) -> dict:
    body = json.dumps(fields).encode("utf-8")
    req = urllib.request.Request(f"{TODO_API}/todos/{todo_id}", data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="PUT")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _todo_archive(todo_id: str) -> dict:
    req = urllib.request.Request(f"{TODO_API}/todos/{todo_id}/archive",
                                 data=json.dumps({"archived": True}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"},
                                 method="PUT")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _description_source_id(desc: str) -> str | None:
    """Extract the itemSourceId embedded in an auto-synced todo description.

    Description format: 'Auto-synced from {source} course calendar
    (itemSourceId: {src}).' Returns the src, or None if not present.
    """
    marker = "itemSourceId:"
    if marker not in desc:
        return None
    rest = desc.split(marker, 1)[1].strip()
    # Strip trailing punctuation/whitespace. Using a single rstrip with all
    # chars handles any order (e.g. 'src).' -> strips '.', then ')').
    return rest.rstrip(").| \t\r\n") or None


def load_course_items() -> list[dict]:
    """Return merged course items from all course JSON files."""
    items: list[dict] = []
    for path in sorted(PROXY_DATA_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        display = data.get("displayId") or path.stem
        source = data.get("source") or "blackboard"
        merged = data.get("dueDateItems") or []
        # NetAcad stores items under dueDateItems only. Blackboard merges
        # calendarItems + dueDateItems in 'merged'; prefer dueDateItems, and
        # fall back to calendarItems for courses with no due dates.
        if not merged:
            merged = data.get("calendarItems") or []
        for item in merged:
            items.append({
                "course": display,
                "source": source,
                "title": item.get("title") or "",
                "startDate": item.get("startDate") or "",
                "endDate": item.get("endDate") or "",
                "eventType": item.get("eventType") or "",
                "handle": item.get("handle") or "",
                "itemSourceId": item.get("itemSourceId") or f"{display}:{item.get('title')}",
                "description": item.get("description") or "",
            })
    return items


def is_actionable(item: dict) -> bool:
    event_type = (item.get("eventType") or "").strip()
    title = (item.get("title") or "").lower()
    if event_type in ACTIONABLE_EVENT_TYPES:
        return True
    if any(h in title for h in NON_ACTIONABLE_TITLE_HINTS):
        return False
    return any(h in title for h in ACTIONABLE_TITLE_HINTS)


def due_date_for(item: dict) -> str | None:
    """Normalize an item's due date to an ISO date (YYYY-MM-DD), else None.

    Proxy items carry the due datetime in `endDate` (the due date) and
    `startDate` (the availability start). Prefer endDate, fall back to
    startDate.
    """
    raw = item.get("endDate") or item.get("startDate") or ""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(
            timezone.utc).date().isoformat()
    except ValueError:
        return None


def _todo_title_for(item: dict) -> str:
    return f"{item['course']} - {item['title']}"


def reconcile(*, dry_run: bool = False, backfill_dates: bool = False) -> dict:
    course_items = load_course_items()
    actionable = [i for i in course_items if is_actionable(i)]
    todos = _todo_query()
    # Build a set of known itemSourceIds already represented by a todo.
    existing = {}
    for t in todos:
        src = _description_source_id(t.get("description") or "")
        if src:
            existing.setdefault(src, t)

    created: list[str] = []
    archived: list[str] = []
    backfilled: list[str] = []
    matched = 0

    for item in actionable:
        src = item.get("itemSourceId") or ""
        todo = existing.get(src)
        if todo:
            matched += 1
            # Backfill a missing due date from the item's endDate.
            if backfill_dates and not todo.get("due_date"):
                due = due_date_for(item)
                if due:
                    if dry_run:
                        backfilled.append(todo.get("title") or "")
                    else:
                        _todo_update(todo["id"], due_date=due)
                        backfilled.append(todo.get("title") or "")
            continue
        title = _todo_title_for(item)
        due = due_date_for(item)
        description = (
            f"Auto-synced from {item['source']} course calendar "
            f"(itemSourceId: {src})."
        )
        if dry_run:
            created.append(title)
            continue
        _todo_create(title, description=description, due_date=due, category="college")
        created.append(title)

    # Archive todos whose itemSourceId no longer exists in the proxy.
    live_srcs = {i.get("itemSourceId") for i in actionable}
    for t in todos:
        src = _description_source_id(t.get("description") or "")
        if src and not t.get("archived") and src not in live_srcs:
            if dry_run:
                archived.append(t.get("title") or t.get("id") or "")
                continue
            _todo_archive(t["id"])
            archived.append(t.get("title") or t.get("id") or "")

    return {"course_items": len(course_items), "actionable": len(actionable),
            "matched": matched, "created": created, "archived": archived,
            "backfilled": backfilled}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change without making changes")
    parser.add_argument("--backfill-dates", action="store_true",
                        help="set missing due dates on existing synced todos")
    args = parser.parse_args()
    try:
        result = reconcile(dry_run=args.dry_run, backfill_dates=args.backfill_dates)
    except Exception as exc:  # urllib/write errors
        print(f"course_todo_sync failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1
    action = "would create" if args.dry_run else "created"
    print(f"course_todo_sync: {result['course_items']} course items, "
          f"{result['actionable']} actionable, {result['matched']} already queued, "
          f"{action} {len(result['created'])}, archived {len(result['archived'])}, "
          f"backfilled {len(result['backfilled'])}")
    for title in result["created"]:
        print(f"  + {title}")
    for title in result["archived"]:
        print(f"  - {title}")
    for title in result["backfilled"]:
        print(f"  ~ {title} (due date set)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())