# Verification and boundaries

Independent parent verification used the portable files, not the archived commands or delivery scripts.

## Original prepared checks

```text
uv run --frozen python -m unittest discover -s tests -v
Ran 7 tests in 1.548s
OK

uv run --frozen python -m todo_example.demo
HTTP exchanges: POST=3, GET=10, PUT=2
Records created across three syncs: [2, 0, 0]
All six demo checks passed.
```

The demo used a disposable store and an OS-selected loopback port. It separately read both exact task IDs after completion and verified unchanged due dates, stable completion after another sync, no duplicates, an unchanged unrelated todo, and deterministic digest output. Both linked assignment lines changed from pending `+ [calendar]` to completed `- [calendar]`.

Privacy preflight and an independent comparison against the parent's pre-delegation hashes confirmed all eight prepared historical/reference evidence files were unchanged. Pattern scans found no configured secret patterns. These are heuristic checks plus review of an explicit source allowlist, not a guarantee about arbitrary future additions.

## Standalone scheduling checks (2026-11-17)

```text
uv run --frozen python -m unittest discover -s tests -v
Ran 11 tests
OK

uv run --frozen python -m todo_example.demo
All six demo checks passed; sync-created counts: [2, 0, 0].

bash -n scripts/calendar_digest_run.sh
crontab -n deploy/calendar-digest.crontab.example
Shell syntax and user-crontab syntax passed.

uv run --frozen python scripts/privacy_check.py
All eight immutable evidence hashes match; no configured patterns found.
```

The four scheduling tests invoke the actual shell entry point with a minimal
environment from outside the repository root, against disposable loopback
stores. They cover repeated sync without duplicates, completion and unrelated
record preservation, rolling dates in an explicit timezone, invalid input and
API failure preserving the previous digest, and overlap skipping followed by
a successful next run. A separate smoke check executed the crontab example's
command using the default `.venv`, substituting disposable output/log paths,
an ephemeral loopback API and the fixture date. It created two linked todos and
the expected digest. No installed crontab or live service was changed.

## Authorship and scope

- GPT-6.1 Sol implemented and checked the portable Python example and supporting API/usage documentation.
- GPT-6.1 Terra, configured with reasoning effort `max`, wrote `TECHNICAL_OVERVIEW.md` only. The parent reviewed the document against the source and linked it from the README.
- The parent prepared and sanitized the historical trace/reference inputs, independently ran the tests/demo, reviewed source/docs, and assembled the distribution.

No live personal tasks or calendar records were changed. No Discord messages were posted. No Google/Discord credentials, private stores, session databases, hidden reasoning, or full environment configuration are included. Package installation may use PyPI; the demo's HTTP traffic is loopback only.

This is a working local teaching adaptation, not a complete deployment export: the original upstream course collectors/proxy, Google OAuth setup, and external message delivery are outside the portable runtime. An optional harness-independent scheduling command and user-crontab example are documented in [Scheduling](SCHEDULING.md). Sanitized reference scripts show the original integration code for study, but must not be used as the quickstart. The repository is published on GitHub, and the owner subsequently selected the [MIT License](../LICENSE).
