"""Validate the local course-snapshot boundary before making any HTTP writes."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from pydantic import Field

from .server import InputModel

ACTIONABLE_TYPES = {"Assignment", "Test", "Quiz", "Exam", "Lab", "Project", "Homework",
                    "Discussion", "Task", "Module", "Unit", "Worksheet"}
TITLE_HINTS = ("assignment", "quiz", "exam", "test", "lab", "project", "homework",
               "discussion", "worksheet", "module", "unit")
EXCLUDE_HINTS = ("lecture", "class", "seminar", "orientation", "welcome", "introduction")


class CourseItem(InputModel):
    title: str = Field(min_length=1)
    itemSourceId: str = Field(min_length=1)
    startDate: str = ""
    endDate: str = ""
    eventType: str = ""
    description: str = ""
    handle: str = ""


class CourseSnapshot(InputModel):
    displayId: str = Field(min_length=1)
    source: str = Field(default="local", min_length=1)
    dueDateItems: list[CourseItem] = []
    calendarItems: list[CourseItem] = []


def parse_when(raw: str) -> date | datetime:
    if len(raw) == 10:
        return date.fromisoformat(raw)
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must include an explicit timezone offset")
    return value


def actionable(item: dict) -> bool:
    if item["eventType"] in ACTIONABLE_TYPES:
        return True
    title = item["title"].casefold()
    return not any(h in title for h in EXCLUDE_HINTS) and any(h in title for h in TITLE_HINTS)


def load_courses(directory: Path) -> list[dict]:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError(f"No course JSON files in {directory}")
    items = []
    seen = set()
    for path in paths:
        try:
            snapshot = CourseSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
            selected = snapshot.dueDateItems or snapshot.calendarItems
            if not selected:
                raise ValueError("Course snapshot is empty")
            for entry in selected:
                item = entry.model_dump()
                for field in ("startDate", "endDate"):
                    if item[field]:
                        parse_when(item[field])
                raw = item["endDate"] or item["startDate"]
                if not raw:
                    raise ValueError("Course item has no date")
                when = parse_when(raw)
                key = (snapshot.displayId, item["itemSourceId"])
                if key in seen:
                    raise ValueError(f"Duplicate course/source key: {key}")
                seen.add(key)
                items.append({**item, "course": snapshot.displayId, "source": snapshot.source,
                              "when": raw, "due_date": when.date().isoformat()
                              if isinstance(when, datetime) else when.isoformat()})
        except (OSError, ValueError) as exc:
            raise ValueError(f"Invalid course snapshot {path.name}: {exc}") from exc
    return items
