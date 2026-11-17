# Scheduling sync and digest

The maintained scheduling entry point is
[`scripts/calendar_digest_run.sh`](../scripts/calendar_digest_run.sh). It runs
`todo_example.job` once using the repository's prepared Python environment.
Ordinary cron, a systemd timer, or another scheduler can invoke the same command.
It has no agent framework dependency and does not load a harness configuration,
home-directory credential files, or an LLM provider.

This adapts the original sync-then-digest sequence. The sanitized wrapper in
`reference/` records the older deployment and is preserved as historical
evidence; it is not the maintained entry point.

## Prepare and run once

The scheduling wrapper requires Bash and Unix advisory file locking (Linux or
macOS), Python 3.11+, and timezone data. Prepare the environment once from the
repository root:

```sh
uv sync --frozen --python /usr/bin/python3
mkdir -p state
```

Use your installed interpreter path if it differs. Dependency installation may
contact the package registry. Scheduled ticks use `.venv/bin/python` directly
and do not install packages or run `uv`. To use a different prepared environment,
set `TODO_PYTHON` to its absolute Python executable path.

Start the local API in another terminal, keeping one server process per store:

```sh
.venv/bin/python -m todo_example.server --data-file state/practice-todos.json --port 8765
```

Then run one job from the repository root:

```sh
./scripts/calendar_digest_run.sh --courses examples/fictional_courses --output state/calendar-digest.md --timezone America/Chicago --start 2026-09-25
cat state/calendar-digest.md
```

The fixture uses fixed dates. Omit `--start` for a rolling window starting today
in `--timezone`, and use your own current normalized course snapshots for an
ongoing schedule. The default window is seven days; `--days` accepts 1 through
31. The default API is `http://127.0.0.1:8765`; `--base-url` can select another
literal loopback HTTP endpoint. The job uses this repo's structured-link API and
input format, with no automatic migration of a legacy deployment's store.

The equivalent direct command is:

```sh
.venv/bin/python -m todo_example.job --courses examples/fictional_courses --output state/calendar-digest.md --timezone America/Chicago
```

For direct module execution, run from the repository root. The shell wrapper
finds its repository and changes there, so it also works from cron's working
directory. Relative input/output arguments to the wrapper are relative to the
repository. Absolute paths are recommended for scheduled use.

## Configure user cron

Copy the entry from
[`deploy/calendar-digest.crontab.example`](../deploy/calendar-digest.crontab.example)
into `crontab -e`, replacing every `/path/to/agent-todo-calendar-example` with
your checkout path. Merge it with existing jobs. The example runs every fifteen
minutes and appends errors to `state/calendar-digest-cron.log`. Create `state/`
first so the shell can open the log before starting the command. If a path has
spaces, quote it in the cron entry.

Cron must be available and running. The API must remain running independently;
the job does not start a server or collect course data. The cron cadence uses
the scheduler's clock; `--timezone` controls the digest's dates and displayed
times. Update the course snapshots through your own collector, using the
[input contract](API.md). To stop scheduled runs, remove just this entry with
`crontab -e`. Keep or rotate the error log as appropriate for your machine.

## Run and failure behavior

1. Validate the date window, timezone and API URL, then acquire the lock next to
   the output file (`calendar-digest.md.lock` in the example).
2. Load and validate one course snapshot, then reuse it for both sync and digest.
3. Sync missing or changed course todos through HTTP, preserving completion and
   archived records. Read todos back for rendering.
4. Render to a temporary file beside the output, then atomically replace it.

Successful runs and skipped overlapping ticks are silent and exit zero. Other
failures exit nonzero with a message on stderr. The previous successful digest
remains available when input validation, the API, rendering, or replacement
fails. Check the error log and file modification time when diagnosing freshness.
Temporary output is cleaned up on ordinary failures; a killed process can leave
a temporary file, but releases its lock automatically. Do not delete the lock
file while jobs may be running.

The lock coordinates jobs targeting the same resolved output path. Use one job
per store; different output paths, manual syncs and other API clients do not
share that lock. Sync is still a sequence of HTTP requests, not a transaction:
a failure can leave some successful upserts even though the digest stays old.
Rerunning converges by stable course/source links. The snapshot loader does not
provide a transaction across files; collectors should publish complete inputs
before starting a job.

Keep output and logs under ignored `state/` or another private runtime directory,
separate from course inputs and the server's JSON store. The output is local
Markdown; sending it to a chat or calendar requires a separate adapter. The
maintained code contains no external message-delivery or credential discovery.
