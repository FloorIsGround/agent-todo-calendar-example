# Technical overview

This repository shows how a request in ordinary language can become a small, verifiable change to a local todo service. A course assignment is represented by a todo, and its completion is reflected in a calendar-style text digest. Completing that todo does not complete the student's assignment or delete, complete, or otherwise modify a Google Calendar event.

The portable example runs without Hermes, T3, an agent framework, or an LLM account. An agent is optional: a shell, an HTTP client, or any harness capable of calling JSON functions can drive the same API. The [API contract](API.md) and [agent instructions](AGENT_INSTRUCTIONS.md) describe the operations and the matching rules.

```text
User's request -> optional agent harness -> JSON tool calls / HTTP client
                                               |
Normalized course JSON -> sync -> local todo API -> JSON store
                                               |
                      course JSON + todo GET -> digest -> local text
                                               |
                         exact-ID GET + rendered-line checks -> verification
```

## From request to verified state

Suppose a user asks to complete two named course items. The harness lists current todos, which include completed but not archived records, and inspects their full titles and links. A substring search is only a way to find candidates. Before changing anything, compare the course identifier, assignment title, and course/source link; ask for clarification if the match is ambiguous. The tool schemas describe argument shapes, but they do not establish the user's intent or authorize a write.

For each resolved record, use the UUID returned by the service, not the course source ID. Send `PUT /todos/{id}` with only `{"completed": true}`, then make a separate `GET /todos/{id}`. Check the same ID, title and link, a true `completed` value, and a nonempty `completed_at`; compare the due date, creation time, and archive status to their prior values. A PUT response shows what the write returned, while a later exact-ID GET independently reads the stored record. For a batch, also check relevant unrelated records. If a rendered preview was requested, check the corresponding digest lines as well: `+` means pending and `-` means completed.

The generic definitions in [tool_schemas.json](tool_schemas.json) name `todo_list`, `todo_get`, `todo_create`, `todo_update`, and `todo_archive`. A host can register them and map each name and JSON argument object to `Client.call_tool()`. That dispatcher sends ordinary HTTP requests; it is not an agent itself. Direct HTTP and the command-line client are equally valid. Completion and archiving are separate operations, and the portable service has no deletion endpoint.

## Input, identity, and time

The upstream collector is outside this repository. The input boundary is one or more normalized course JSON files, such as [the fictional fixture](../examples/fictional_courses/DEMO101_FALL.json):

```json
{
  "displayId": "DEMO101_FALL",
  "source": "fictional-course-export",
  "dueDateItems": [{
    "itemSourceId": "demo-quiz-001",
    "title": "Module 2: Quiz",
    "eventType": "Quiz",
    "endDate": "2026-09-25T23:59:00-05:00"
  }]
}
```

`displayId` identifies the course; `source` describes the export. The item has a stable `itemSourceId`, title, type, and date. A nonempty `dueDateItems` list takes precedence over `calendarItems`; they are not merged. The loader validates all files before sync writes and uses event types or title hints to select actionable items. `endDate` is preferred as the due time, with `startDate` as a fallback.

Sync creates a todo with a separate service-generated `id`, a course-prefixed `title`, `description`, `category`, and `due_date`. Its structured, immutable link is `{"course": "DEMO101_FALL", "source_id": "demo-quiz-001"}`. The pair is unique even across archived records; the same source ID may occur in another course. Manual todos have no link. A historical record instead placed `itemSourceId` inside its description; the portable service does not automatically parse or migrate those legacy descriptions.

Todo responses also include `completed`, `completed_at`, `archived`, `archived_at`, `created_at`, and `updated_at`. Audit timestamps are UTC. An omitted field in an update is preserved; an explicit `null` clears only `due_date`. Completing a todo preserves its due date and identity. Repeating an identical update also preserves audit timestamps.

Dates may be calendar dates or offset-aware datetimes; naive datetimes are rejected. The stored todo due date uses the calendar day in the source offset. The digest converts timed course items to its explicit display timezone, defaulting to `America/Chicago`, so a time near midnight can appear on a different day. Its start date and window are explicit, and sorted rows make output deterministic for the same inputs and options. Dated items outside the window are omitted; undated todos get their own section.

## Reconciliation, storage, and failures

Sync reads all todos, including archives, and matches the full course/source pair. It creates missing actionable items and updates changed title, description, category, or due date without changing completion or the todo UUID. Rerunning the same input does not create duplicates. Archived matches are left archived, and missing source items are retained rather than automatically archived. A dry run reports intended changes without writing.

Malformed, empty, missing, duplicate, or undated course input fails before writes. A duplicate link returns HTTP 409, an unknown ID 404, and invalid request fields 422. An unreadable or corrupt existing store returns 500 instead of being silently replaced. Individual writes use an in-process lock and atomic file replacement, but a sync comprises multiple requests and is not a transaction. A failure can leave some successful writes; inspect the result and rerun to converge. Concurrent syncs can conflict and need a rerun.

The service is a single-user teaching tool with no authentication. It binds to loopback, but other local processes can still access it. The client accepts literal loopback HTTP addresses and disables proxies and redirects. Use one server process per store, keep practice data backed up, and keep runtime data, credentials, virtual environments, and caches out of public archives. The privacy checker is a heuristic, not a privacy certification.

## Portable files

- [todo_example/server.py](../todo_example/server.py): `create_app()` exposes health, list, exact read, create, partial update, and archive/restore endpoints. `Store.load()` validates the JSON array; `Store.save()` replaces it atomically.
- [todo_example/client.py](../todo_example/client.py): `Client` implements loopback HTTP methods and `call_tool()`; `main()` provides the JSON-printing CLI and nonzero error exits.
- [todo_example/courses.py](../todo_example/courses.py): `load_courses()` validates snapshots, `parse_when()` handles dates and offsets, and `actionable()` applies the import heuristic.
- [todo_example/sync.py](../todo_example/sync.py): `reconcile()` compares validated items with all stored links and issues only needed create or metadata update requests. `--dry-run` still reads the API.
- [todo_example/digest.py](../todo_example/digest.py): `render()` joins course items to todo completion by the full link, includes manual and unrepresented linked todos, sorts the selected window, and returns text. It does not deliver messages.
- [todo_example/demo.py](../todo_example/demo.py): `local_server()` starts a disposable loopback server; `run_demo()` syncs fictional inputs, completes two linked records, reads them back, checks preservation, and renders before/after text. The default trace output is `state/demo_trace.json`.
- [todo_example/__init__.py](../todo_example/__init__.py) identifies the package. [tests/test_example.py](../tests/test_example.py) defines disposable-store and loopback HTTP checks for validation, reconciliation, dates, identity, digest output, and tool dispatch. [scripts/privacy_check.py](../scripts/privacy_check.py) checks configured text patterns and stored evidence hashes; it cannot prove that future content is safe to publish.

## Sanitized reference scripts

The files in [reference/](../reference/) are later sanitized source snapshots, not necessarily the exact historical revision and not the portable quickstart. They illustrate the original design and its limitations. Do not run their delivery scripts.

- [reference/todo_server.py](../reference/todo_server.py): the original FastAPI service offers list, create, update, archive, delete, and installer routes. Its `create_todo()` accepts but drops `due_date`, and `_load()` can treat invalid storage as empty. The portable server changes those behaviors.
- [reference/course_todo_sync.py](../reference/course_todo_sync.py): `load_course_items()` reads proxy snapshots, `is_actionable()` filters them, and `reconcile()` creates or archives todos. It extracts source IDs from descriptions and queries only current records, matching by source ID alone despite its per-course deduplication claim. Missing or malformed snapshots can lead to unintended archiving.
- [reference/google_calendar_7day_digest.py](../reference/google_calendar_7day_digest.py): `fetch_events()` reads Google Calendar, while `fetch_course_items()`, `fetch_todos()`, and `make_digest()` merge sources and apply completion markers. `deliver_digest()` deletes the previous Discord message before posting a new one; a failed post can leave no previous message. Its reference Google access is read-only.
- [reference/todo_digest.py](../reference/todo_digest.py): `fetch_todos()` excludes course-linked descriptions, `format_digest()` groups remaining current todos, and `deliver_digest()` uses Discord delete/repost. It skips delivery when the content hash is unchanged; its length-limiting formatter can silently omit items.
- [reference/calendar_digest_run.sh](../reference/calendar_digest_run.sh): the original shell wrapper runs the course sync, then generates and delivers the seven-day digest, stopping on a command failure.

Google credential handling and Discord delivery occur only in reference code, not in the portable package. See [reference differences](REFERENCE_DIFFERENCES.md) for the full comparison and integration boundaries.

## Evidence and running the example

[The historical trace](../examples/historical_trace.json) is a real, transformed completion turn: identifiers are pseudonymized, dates shifted, and some material omitted. It records two todo completion PUT responses, then two failed verification commands before a successful Discord message GET showed both rendered lines complete. It contains no separate exact-ID todo GET after the writes. The historical commands are archival data and must not be executed; the excerpt does not establish a Google event write or that the assignments were done.

[The stored demo trace](../examples/demo_trace.json) is a separate, newly executed local HTTP demonstration using fictional inputs, not a replay of that historical system. Its recorded checks report two exact-ID readbacks, preserved due dates and unrelated state, no duplicates, completion surviving another sync, and deterministic digest output. These are recorded demonstration results, not a claim about current service health.

With Python 3.11+, `uv`, and timezone data available, the [README](../README.md) gives these commands from the repository root. Dependency installation may contact a package registry; the example's runtime HTTP stays on loopback.

```sh
export UV_CACHE_DIR="$PWD/.uv-cache"
uv sync --python /usr/bin/python3
uv run python -m unittest discover -s tests -v
uv run python -m todo_example.demo
uv run python scripts/privacy_check.py
```

Use a different Python path if needed. The demo removes its disposable store and writes a new local trace; the README also documents running the server, sync, client, and digest individually. The project's code and documentation are licensed under the [MIT License](../LICENSE); third-party dependencies retain their respective licenses.
