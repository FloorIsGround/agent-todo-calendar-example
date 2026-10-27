# Local API and normalized input contract

Start one server with `uv run python -m todo_example.server`. Defaults are
`http://127.0.0.1:8765` and `state/todos.json`, relative to the working directory.
Use `--data-file` and `--port` to isolate runs. There is no home-directory or
credential discovery. The client, sync, and digest accept `--base-url` for a
different loopback port. They disable environment proxies and HTTP redirects.

## Todo endpoints

| Operation | Request | Behavior |
| --- | --- | --- |
| Health | `GET /health` | Checks store readability, returns `{"status":"ok"}` |
| List | `GET /todos?filter=current&q=Module` | Title/description substring search |
| Read exact ID | `GET /todos/{id}` | One record, or 404 |
| Create | `POST /todos` | 201 with generated UUID; persists supplied due date |
| Partial update | `PUT /todos/{id}` | Only supplied mutable fields change |
| Archive/restore | `PUT /todos/{id}/archive` | `{"archived":true}` or `false` |

List filters: `current` is non-archived, including completed; `active` is
non-archived and incomplete; `completed` excludes archives; `archived` includes
only archives; `all` includes every record. Invalid filters or request bodies
return 422. Completion is separate from archive. DELETE is not provided.

POST accepts these fields (only `title` is required):

```json
{
  "title": "DEMO101_FALL - Module 2: Quiz",
  "description": "Imported from fictional course JSON.",
  "category": "college",
  "completed": false,
  "due_date": "2026-09-25",
  "link": {"course": "DEMO101_FALL", "source_id": "demo-quiz-001"}
}
```

Manual todos omit `link`. A link is structured identity, independent of title
or description, and cannot be edited via PUT. Creating a duplicate course/source
pair returns 409 even when the original is archived. Different courses may use
the same source ID. Responses include `id`, the POST fields, `completed_at`,
`archived`, `archived_at`, `created_at`, and `updated_at`. Audit timestamps are
UTC ISO datetimes. All IDs and timestamps are assigned by the service.

PUT accepts `title`, `description`, `category`, `completed`, and `due_date`.
Omitted fields stay unchanged. Only `due_date` can be cleared with JSON `null`.
Booleans must be JSON booleans. Empty updates, blank titles, unknown fields,
identity edits, invalid dates, and null completion flags are rejected. A repeated
identical update preserves audit timestamps. Reopening completion sets
`completed_at` to null. A later completion sets a new timestamp.

Writes serialize inside one process and replace the store atomically. Missing
stores start empty. Corrupt/invalid existing stores cause HTTP 500 and are not
silently replaced. The store is the portable API's JSON array format, not an
importer for reference-format data.

## Course JSON

Use one or more `*.json` files in an explicit directory. For example:

```json
{
  "displayId": "DEMO101_FALL",
  "source": "fictional-course-export",
  "dueDateItems": [
    {
      "itemSourceId": "demo-quiz-001",
      "title": "Module 2: Quiz",
      "eventType": "Quiz",
      "endDate": "2026-09-25T23:59:00-05:00"
    }
  ]
}
```

The accepted top-level fields are `displayId`, `source` (default `local`),
`dueDateItems`, and `calendarItems`. Prefer nonempty `dueDateItems`, otherwise
use `calendarItems`, following the reference's selection rule. The lists are
not merged. Item fields are `itemSourceId`, `title`, `startDate`, `endDate`,
`eventType`, `description`, and `handle`. Unknown fields are rejected; normalize
upstream exports before handing them to this boundary. Both title and stable
source ID are required. A changed course ID or source ID denotes a new identity;
no fuzzy title-based migration is attempted.

All files are loaded and validated before HTTP writes. An absent directory,
no JSON files, empty snapshot, malformed JSON, invalid item, duplicate pair,
missing date, or naive datetime aborts the run. Duplicate source IDs across
different courses are allowed. Selected items use `endDate` as the due time,
falling back to `startDate`. Dates may be `YYYY-MM-DD`; datetimes must carry an
offset or `Z`. The todo due date retains the calendar day in the source's offset;
the digest converts timed entries to its explicit display timezone. Those days
can differ near midnight if different timezones are selected.

Actionable event types follow the reference: Assignment, Test, Quiz, Exam, Lab,
Project, Homework, Discussion, Task, Module, Unit, Worksheet. Otherwise use the
reference's title hints, excluding lecture/class/seminar/orientation/welcome/
introduction titles before the positive keyword fallback. Explicit actionable
types take priority. This is a simple heuristic, not course-domain intelligence.

Sync reads `filter=all`, matches `(displayId, itemSourceId)`, creates missing
records, and updates changed title/description/category/due-date metadata. It
preserves completion fields and original IDs. Archived matches are retained
without updates or restoration. Missing source items are retained with no
automatic archive. Concurrent syncs may encounter 409; rerun after the other
finishes. Sync is not an all-or-nothing multi-request transaction.

## Digest contract

This renders to stdout:

```sh
uv run python -m todo_example.digest --courses examples/fictional_courses --start 2026-09-25 --days 7 --timezone America/Chicago
```

Start date is required; timezone defaults to
America/Chicago; days must be 1 through 31. Identical inputs and options yield
identical output, regardless of record ordering. The host clock and locale do
not select the window or format times.

Course lines use `[calendar]`; manual lines use `[todo]`. Completion is joined
by course/source pair. Archived todos and their linked course lines are hidden.
Unrepresented linked todos use `[linked todo absent from snapshot]`. Dated rows
outside the requested window are omitted by design; undated todos appear in a
separate section. No rows within these selections are silently truncated for a
Discord character cap. Titles are flattened to one line. Nothing is delivered.

## JSON tools and CLI mapping

`tool_schemas.json` is an array of generic JSON function definitions. A caller
registers the definitions with its own agent runtime, then maps each function
name and argument object to `Client.call_tool(name, arguments)` or this CLI:

```sh
uv run python -m todo_example.client tool todo_list --args '{"filter":"current","q":"DEMO101_FALL - Module 2: Quiz"}'
```

Good subsequent arguments after inspecting that response:

```json
{"todo_id":"COPY_EXACT_RETURNED_ID","fields":{"completed":true}}
```

Dispatch them to `todo_update`, then dispatch
`{"todo_id":"COPY_EXACT_RETURNED_ID"}` to `todo_get`. Replace the placeholder
with the exact UUID returned by the service. `todo_create` accepts `{"fields":{...}}`;
`todo_archive` accepts `{"todo_id":"...","archived":true}`. Tool responses are
the same JSON as HTTP responses. CLI errors exit nonzero. FastAPI's
`/openapi.json` also exposes the HTTP schema.

Bad arguments for `todo_update`:

```json
{"todo_id":"demo-quiz-001","fields":{"completed":"yes","due_date":null}}
```

The source ID is not a todo UUID, string booleans are invalid, and clearing a
date is an unrelated change. Another bad operation is selecting every substring
match and updating it without resolving the course/full title/source link.
Schemas check structure; the agent instructions govern semantic matching and
authorization. The dispatcher relies on the HTTP service for field validation.
