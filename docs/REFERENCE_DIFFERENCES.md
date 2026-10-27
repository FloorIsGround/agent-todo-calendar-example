# Evidence and intentional portable changes

The immutable `reference/` directory contains allowlisted sanitized snapshots of
the real project. They are not installation scripts for this repo and are not
guaranteed to be the historical revision. The immutable historical trace is a
real contiguous completion turn with pseudonyms, shifted dates, omissions, and
two failed verification attempts recorded in its own provenance.

The historical excerpt demonstrates linked-todo completion writes and final
Discord rendered-message readback. It has no separate exact-todo GET after the
writes and does not prove original collection or Google event writes. The
portable demo adds exact-ID GET verification. Its fictional data borrows the
historical pseudonyms; its generated HTTP trace is separate evidence of new
execution, with no claim to have reproduced the private environment.

| Reference behavior | Portable behavior and reason |
| --- | --- |
| FastAPI JSON service with create/list/read/update/archive/delete | Same basic records and filter meanings; create/read/update/archive only, no hard deletion or plugin installers |
| POST schema accepts `due_date` but create omits it | POST persists it; regression test verifies completion preserves it |
| Service binds all interfaces and derives a project data path | Loopback binding; explicit store path and port, task-local defaults |
| Corrupt or wrong-shaped store can load as empty | Invalid existing storage fails with 500; writes refuse to replace it |
| Direct file writes | Atomic replacement plus one-process request locking; still a single-user store |
| PUT only applies non-null dates | Omission preserves a date; explicit null clears it; other null fields fail |
| Raw sync reads current records and keys by extracted source ID alone | Structured immutable course/source pairs; queries all records, including archives; duplicate keys rejected |
| Raw sync docstring claims per-course deduplication | Do not attribute that claim to its implementation; same source IDs can collide across courses, and archived matches are invisible to its query |
| Missing source ID gets a title-derived fallback | Stable source IDs required; renamed titles preserve identity |
| Empty/malformed source files are skipped and absent items archived | All input validated first; missing/empty/corrupt inputs abort, and there is no auto-archive at all |
| Optional missing-date backfill on a matched item | Ordinary changed source metadata updates, with completion fields preserved; archived matches are skipped |
| Raw sync converts due dates to a UTC day, while digest prefers availability start | Todo date uses due/end date's source-offset day; digest uses due/end time in explicit display timezone |
| Calendar digest completion matches raw source IDs | Completion joins full course/source pairs, tested against collisions |
| Google fetch, token refresh, system timezone discovery, host/path footer | Local normalized course inputs, explicit date/timezone, no identity footer or credential discovery |
| Todo formatter can silently omit overflow | Selected local text output is complete with no service character cap |
| Reference Discord delivery deletes old messages and posts new ones | Rendering only, no delivery code in the portable runtime |

The raw calendar delivery section still has a stale "edit in place" comment;
its actual implementation uses DELETE then POST. The todo delivery script also
uses delete/repost (with unchanged-content detection), rather than PATCH.
Deleting before posting can lose the previous visible message if posting fails.
Do not copy stale delivery documentation or infer safe replacement semantics.

## Integration boundaries

The upstream collector/proxy is not bundled. Its output must be normalized to
the strict course JSON contract in `API.md`. This repo does not fetch LMS pages
or discover live course files. It does not migrate a reference-format store or
parse identity out of legacy descriptions; doing so requires an explicit,
reviewed migration with ambiguity handling.

Google Calendar would be a separate, opt-in adapter that maps authorized event
data to an explicit local format, with its own IDs, offsets, duplicate policy,
and verification. The reference includes Google read/refresh code for study,
but the portable package has no Google SDK, OAuth loading, or Google writes.
Completing a linked todo changes local state and rendered course lines only.

Discord would be a separate, opt-in text-delivery adapter with explicit target,
credential handling, length handling, failure recovery, and final message
readback. It is not included or enabled. Never discover tokens from home or
environment files or deliver merely because rendering succeeded.

The owner must choose licensing before public reuse. Inclusion of sanitized
source, evidence, or third-party dependency names is not a license grant.
