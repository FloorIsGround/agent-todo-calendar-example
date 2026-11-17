"""Sync course todos and atomically save a digest; suitable for ordinary Unix cron."""
from __future__ import annotations

import argparse
import fcntl
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .client import Client
from .courses import load_courses
from .digest import render
from .sync import reconcile_items


def run_job(courses: Path, output: Path, *, base_url: str = "http://127.0.0.1:8765",
            start: date | None = None, days: int = 7,
            timezone_name: str = "America/Chicago") -> bool:
    """Return False if another run owns this output; otherwise sync and replace it."""
    if not 1 <= days <= 31:
        raise ValueError("days must be between 1 and 31")
    tz = ZoneInfo(timezone_name)
    start = start if start is not None else datetime.now(tz).date()
    start + timedelta(days=days - 1)  # Validate the entire window before sync writes.
    client = Client(base_url)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.with_name(output.name + ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        items = load_courses(courses.expanduser().resolve())
        reconcile_items(client, items)
        digest = render(items, client.list("all"), start=start, days=days,
                        timezone_name=timezone_name)
        descriptor, name = tempfile.mkstemp(prefix="." + output.name + ".", suffix=".tmp",
                                            dir=output.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(digest)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--courses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--start", type=date.fromisoformat,
                        help="first digest day (default: today in --timezone)")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--timezone", default="America/Chicago")
    args = parser.parse_args()
    try:
        run_job(args.courses, args.output, base_url=args.base_url, start=args.start,
                days=args.days, timezone_name=args.timezone)
    except (OSError, ValueError, OverflowError, ZoneInfoNotFoundError) as exc:
        print(f"Calendar job failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
