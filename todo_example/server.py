"""One process, one JSON store. Run with: uv run python -m todo_example.server."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator

TodoFilter = Literal["current", "active", "completed", "archived", "all"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CourseLink(InputModel):
    course: str = Field(min_length=1)
    source_id: str = Field(min_length=1)


class TodoCreate(InputModel):
    title: str = Field(min_length=1)
    description: str = ""
    category: str = ""
    completed: StrictBool = False
    due_date: date | None = None
    link: CourseLink | None = None


class TodoUpdate(InputModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    category: str | None = None
    completed: StrictBool | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one field")
        for field in self.model_fields_set - {"due_date"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null; only due_date can be cleared")
        return self


class ArchiveChange(InputModel):
    archived: StrictBool


class Todo(TodoCreate):
    id: str = Field(min_length=1)
    completed_at: str | None = None
    archived: StrictBool = False
    archived_at: str | None = None
    created_at: str
    updated_at: str


def link_key(todo: dict) -> tuple[str, str] | None:
    link = todo.get("link")
    return (link["course"], link["source_id"]) if link else None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = RLock()

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("Store must contain a JSON array")
            todos = [Todo.model_validate(t).model_dump(mode="json") for t in raw]
            ids = [t["id"] for t in todos]
            keys = [link_key(t) for t in todos if t["link"]]
            if len(set(ids)) != len(ids) or len(set(keys)) != len(keys):
                raise ValueError("Duplicate stored ID or course/source link")
            return todos
        except (OSError, ValueError, ValidationError) as exc:
            raise HTTPException(500, "Store unreadable or corrupt; refusing to overwrite it") from exc

    def save(self, todos: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A rename prevents a partially written JSON file after interruption.
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".todos-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(json.dumps(todos, indent=2, ensure_ascii=False) + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)


def find(todos: list[dict], todo_id: str) -> dict:
    for todo in todos:
        if todo["id"] == todo_id:
            return todo
    raise HTTPException(404, "Todo not found")


def create_app(data_file: Path) -> FastAPI:
    app = FastAPI(title="Local Todo Teaching API", version="0.1.0")
    store = Store(data_file)

    @app.get("/health")
    def health():
        with store.lock:
            store.load()
        return {"status": "ok"}

    @app.get("/todos", response_model=list[Todo])
    def list_todos(filter: TodoFilter = Query("current"), q: str | None = None):
        with store.lock:
            todos = store.load()
        if filter != "all":
            todos = [t for t in todos if t["archived"] == (filter == "archived")]
        if filter in ("active", "completed"):
            todos = [t for t in todos if t["completed"] == (filter == "completed")]
        if q and q.strip():
            todos = [t for t in todos if q.strip().casefold() in
                     (t["title"] + " " + t["description"]).casefold()]
        return todos

    @app.get("/todos/{todo_id}", response_model=Todo)
    def get_todo(todo_id: str):
        with store.lock:
            return find(store.load(), todo_id)

    @app.post("/todos", response_model=Todo, status_code=201)
    def create_todo(body: TodoCreate):
        with store.lock:
            todos = store.load()
            fields = body.model_dump(mode="json")
            if fields["link"] and any(link_key(t) == link_key(fields) for t in todos):
                raise HTTPException(409, "Course/source link already exists, including archives")
            stamp = now()
            todo = Todo(**fields, id=str(uuid4()), created_at=stamp, updated_at=stamp,
                        completed_at=stamp if body.completed else None).model_dump(mode="json")
            todos.append(todo)
            store.save(todos)
            return todo

    @app.put("/todos/{todo_id}", response_model=Todo)
    def update_todo(todo_id: str, body: TodoUpdate):
        with store.lock:
            todos = store.load()
            todo = find(todos, todo_id)
            changes = body.model_dump(mode="json", exclude_unset=True)
            if any(todo[k] != v for k, v in changes.items()):
                stamp = now()
                if "completed" in changes and changes["completed"] != todo["completed"]:
                    todo["completed_at"] = stamp if changes["completed"] else None
                todo.update(changes)
                todo["updated_at"] = stamp
                store.save(todos)
            return todo

    @app.put("/todos/{todo_id}/archive", response_model=Todo)
    def archive_todo(todo_id: str, body: ArchiveChange):
        with store.lock:
            todos = store.load()
            todo = find(todos, todo_id)
            if todo["archived"] != body.archived:
                stamp = now()
                todo.update(archived=body.archived,
                            archived_at=stamp if body.archived else None, updated_at=stamp)
                store.save(todos)
            return todo

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-file", type=Path, default=Path("state/todos.json"))
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(create_app(args.data_file), host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
