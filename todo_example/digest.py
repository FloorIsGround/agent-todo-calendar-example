"""Pure text rendering, with explicit dates/timezone and no delivery side effects."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .client import Client
from .courses import actionable, load_courses, parse_when
from .server import link_key


def one_line(value: str) -> str:
    return " ".join(value.split())


def render(items: list[dict], todos: list[dict], *, start: date,
           days: int = 7, timezone_name: str = "America/Chicago") -> str:
    if not 1 <= days <= 31:
        raise ValueError("days must be between 1 and 31")
    tz = ZoneInfo(timezone_name)
    current = [t for t in todos if not t["archived"]]
    linked = {link_key(t): t for t in todos if t.get("link")}
    rows: dict[date | None, list[tuple[str, str, bool]]] = {}
    represented = set()
    for item in items:
        if not actionable(item):
            continue
        key = (item["course"], item["itemSourceId"])
        represented.add(key)
        todo = linked.get(key)
        if todo and todo["archived"]:
            continue
        when = parse_when(item["when"])
        if isinstance(when, datetime):
            local = when.astimezone(tz)
            day = local.date()
            clock = f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
            sort_time = local.isoformat()
        else:
            day, clock, sort_time = when, "All day", ""
        line = f"[calendar] {clock}: {one_line(item['title'])} ({one_line(item['course'])})"
        rows.setdefault(day, []).append((sort_time + line, line, bool(todo and todo["completed"])))
    for todo in current:
        key = link_key(todo)
        if key in represented:
            continue
        day = date.fromisoformat(todo["due_date"]) if todo["due_date"] else None
        kind = "linked todo absent from snapshot" if key else "todo"
        line = f"[{kind}] {one_line(todo['title'])}"
        rows.setdefault(day, []).append(("z" + line + todo["id"], line, todo["completed"]))
    unit = "day" if days == 1 else "days"
    lines = [f"# Schedule from {start.isoformat()} ({days} {unit})",
             f"Times: {timezone_name}. '+' pending; '-' completed.", ""]
    for offset in range(days):
        day = start + timedelta(days=offset)
        lines.append(f"## {day.isoformat()}")
        lines.extend(("- " if done else "+ ") + line for _, line, done in sorted(rows.get(day, [])))
        if not rows.get(day):
            lines.append("Nothing scheduled.")
        lines.append("")
    lines.append("## Undated todos")
    lines.extend(("- " if done else "+ ") + line for _, line, done in sorted(rows.get(None, [])))
    if not rows.get(None):
        lines.append("None.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--courses", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--timezone", default="America/Chicago")
    args = parser.parse_args()
    print(render(load_courses(args.courses), Client(args.base_url).list("all"),
                 start=args.start, days=args.days, timezone_name=args.timezone), end="")


if __name__ == "__main__":
    main()
