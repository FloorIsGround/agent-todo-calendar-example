"""Boundary/regression checks using disposable stores and real loopback HTTP."""
import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

from todo_example.client import Client
from todo_example.courses import load_courses
from todo_example.demo import ROOT, local_server
from todo_example.digest import render
from todo_example.server import Store, link_key
from todo_example.sync import reconcile


class ExampleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".test-", dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data_file = self.root / "todos.json"
        self.server_context = local_server(self.data_file)
        self.base_url = self.server_context.__enter__()
        self.addCleanup(self.server_context.__exit__, None, None, None)
        self.client = Client(self.base_url)
        self.courses = self.root / "courses"
        self.courses.mkdir()
        self.fixture = json.loads((ROOT / "examples/fictional_courses/DEMO101_FALL.json").read_text())
        self.write_course(self.fixture)

    def write_course(self, value, name="course.json"):
        (self.courses / name).write_text(json.dumps(value))

    def assert_http(self, status, function, *args):
        with self.assertRaises(HTTPError) as error:
            function(*args)
        self.assertEqual(error.exception.code, status)

    def test_post_dates_partial_update_and_completion_are_preserved(self):
        todo = self.client.create({"title": "Manual task", "due_date": "2026-09-25"})
        self.assertEqual(todo["due_date"], "2026-09-25")  # Raw reference POST loses this.
        done = self.client.update(todo["id"], {"completed": True})
        self.assertEqual(done["due_date"], todo["due_date"])
        self.assertTrue(done["completed_at"])
        self.assertEqual(done, self.client.update(todo["id"], {"completed": True}))
        self.assertEqual(done, self.client.get(todo["id"]))
        cleared = self.client.update(todo["id"], {"due_date": None})
        self.assertIsNone(cleared["due_date"])
        self.assertEqual(cleared["completed_at"], done["completed_at"])
        self.assertIsNone(self.client.update(todo["id"], {"completed": False})["completed_at"])

    def test_validation_and_no_delete(self):
        self.assert_http(422, self.client.create, {"title": "   "})
        self.assert_http(422, self.client.create, {"title": "x", "due_date": "tomorrow"})
        todo = self.client.create({"title": "x"})
        for fields in ({}, {"completed": "true"}, {"completed": None}, {"title": None},
                       {"id": "other"}, {"link": None}):
            self.assert_http(422, self.client.update, todo["id"], fields)
        self.assert_http(404, self.client.get, "missing")
        self.assert_http(405, self.client.request, "DELETE", "/todos/" + todo["id"])
        self.assert_http(422, self.client.list, "unknown")

    def test_sync_course_collision_completion_rename_and_archive(self):
        other = copy.deepcopy(self.fixture)
        other["displayId"] = "DEMO202_FALL"  # Same raw IDs, different course.
        self.write_course(other, "other.json")
        dry_run = reconcile(self.client, self.courses, dry_run=True)
        self.assertEqual(dry_run["created"], 4)
        self.assertEqual(self.client.list("all"), [])
        self.assertEqual(reconcile(self.client, self.courses)["created"], 4)
        self.assertEqual(reconcile(self.client, self.courses)["created"], 0)
        records = {link_key(t): t for t in self.client.list("all")}
        todo = records[("DEMO101_FALL", "demo-lab-001")]
        done = self.client.update(todo["id"], {"completed": True})
        unrelated = records[("DEMO202_FALL", "demo-lab-001")]
        self.fixture["dueDateItems"][0]["title"] = "Module 2: Renamed Lab"
        self.write_course(self.fixture)
        result = reconcile(self.client, self.courses)
        changed = self.client.get(todo["id"])
        self.assertEqual(result["updated"], 1)
        self.assertTrue(changed["completed"])
        self.assertEqual(changed["completed_at"], done["completed_at"])
        self.assertEqual(changed["due_date"], "2026-09-25")  # End date, source offset day.
        self.assertEqual(self.client.get(unrelated["id"]), unrelated)
        self.client.archive(todo["id"], True)
        self.assertEqual(reconcile(self.client, self.courses)["archived_matches"], 1)
        self.assertEqual(len(self.client.list("all")), 4)
        self.assertEqual(len(self.client.list()), 3)
        self.assert_http(409, self.client.create, {"title": "duplicate", "link": todo["link"]})
        restored = self.client.archive(todo["id"], False)
        self.assertTrue(restored["completed"])
        self.assertEqual(restored["id"], todo["id"])

    def test_bad_inputs_fail_before_writes_and_disappearance_never_archives(self):
        reconcile(self.client, self.courses)
        original = self.data_file.read_bytes()
        bad_values = [{}, {"displayId": "X", "dueDateItems": []},
                      {"displayId": "X", "dueDateItems": "wrong type"}]
        for mutate in ("missing_id", "bad_date", "naive_datetime", "duplicate"):
            value = copy.deepcopy(self.fixture)
            item = value["dueDateItems"][0]
            if mutate == "missing_id":
                del item["itemSourceId"]
            elif mutate == "bad_date":
                item["endDate"] = "not a date"
            elif mutate == "naive_datetime":
                item["endDate"] = "2026-09-25T23:59:00"
            else:
                value["dueDateItems"].append(copy.deepcopy(item))
            bad_values.append(value)
        for value in bad_values:
            self.write_course(value, "bad.json")
            with self.assertRaises(ValueError):
                reconcile(self.client, self.courses)
            self.assertEqual(self.data_file.read_bytes(), original)
        (self.courses / "bad.json").write_text("{broken")
        with self.assertRaises(ValueError):
            reconcile(self.client, self.courses)
        self.assertEqual(self.data_file.read_bytes(), original)
        (self.courses / "bad.json").unlink()
        (self.courses / "course.json").unlink()
        with self.assertRaises(ValueError):
            reconcile(self.client, self.courses)
        self.assertEqual(self.data_file.read_bytes(), original)
        self.fixture["dueDateItems"].pop()
        self.write_course(self.fixture)
        self.assertEqual(reconcile(self.client, self.courses)["archived"], 0)
        self.assertEqual(self.data_file.read_bytes(), original)

    def test_corrupt_store_is_not_overwritten_and_new_store_reads_disk(self):
        todo = self.client.create({"title": "persisted"})
        self.assertEqual(Store(self.data_file).load(), [todo])
        for content in ("{broken", "{}", '[{"title":"incomplete"}]'):
            self.data_file.write_text(content)
            self.assert_http(500, self.client.create, {"title": "must not replace data"})
            self.assertEqual(self.data_file.read_text(), content)

    def test_digest_is_deterministic_and_completion_uses_course_plus_source(self):
        other = copy.deepcopy(self.fixture)
        other["displayId"] = "DEMO202_FALL"
        self.write_course(other, "other.json")
        reconcile(self.client, self.courses)
        todo = next(t for t in self.client.list() if t["link"]["course"] == "DEMO101_FALL")
        self.client.update(todo["id"], {"completed": True})
        for index in range(80):
            self.client.create({"title": f"Manual task {index:02d}", "due_date": "2026-09-25"})
        self.client.create({"title": "Undated task"})
        todos = self.client.list("all")
        items = load_courses(self.courses)
        digest = render(items, todos, start=date(2026, 9, 25), days=1)
        self.assertEqual(digest.count("- [calendar]"), 1)
        self.assertEqual(digest.count("+ [calendar]"), 3)
        self.assertIn("11:59 PM: Module 2: Lab Assignments", digest)  # End, not availability start.
        self.assertEqual(digest.count("+ [todo] Manual task"), 80)  # No reference-style truncation.
        self.assertIn("Undated task", digest)
        self.assertEqual(digest, render(list(reversed(items)), list(reversed(todos)),
                                        start=date(2026, 9, 25), days=1))

    def test_client_refuses_remote_urls_and_schema_dispatch_matches(self):
        for base in ("https://127.0.0.1", "http://example.com", "http://127.0.0.1/extra",
                     "http://user:password@127.0.0.1", "http://127.0.0.1?x=1"):
            with self.assertRaises(ValueError):
                Client(base)
        schemas = json.loads((ROOT / "docs/tool_schemas.json").read_text())
        self.assertEqual({s["function"]["name"] for s in schemas},
                         {"todo_list", "todo_get", "todo_create", "todo_update", "todo_archive"})
        todo = self.client.call_tool("todo_create", {"fields": {"title": "tool test"}})
        self.assertEqual(self.client.call_tool("todo_get", {"todo_id": todo["id"]}), todo)
        changed = self.client.call_tool("todo_update", {"todo_id": todo["id"],
                                                       "fields": {"completed": True}})
        self.assertTrue(changed["completed"])
        self.assertEqual(len(self.client.call_tool("todo_list", {"filter": "completed"})), 1)
        self.assertTrue(self.client.call_tool("todo_archive", {"todo_id": todo["id"],
                                                               "archived": True})["archived"])


if __name__ == "__main__":
    unittest.main()
