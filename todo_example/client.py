"""Small stdlib HTTP client and JSON tool dispatcher. Loopback only."""
from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, base_url: str = "http://127.0.0.1:8765", trace: list | None = None):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise ValueError("Use a plain HTTP loopback base URL with no path or credentials")
        self.base_url = base_url.rstrip("/")
        self.trace = trace
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method: str, path: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(self.base_url + path, data=data, method=method,
                      headers={"Content-Type": "application/json"})
        with self.opener.open(req, timeout=5) as response:
            result = json.load(response)
            if self.trace is not None:
                self.trace.append({"method": method, "path": path, "request": body,
                                   "status": response.status, "response": result})
            return result

    def list(self, filter: str = "current", q: str | None = None) -> list[dict]:
        params = {"filter": filter}
        if q is not None:
            params["q"] = q
        return self.request("GET", "/todos?" + urlencode(params))

    def get(self, todo_id: str) -> dict:
        return self.request("GET", "/todos/" + quote(todo_id, safe=""))

    def create(self, fields: dict) -> dict:
        return self.request("POST", "/todos", fields)

    def update(self, todo_id: str, fields: dict) -> dict:
        return self.request("PUT", "/todos/" + quote(todo_id, safe=""), fields)

    def archive(self, todo_id: str, archived: bool) -> dict:
        return self.request("PUT", "/todos/" + quote(todo_id, safe="") + "/archive",
                            {"archived": archived})

    def call_tool(self, name: str, arguments: dict):
        # The names/arguments are defined in docs/tool_schemas.json.
        functions = {"todo_list": self.list, "todo_get": self.get,
                     "todo_create": self.create, "todo_update": self.update,
                     "todo_archive": self.archive}
        if name not in functions:
            raise ValueError(f"Unknown tool: {name}")
        return functions[name](**arguments)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--filter", default="current")
    listing.add_argument("--q")
    get = commands.add_parser("get")
    get.add_argument("todo_id")
    create = commands.add_parser("create")
    create.add_argument("--json", required=True, dest="fields")
    update = commands.add_parser("update")
    update.add_argument("todo_id")
    update.add_argument("--json", required=True, dest="fields")
    archive = commands.add_parser("archive")
    archive.add_argument("todo_id")
    archive.add_argument("--restore", action="store_true")
    tool = commands.add_parser("tool")
    tool.add_argument("name")
    tool.add_argument("--args", required=True)
    args = parser.parse_args()
    try:
        client = Client(args.base_url)
        if args.command == "list":
            result = client.list(args.filter, args.q)
        elif args.command == "get":
            result = client.get(args.todo_id)
        elif args.command == "create":
            result = client.create(json.loads(args.fields))
        elif args.command == "update":
            result = client.update(args.todo_id, json.loads(args.fields))
        elif args.command == "archive":
            result = client.archive(args.todo_id, not args.restore)
        else:
            result = client.call_tool(args.name, json.loads(args.args))
        print(json.dumps(result, indent=2))
        return 0
    except HTTPError as exc:
        print(json.dumps({"error": "HTTP error", "status": exc.code,
                          "detail": exc.read().decode("utf-8")}))
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
