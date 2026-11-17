"""Run the actual cron entry point against disposable loopback state."""
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from todo_example.client import Client
from todo_example.demo import ROOT, local_server


@unittest.skipUnless(os.name == "posix", "The cron entry point uses Bash and Unix file locking")
class JobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".test-", dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data_file = self.root / "todos.json"
        self.server_context = local_server(self.data_file)
        self.base_url = self.server_context.__enter__()
        self.addCleanup(self.server_context.__exit__, None, None, None)
        self.client = Client(self.base_url)
        self.courses = self.root / "course inputs"
        self.courses.mkdir()
        fixture = (ROOT / "examples/fictional_courses/DEMO101_FALL.json").read_text()
        (self.courses / "course.json").write_text(fixture)
        self.output = self.root / "job state" / "digest.md"
        self.environment = {"PATH": "/usr/bin:/bin", "HOME": str(self.root),
                            "TODO_PYTHON": sys.executable}

    def run_job(self, *extra):
        return subprocess.run(
            [str(ROOT / "scripts/calendar_digest_run.sh"),
             "--courses", str(self.courses), "--output", str(self.output),
             "--base-url", self.base_url, *extra],
            cwd=self.root, env=self.environment, text=True, capture_output=True, timeout=15)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_cron_entry_point_syncs_and_preserves_completion_on_rerun(self):
        manual = self.client.create({"title": "Keep this manual todo", "due_date": "2026-09-25"})
        options = ("--start", "2026-09-25", "--days", "1", "--timezone", "America/Chicago")
        self.assert_success(self.run_job(*options))
        self.assertEqual(self.output.read_text().count("+ [calendar]"), 2)
        todo = next(t for t in self.client.list("all") if t["link"])
        self.client.update(todo["id"], {"completed": True})
        completed = self.client.get(todo["id"])
        self.assert_success(self.run_job(*options))
        digest = self.output.read_text()
        self.assertEqual(digest.count("+ [calendar]"), 1)
        self.assertEqual(digest.count("- [calendar]"), 1)
        self.assertIn("Keep this manual todo", digest)
        self.assertEqual(len(self.client.list("all")), 3)
        self.assertEqual(self.client.get(todo["id"]), completed)
        self.assertEqual(self.client.get(manual["id"]), manual)
        self.assert_success(self.run_job(*options))
        self.assertEqual(self.output.read_text(), digest)

    def test_rolling_window_uses_today_in_the_requested_timezone(self):
        before = datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
        self.assert_success(self.run_job("--timezone", "Pacific/Kiritimati", "--days", "2"))
        after = datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
        digest = self.output.read_text()
        self.assertIn(digest.splitlines()[0],
                      {f"# Schedule from {day.isoformat()} (2 days)" for day in (before, after)})
        self.assertIn("Times: Pacific/Kiritimati.", digest)

    def test_failures_preserve_previous_digest_and_invalid_inputs_do_not_sync(self):
        self.output.parent.mkdir()
        self.output.write_text("Last good digest\n")
        self.client.create({"title": "Unrelated"})
        original_store = self.data_file.read_bytes()
        for options in (("--days", "0"), ("--timezone", "Invalid/Timezone"),
                        ("--start", "9999-12-31", "--days", "2")):
            with self.subTest(options=options):
                result = self.run_job(*options)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Calendar job failed:", result.stderr)
                self.assertEqual(self.output.read_text(), "Last good digest\n")
                self.assertEqual(self.data_file.read_bytes(), original_store)
        (self.courses / "broken.json").write_text("{broken")
        result = self.run_job()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.data_file.read_bytes(), original_store)
        self.assertEqual(self.output.read_text(), "Last good digest\n")
        (self.courses / "broken.json").unlink()
        self.data_file.write_text("{broken")
        result = self.run_job()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.output.read_text(), "Last good digest\n")
        self.assertEqual(self.data_file.read_text(), "{broken")

    def test_overlapping_tick_skips_then_next_tick_can_run(self):
        import fcntl

        self.output.parent.mkdir()
        self.output.write_text("Previous digest\n")
        with self.output.with_name("digest.md.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assert_success(self.run_job("--start", "2026-09-25"))
            self.assertEqual(self.output.read_text(), "Previous digest\n")
            self.assertEqual(self.client.list("all"), [])
        self.assert_success(self.run_job("--start", "2026-09-25"))
        self.assertEqual(len(self.client.list("all")), 2)
        self.assertIn("+ [calendar]", self.output.read_text())
        self.assertEqual(list(self.output.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
