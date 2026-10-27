"""Exercise real HTTP on disposable fictional data, then save a fresh trace."""
from __future__ import annotations

import argparse
import json
import socket
import tempfile
import threading
import time
from collections import Counter
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import uvicorn

from .client import Client
from .courses import load_courses
from .digest import render
from .server import create_app, link_key
from .sync import reconcile

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def local_server(data_file: Path):
    """The OS chooses a free loopback port; no personal service is contacted."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(data_file), log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Disposable server did not start")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        if thread.is_alive():
            raise RuntimeError("Disposable server did not stop")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_demo() -> dict:
    courses = ROOT / "examples/fictional_courses"
    items = load_courses(courses)
    requests = []
    with tempfile.TemporaryDirectory(prefix=".demo-", dir=ROOT) as temporary:
        with local_server(Path(temporary) / "todos.json") as base_url:
            client = Client(base_url, trace=requests)
            manual = client.create({"title": "Return fictional library book", "category": "need to do",
                                    "due_date": "2026-09-25"})
            first = reconcile(client, courses)
            second = reconcile(client, courses)
            require(first["created"] == 2 and second["created"] == 0, "Sync duplicated records")
            before = client.list("all")
            require(len(before) == 3, "Unexpected record count")
            before_digest = render(items, before, start=date(2026, 9, 25), days=1)
            targets = {link_key(t): t for t in before if t["link"]}
            readbacks = []
            for source_id in ("demo-lab-001", "demo-quiz-001"):
                original = targets[("DEMO101_FALL", source_id)]
                client.update(original["id"], {"completed": True})
                readback = client.get(original["id"])
                require(readback["id"] == original["id"] and readback["completed"]
                        and bool(readback["completed_at"]), "Exact-ID verification failed")
                require(all(readback[k] == original[k] for k in
                            ("title", "link", "due_date", "created_at", "archived")),
                        "Completion changed identity, date, or archive state")
                readbacks.append(readback)
            third = reconcile(client, courses)
            after = client.list("all")
            require(client.get(manual["id"]) == manual, "Unrelated item changed")
            for verified in readbacks:
                require(client.get(verified["id"]) == verified, "Sync changed completion state")
            after_digest = render(items, after, start=date(2026, 9, 25), days=1)
            require(after_digest == render(items, list(reversed(after)),
                                           start=date(2026, 9, 25), days=1),
                    "Digest depends on API record order")
            require(before_digest.count("+ [calendar]") == 2
                    and after_digest.count("- [calendar]") == 2, "Rendered state is incorrect")
            require(len(after) == 3, "Record count changed")
    return {
        "kind": "synthetic_inputs_new_local_http_execution",
        "provenance": {"historical_reexecution": False,
                       "inputs": "examples/fictional_courses/DEMO101_FALL.json plus one fictional manual todo",
                       "transport": "Real HTTP on an ephemeral loopback server; disposable store removed",
                       "note": "UUIDs and audit timestamps are generated anew on every run; digest dates are fixed"},
        "sync_runs": [first, second, third],
        "verified_ids": [t["id"] for t in readbacks],
        "checks": {"no_duplicates": True, "two_exact_id_readbacks": True,
                   "due_dates_preserved": True, "completion_survives_sync": True,
                   "unrelated_item_unchanged": True, "deterministic_digest": True},
        "before_digest": before_digest, "after_digest": after_digest,
        "http_counts": dict(Counter(row["method"] for row in requests)),
        "http_exchanges": requests,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, default=Path("state/demo_trace.json"))
    args = parser.parse_args()
    destination = args.trace.resolve()
    if (destination == ROOT / "examples" or ROOT / "reference" in destination.parents
            or destination.name.startswith("historical_trace.")):
        raise ValueError("Do not overwrite prepared evidence")
    trace = run_demo()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(trace, indent=2) + "\n", encoding="utf-8")
    print(trace["before_digest"])
    print(trace["after_digest"])
    print(json.dumps({"checks": trace["checks"], "http_counts": trace["http_counts"],
                      "sync_created": [r["created"] for r in trace["sync_runs"]],
                      "trace": str(args.trace)}, indent=2))


if __name__ == "__main__":
    main()
