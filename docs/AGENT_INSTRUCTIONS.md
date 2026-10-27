# Instructions for any HTTP- or shell-capable agent

These instructions describe the portable example. No harness-specific skill,
plugin, memory, token discovery, or delivery tool is required.

1. Resolve intent before a write. "Complete these calendar events" means updating
   their linked todos when that link is established. It does not mean deleting
   todos, moving due dates, or writing to an external calendar.
2. List current todos, including completed ones, and inspect candidate full
   titles. Match the full course identifier, full assignment title, and structured
   `link.course` plus `link.source_id`. A title substring is a search aid, not an
   identity. Source IDs alone can collide between courses. Do not infer the
   current todo ID from IDs in either example trace.
3. When there are multiple plausible matches, no linked match, or a mismatch
   between the user's wording and source identity, ask a focused clarification
   before writing. "Quiz" alone does not identify a course or module. Do not
   silently create a replacement, reopen an archive, or bulk-complete candidates.
4. For each resolved todo ID, send only `{"completed":true}` using
   `PUT /todos/{id}`. An already completed record needs no change. Completion
   keeps the record and date. Archive is a separate, explicit operation; deletion
   is not supported by the portable API.
5. GET each exact ID afterward. Verify full title and link, `completed: true`,
   a nonempty `completed_at`, and unchanged `due_date`, `created_at`, and archive
   status. Compare relevant unrelated records when performing a batch. A PUT
   response alone is weaker evidence than separate readback.
6. If the user requested a rendered preview, render locally with an explicit
   start date and timezone, then check the requested lines. `+` means pending
   and `-` means completed in this example. Report the actual checks and any
   failed verification. A source snapshot or rendered line does not prove a
   Google event write or Discord delivery.
7. Do not send unsolicited messages or refresh external delivery channels.
   Local digest rendering has no delivery side effects. External integrations
   require a separately implemented adapter and explicit user authorization.

Good: list full candidates, identify `DEMO101_FALL` / `demo-quiz-001`, update its
returned todo ID, GET the same ID, and report the verified state.

Bad: mark every title containing "Module 2" done; treat `demo-quiz-001` as a
globally unique todo ID; clear `due_date`; delete/recreate a todo to complete it;
execute historical SSH or delivery commands; claim an external calendar was
changed because the local digest changed.

Use [tool_schemas.json](tool_schemas.json) with the dispatcher in
[API.md](API.md), or make the documented HTTP calls directly. Tool schemas do
not confer permission to write: resolve scope and identity first.
