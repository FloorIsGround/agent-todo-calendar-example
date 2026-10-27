"""Todo Service - FastAPI backend with JSON file persistence.

Stores todos as a JSON array in data/todos.json. Auto-creates data/.
Archived tasks are retained but excluded from the default list view.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

app = FastAPI(title="Todo Service", version="1.1.0")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_FILE = DATA_DIR / "todos.json"
TodoFilter = Literal["current", "active", "completed", "archived", "all"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class TodoOut(BaseModel):
    id: str
    title: str
    description: str = ""
    category: str = ""
    completed: bool = False
    completed_at: Optional[str] = None
    archived: bool = False
    archived_at: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    due_date: Optional[str] = None


class TodoCreate(BaseModel):
    title: str
    description: str = ""
    category: str = ""
    completed: bool = False
    due_date: Optional[str] = None


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    completed: Optional[bool] = None
    due_date: Optional[str] = None


class TodoArchive(BaseModel):
    archived: bool = True


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _normalize(todo: dict) -> dict:
    """Supply archive fields for records created before version 1.1."""
    normalized = dict(todo)
    normalized.setdefault("completed_at", None)
    normalized.setdefault("archived", False)
    normalized.setdefault("archived_at", None)
    normalized.setdefault("category", "")
    normalized.setdefault("due_date", None)
    return normalized


def _load() -> List[dict]:
    _ensure_data_dir()
    if not DATA_FILE.exists():
        return []
    try:
        stored = json.loads(DATA_FILE.read_text("utf-8"))
        if not isinstance(stored, list):
            return []
        return [_normalize(todo) for todo in stored if isinstance(todo, dict)]
    except (json.JSONDecodeError, FileNotFoundError, ValueError):
        return []


def _save(todos: List[dict]) -> None:
    _ensure_data_dir()
    DATA_FILE.write_text(json.dumps(todos, indent=2, ensure_ascii=False), "utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Quick-install endpoints - serve plugin files & installer
# ---------------------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent
PLUGIN_DIR = PROJECT_DIR / "plugin"

_PLUGIN_YAML = None
_PLUGIN_INIT = None
_INSTALL_SH = None


def _load_plugin_yaml() -> str:
    global _PLUGIN_YAML
    if _PLUGIN_YAML is None:
        _PLUGIN_YAML = (PLUGIN_DIR / "plugin.yaml").read_text("utf-8")
    return _PLUGIN_YAML


def _load_plugin_init() -> str:
    global _PLUGIN_INIT
    if _PLUGIN_INIT is None:
        _PLUGIN_INIT = (PLUGIN_DIR / "__init__.py").read_text("utf-8")
    return _PLUGIN_INIT


def _load_install_sh() -> str:
    global _INSTALL_SH
    if _INSTALL_SH is None:
        _INSTALL_SH = (PROJECT_DIR / "install.sh").read_text("utf-8")
    return _INSTALL_SH


@app.get("/install.sh", response_class=PlainTextResponse)
def serve_install_script():
    """Quick-install script. Pipe directly: curl -sL http://host:8765/install.sh | bash"""
    return _load_install_sh()


@app.get("/plugin.yaml", response_class=PlainTextResponse)
def serve_plugin_yaml():
    return _load_plugin_yaml()


@app.get("/plugin/__init__.py", response_class=PlainTextResponse)
def serve_plugin_init():
    return _load_plugin_init()


@app.get("/todos", response_model=List[TodoOut])
def list_todos(
    filter: TodoFilter = Query(
        "current",
        description="current (default), active, completed, archived, or all",
    ),
    q: Optional[str] = Query(None, description="Case-insensitive title/description search"),
):
    """List/search todos. Archives are excluded unless explicitly requested."""
    todos = _load()

    if filter == "current":
        todos = [todo for todo in todos if not todo["archived"]]
    elif filter == "active":
        todos = [todo for todo in todos if not todo["archived"] and not todo["completed"]]
    elif filter == "completed":
        todos = [todo for todo in todos if not todo["archived"] and todo["completed"]]
    elif filter == "archived":
        todos = [todo for todo in todos if todo["archived"]]

    if q and q.strip():
        needle = q.strip().casefold()
        todos = [
            todo
            for todo in todos
            if needle in todo.get("title", "").casefold()
            or needle in todo.get("description", "").casefold()
        ]

    return todos


@app.get("/todos/{todo_id}", response_model=TodoOut)
def get_todo(todo_id: str):
    todos = _load()
    for todo in todos:
        if todo["id"] == todo_id:
            return todo
    raise HTTPException(status_code=404, detail="Todo not found")


@app.post("/todos", response_model=TodoOut, status_code=201)
def create_todo(todo: TodoCreate):
    todos = _load()
    now = _now()
    new = {
        "id": str(uuid4()),
        "title": todo.title,
        "description": todo.description,
        "category": (todo.category or "").strip(),
        "completed": todo.completed,
        "completed_at": now if todo.completed else None,
        "archived": False,
        "archived_at": None,
        "created_at": now,
        "updated_at": now,
    }
    todos.append(new)
    _save(todos)
    return new


@app.put("/todos/{todo_id}", response_model=TodoOut)
def update_todo(todo_id: str, todo: TodoUpdate):
    todos = _load()
    now = _now()
    for stored in todos:
        if stored["id"] == todo_id:
            if todo.title is not None:
                stored["title"] = todo.title
            if todo.description is not None:
                stored["description"] = todo.description
            if todo.category is not None:
                stored["category"] = (todo.category or "").strip()
            if todo.due_date is not None:
                stored["due_date"] = (todo.due_date or "").strip() or None
            if todo.completed is not None:
                if todo.completed and not stored["completed"]:
                    stored["completed_at"] = now
                elif not todo.completed:
                    stored["completed_at"] = None
                stored["completed"] = todo.completed
            stored["updated_at"] = now
            _save(todos)
            return stored
    raise HTTPException(status_code=404, detail="Todo not found")


@app.put("/todos/{todo_id}/archive", response_model=TodoOut)
def set_todo_archive(todo_id: str, change: TodoArchive):
    """Archive or restore a todo without deleting its history."""
    todos = _load()
    now = _now()
    for todo in todos:
        if todo["id"] == todo_id:
            todo["archived"] = change.archived
            todo["archived_at"] = now if change.archived else None
            todo["updated_at"] = now
            _save(todos)
            return todo
    raise HTTPException(status_code=404, detail="Todo not found")


@app.delete("/todos/{todo_id}", status_code=204)
def delete_todo(todo_id: str):
    """Permanently delete a todo. Archive is preferred for normal cleanup."""
    todos = _load()
    for index, todo in enumerate(todos):
        if todo["id"] == todo_id:
            todos.pop(index)
            _save(todos)
            return
    return  # Idempotent permanent delete.


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=True)
