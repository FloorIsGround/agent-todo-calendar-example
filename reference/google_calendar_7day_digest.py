#!/usr/bin/env python3
"""Generate a deterministic seven-day Google Calendar digest for Discord."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN_PATH = Path.home() / ".hermes/google_token.json"
DEFAULT_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
COURSE_CODE = re.compile(r"[A-Z]{3,4}\d{3}")
EMAIL_CALENDAR = re.compile(r"^[^@]+@[^@]+\.[^@]+$")
COURSE_KEYWORDS = (
    "course", "lecture", "seminar", "tutorial", "lab", "recitation", "class",
    "assignment", "homework", "quiz", "exam", "project", "module", "unit",
    "university", "college", "security", "network", "systems", "software",
    "engineering", "programming", "algorithm", "data structure",
)


def system_timezone() -> tuple[str, ZoneInfo]:
    timezone_file = Path("/etc/timezone")
    try:
        name = timezone_file.read_text().strip()
        if name:
            return name, ZoneInfo(name)
    except (OSError, ValueError):
        pass

    try:
        target = Path("/etc/localtime").resolve()
        marker = "/zoneinfo/"
        if marker in str(target):
            name = str(target).split(marker, 1)[1]
            return name, ZoneInfo(name)
    except (OSError, ValueError):
        pass

    return "America/Chicago", ZoneInfo("America/Chicago")


def credentials_from(data: dict[str, object]) -> Credentials:
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes") or DEFAULT_SCOPES,
    )


def save_refreshed_token(data: dict[str, object], creds: Credentials) -> None:
    data["token"] = creds.token
    if creds.expiry:
        data["expiry"] = creds.expiry.isoformat()

    temporary = TOKEN_PATH.with_suffix(".tmp")
    mode = TOKEN_PATH.stat().st_mode & 0o777
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(temporary, mode)
    temporary.replace(TOKEN_PATH)


def load_credentials() -> tuple[dict[str, object], Credentials]:
    if not TOKEN_PATH.exists():
        raise RuntimeError(f"Google Calendar OAuth token is missing: {TOKEN_PATH}")

    data = json.loads(TOKEN_PATH.read_text())
    creds = credentials_from(data)
    if creds.expired or not creds.valid:
        if not creds.refresh_token:
            raise RuntimeError("Google Calendar OAuth token is expired and has no refresh token")
        creds.refresh(Request())
        save_refreshed_token(data, creds)
    return data, creds


# ---------------------------------------------------------------------------
# Discord rolling-message delivery (create once, edit in place thereafter)
# ---------------------------------------------------------------------------

DISCORD_API_BASE = "https://discord.com/api/v10"
# Forum post thread where the digest lives. Override via env if ever needed.
DISCORD_THREAD_ID = os.environ.get("CALENDAR_DIGEST_THREAD_ID", "000000000000000002")
DISCORD_MAX_CONTENT = 2000
DISCORD_HEADERS = {
    "Authorization": "",
    "Content-Type": "application/json",
    "User-Agent": "hermes-calendar-digest/1.0",
}


def _hermes_root() -> Path:
    """Profile-aware Hermes home (subprocess env preserves HERMES_HOME)."""
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def load_discord_token() -> str:
    """Read DISCORD_BOT_TOKEN from the Hermes .env file.

    Cron subprocesses get their env scrubbed of secrets
    (``build_subprocess_env`` / ``_sanitize_subprocess_env``), so the token
    must be read from disk, not os.environ - same as the Google token.
    """
    env_path = _hermes_root() / ".env"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == "DISCORD_BOT_TOKEN":
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                if value:
                    return value
    except OSError as exc:
        raise RuntimeError(f"Cannot read Hermes .env at {env_path}: {exc}") from exc
    raise RuntimeError("DISCORD_BOT_TOKEN is missing from the Hermes .env file")


def _discord_request(method: str, url: str, payload: dict | None = None) -> dict:
    headers = dict(DISCORD_HEADERS)
    headers["Authorization"] = f"Bot {load_discord_token()}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    request = urllib.request.Request(
        url, data=body or None, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(
            f"Discord {method} {url} failed (HTTP {exc.code}): {detail}"
        ) from exc


def _discord_state_path() -> Path:
    return _hermes_root() / "cron" / ".calendar_digest_state.json"


def _load_discord_state() -> dict:
    path = _discord_state_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_discord_state(state: dict) -> None:
    path = _discord_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def deliver_digest(digest: str) -> None:
    """Post a new digest message, delete the old one, and save the new ID.

    Each run creates a fresh forum post so it shows as unread. The
    previous digest message is deleted if it still exists. Emits nothing
    on success - cron delivery is ``local`` for this job, so the script
    owns Discord posting entirely.
    """
    if len(digest) > DISCORD_MAX_CONTENT:
        raise RuntimeError(
            f"Digest is {len(digest)} chars; Discord caps messages at "
            f"{DISCORD_MAX_CONTENT}"
        )

    state = _load_discord_state()
    old_message_id = state.get("message_id")
    thread_id = state.get("thread_id") or DISCORD_THREAD_ID

    # Delete the old message first (best-effort; ignore 404).
    if old_message_id:
        del_url = f"{DISCORD_API_BASE}/channels/{thread_id}/messages/{old_message_id}"
        try:
            _discord_request("DELETE", del_url, {})
        except RuntimeError as exc:
            if "HTTP 404" not in str(exc):
                raise

    # Post the new message.
    url = f"{DISCORD_API_BASE}/channels/{thread_id}/messages"
    created = _discord_request("POST", url, {"content": digest})
    new_id = created.get("id")
    if not new_id:
        raise RuntimeError("Discord POST succeeded but returned no message id")
    _save_discord_state({"thread_id": thread_id, "message_id": new_id})


def clean_course_name(name: str) -> str:
    match = re.search(r"([A-Z]{3,4}\d{3})[ _].*?[ _](.+)", name)
    if match:
        return f"{match.group(1)} - {match.group(2).strip(' _')}"
    return name


def detect_course(calendar_name: str, title: str) -> str | None:
    if EMAIL_CALENDAR.fullmatch(calendar_name):
        return None
    combined = f"{calendar_name} {title}".lower()
    if COURSE_CODE.search(calendar_name) or any(word in combined for word in COURSE_KEYWORDS):
        return clean_course_name(calendar_name)
    return None


def parse_datetime(value: str, local_tz: ZoneInfo) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(local_tz)


def event_start(event: dict[str, object], local_tz: ZoneInfo) -> tuple[date, datetime | None, bool] | None:
    start = event.get("start")
    if not isinstance(start, dict):
        return None
    if isinstance(start.get("dateTime"), str):
        value = parse_datetime(start["dateTime"], local_tz)
        return value.date(), value, False
    if isinstance(start.get("date"), str):
        value = date.fromisoformat(start["date"])
        return value, None, True
    return None


def format_event(event: dict[str, object], calendar_name: str, local_tz: ZoneInfo) -> tuple[date, tuple[int, datetime], str] | None:
    parsed = event_start(event, local_tz)
    if parsed is None:
        return None
    day, start_dt, all_day = parsed

    title = str(event.get("summary") or "Untitled event").strip()
    if all_day:
        time_text = "All day"
        sort_key = (0, datetime.combine(day, time.min, local_tz))
    else:
        assert start_dt is not None
        time_text = start_dt.strftime("%I:%M %p").lstrip("0")
        sort_key = (1, start_dt)
        end = event.get("end")
        if isinstance(end, dict) and isinstance(end.get("dateTime"), str):
            end_dt = parse_datetime(end["dateTime"], local_tz)
            end_text = end_dt.strftime("%I:%M %p").lstrip("0")
            if end_text != time_text:
                time_text += f" - {end_text}"

    course = detect_course(calendar_name, title)
    course_text = f" ({course})" if course else ""

    location = str(event.get("location") or "").strip()
    if len(location) > 160:
        location = ""
    elif location.startswith(("http://", "https://")):
        location = f"<{location}>"
    location_text = f" at {location}" if location else ""

    return day, sort_key, f"- {time_text}: {title}{course_text}{location_text}"


def fetch_events(token_data: dict[str, object], creds: Credentials, start_utc: datetime, end_utc: datetime) -> list[tuple[str, dict[str, object]]]:
    list_service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    calendars = list_service.calendarList().list().execute().get("items", [])
    collected: list[tuple[str, dict[str, object]]] = []

    for calendar in calendars:
        calendar_name = str(calendar.get("summary") or "Unnamed calendar")
        if "holiday" in calendar_name.lower():
            continue

        per_calendar_creds = credentials_from(token_data)
        per_calendar_creds.token = creds.token
        service = build("calendar", "v3", credentials=per_calendar_creds, cache_discovery=False)
        page_token = None
        while True:
            response = service.events().list(
                calendarId=calendar["id"],
                timeMin=start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                timeMax=end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            ).execute()
            for event in response.get("items", []):
                collected.append((calendar_name, event))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    return collected


# ---------------------------------------------------------------------------
# Course-item + todo merging for the 7-day overview
# ---------------------------------------------------------------------------

TODO_API = os.environ.get("TODO_API", "http://127.0.0.1:8765")
PROXY_COURSE_DIR = Path.home() / "Desktop/servers/simple-calendar-proxy/data/courses"


def _http_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_todos() -> list[dict]:
    """All todos from the todo service (active and completed, not archived)."""
    try:
        todos = _http_json(f"{TODO_API}/todos")
        return [t for t in todos if not t.get("archived")]
    except Exception:
        return []


def fetch_course_items() -> list[dict]:
    """Course items from simple-calendar-proxy (ground truth for courses)."""
    items: list[dict] = []
    if not PROXY_COURSE_DIR.exists():
        return items
    for path in sorted(PROXY_COURSE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        display = data.get("displayId") or path.stem
        source = data.get("source") or "blackboard"
        merged = data.get("dueDateItems") or data.get("calendarItems") or []
        for item in merged:
            items.append({
                "course": display,
                "source": source,
                "title": item.get("title") or "",
                "startDate": item.get("startDate") or "",
                "endDate": item.get("endDate") or "",
                "eventType": item.get("eventType") or "",
                "handle": item.get("handle") or "",
                "itemSourceId": item.get("itemSourceId") or f"{display}:{item.get('title')}",
            })
    return items


def course_item_date(item: dict, local_tz: ZoneInfo) -> date | None:
    raw = item.get("startDate") or item.get("endDate") or ""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(
            local_tz).date()
    except ValueError:
        return None


def course_item_sort_key(item: dict, local_tz: ZoneInfo) -> tuple[int, datetime]:
    raw = item.get("startDate") or item.get("endDate") or ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(local_tz)
        return (1, dt)
    except ValueError:
        return (0, datetime.combine(date.min, time.min, local_tz))


def todo_due_date(todo: dict, local_tz: ZoneInfo) -> date | None:
    raw = todo.get("due_date") or ""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(
            local_tz).date()
    except ValueError:
        return None


def _is_lecture(item: dict) -> bool:
    title = (item.get("title") or "").lower()
    return any(h in title for h in ("lecture", "class", "seminar", "orientation",
                                    "welcome", "introduction"))


def _format_course_item(item: dict, local_tz: ZoneInfo) -> str:
    """Format a proxy course item as a [calendar]-prefixed line.

    Returns the bare line (no diff prefix); the render loop adds '+ ' or '- '
    based on the completed flag carried in the merge tuple.
    """
    raw = item.get("startDate") or item.get("endDate") or ""
    time_text = "All day"
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(local_tz)
        time_text = dt.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        pass
    course = item.get("course") or ""
    title = item.get("title") or "Untitled"
    # Marker at the front: '[calendar] TIME: TITLE (COURSE)'
    return f"[calendar] {time_text}: {title} ({course})"


def _format_todo(todo: dict, local_tz: ZoneInfo) -> str:
    return f"[todo] {todo.get('title') or 'Untitled'}"


def _is_auto_synced_todo(todo: dict) -> bool:
    """True if this todo was created by course_todo_sync (has itemSourceId)."""
    return "itemSourceId:" in (todo.get("description") or "")


def _todo_item_source(todo: dict) -> str | None:
    """Extract the itemSourceId embedded in an auto-synced todo description."""
    desc = todo.get("description") or ""
    marker = "itemSourceId:"
    if marker not in desc:
        return None
    return desc.split(marker, 1)[1].strip().rstrip(").| \t\r\n") or None


def _completed_course_sources(todos: list[dict]) -> set[str]:
    """Set of itemSourceIds whose auto-synced todo is marked completed."""
    return {
        src for t in todos
        if t.get("completed")
        for src in [_todo_item_source(t)]
        if src
    }


def _day_manual_todos(day: date, todos: list[dict], local_tz: ZoneInfo) -> list[tuple[tuple[int, datetime], str, bool]]:
    """Manual (non-auto-synced) todos due on this day.

    Returns (sort_key, rendered_line, completed_flag). Auto-created course
    todos are intentionally excluded - they are represented by [calendar]
    lines and would clutter the list with a whole semester.
    """
    out: list[tuple[tuple[int, datetime], str, bool]] = []
    for todo in todos:
        if _is_auto_synced_todo(todo):
            continue
        todo_day = todo_due_date(todo, local_tz)
        if todo_day != day:
            continue
        out.append(((2, datetime.combine(day, time.min, local_tz)),
                    _format_todo(todo, local_tz),
                    bool(todo.get("completed"))))
    return out


def _merge_day_events(day: date, google_events: list[tuple[date, tuple[int, datetime], str]],
                      course_items: list[dict],
                      completed_sources: set[str],
                      local_tz: ZoneInfo) -> list[tuple[tuple[int, datetime], str, bool]]:
    """Combine Google calendar events + proxy course items for one day.

    Returns (sort_key, rendered_line, completed) where completed is True if
    the course item's auto-synced todo is done. Google course duplicates are
    dropped in favor of the ground-truth proxy item.
    """
    # Build the set of proxy item titles for this day (for dedupe).
    proxy_titles: set[str] = set()
    for item in course_items:
        item_day = course_item_date(item, local_tz)
        if item_day == day:
            proxy_titles.add((item.get("title") or "").strip().lower())

    calendar_lines: list[tuple[tuple[int, datetime], str, bool]] = []

    for ev_day, sort_key, line in google_events:
        if ev_day != day:
            continue
        # If a proxy item covers this title, skip the Google duplicate.
        title = _google_event_title(line)
        if title in proxy_titles:
            continue
        calendar_lines.append((sort_key, line, False))

    for item in course_items:
        item_day = course_item_date(item, local_tz)
        if item_day != day:
            continue
        if _is_lecture(item):
            continue
        completed = item.get("itemSourceId") in completed_sources
        calendar_lines.append((course_item_sort_key(item, local_tz),
                               _format_course_item(item, local_tz),
                               completed))

    return calendar_lines


def _google_event_title(line: str) -> str:
    """Extract the event title from a formatted Google event line.

    Format is '- TIME: TITLE (COURSE) at LOCATION'. We strip the leading
    '- TIME:' and trailing ' (course) at location' so matches are on the title.
    """
    if not line.startswith("- "):
        return ""
    body = line[2:]
    # Strip the leading time '6:59 PM:' or 'All day:'.
    if ": " in body:
        body = body.split(": ", 1)[1]
    # Strip a trailing course/location group in parentheses (course) or at loc.
    body = re.sub(r"\s+\([^)]*\)\s*$", "", body).strip()
    return body.lower()


def _script_dir() -> str:
    """Directory of this script, abbreviated with ~ when under $HOME."""
    path = Path(__file__).resolve().parent
    try:
        rel = path.relative_to(Path.home())
        return str(Path("~") / rel)
    except ValueError:
        return str(path)


def _host_suffix() -> str:
    """Last two octets of the primary LAN IP, e.g. '0.111'."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("127.0.0.1", 9))  # UDP connect picks route, sends nothing
        ip = sock.getsockname()[0]
    finally:
        sock.close()
    parts = ip.split(".")
    return f"{parts[-2]}.{parts[-1]}" if len(parts) == 4 else "?.?"


def make_digest() -> str:
    timezone_name, local_tz = system_timezone()
    today = datetime.now(local_tz).date()
    start_local = datetime.combine(today, time.min, local_tz)
    end_local = start_local + timedelta(days=7)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    token_data, creds = load_credentials()
    events = fetch_events(token_data, creds, start_utc, end_utc)
    course_items = fetch_course_items()
    todos = fetch_todos()
    completed_sources = _completed_course_sources(todos)

    by_day: dict[date, list[tuple[tuple[int, datetime], str]]] = {}
    day_google: dict[date, list[tuple[date, tuple[int, datetime], str]]] = {}
    seen: set[tuple[date, str]] = set()
    # Stable ICS UIDs also catch Google copies cached on an obsolete date.
    # Title-and-day dedupe alone resurrects an event after a manual date move.
    proxy_uids = {f"{item['itemSourceId']}@blackboard.fhsu.edu"
                  for item in course_items if item.get("itemSourceId")}
    for calendar_name, event in events:
        if event.get("iCalUID") in proxy_uids:
            continue
        formatted = format_event(event, calendar_name, local_tz)
        if formatted is None:
            continue
        day, sort_key, line = formatted
        if not today <= day < today + timedelta(days=7):
            continue
        dedupe_key = (day, line)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        by_day.setdefault(day, []).append((sort_key, line))
        day_google.setdefault(day, []).append((day, sort_key, line))

    lines = ["# Schedule for the next 7 days", f"Times are in {timezone_name}.", ""]
    for offset in range(7):
        day = today + timedelta(days=offset)
        lines.append(f"### {day.strftime('%A, %B')} {day.day}")
        cal = sorted(_merge_day_events(day, day_google.get(day, []),
                                       course_items, completed_sources, local_tz),
                     key=lambda item: item[0])
        todo = sorted(_day_manual_todos(day, todos, local_tz),
                      key=lambda item: item[0])
        has_anything = bool(cal or todo)
        if cal:
            lines.append("```diff")
            for _, line, completed in cal:
                # Google events / legacy lines may start with '- '; normalize.
                clean = line[2:] if line.startswith("- ") else line
                lines.append(("- " if completed else "+ ") + clean)
            lines.append("```")
        if todo:
            lines.append("```diff")
            # todo entries are (sort_key, line, completed)
            lines.extend(("- " if completed else "+ ") + line
                         for _, line, completed in todo)
            lines.append("```")
        if not has_anything:
            lines.append("- Nothing scheduled.")
        lines.append("")

    # Small-print source footer (Discord -# syntax: host last-2-octets: script dir).
    lines.append(f"-# {_host_suffix()}: {_script_dir()}")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    try:
        digest = make_digest()
        sys.stdout.write(digest)
        deliver_digest(digest)
        return 0
    except Exception as exc:
        print(f"Calendar digest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
