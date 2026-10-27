"""Upsert actionable course items; never auto-archive or change completion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .client import Client
from .courses import actionable, load_courses
from .server import link_key


def reconcile(client: Client, directory: Path, *, dry_run: bool = False) -> dict:
    items = [item for item in load_courses(directory) if actionable(item)]
    todos = client.list("all")
    existing = {}
    for todo in todos:
        key = link_key(todo)
        if key:
            if key in existing:
                raise ValueError(f"Ambiguous stored course/source link: {key}")
            existing[key] = todo
    result = {"created": 0, "updated": 0, "matched": 0, "archived": 0,
              "archived_matches": 0, "dry_run": dry_run}
    for item in items:
        key = (item["course"], item["itemSourceId"])
        fields = {"title": f"{item['course']} - {item['title']}",
                  "description": f"Imported from {item['source']} course JSON.",
                  "category": "college", "due_date": item["due_date"]}
        todo = existing.get(key)
        if todo is None:
            if not dry_run:
                client.create({**fields, "link": {"course": key[0], "source_id": key[1]}})
            result["created"] += 1
        else:
            result["matched"] += 1
            if todo["archived"]:
                result["archived_matches"] += 1
                continue
            changes = {k: v for k, v in fields.items() if todo[k] != v}
            if changes:
                if not dry_run:
                    client.update(todo["id"], changes)
                result["updated"] += 1
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--courses", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(reconcile(Client(args.base_url), args.courses, dry_run=args.dry_run), indent=2))


if __name__ == "__main__":
    main()
