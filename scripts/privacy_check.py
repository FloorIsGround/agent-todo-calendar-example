"""Cheap publication preflight over included files, not a privacy certification."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = {".git", ".venv", ".uv-cache", ".uv-python", "__pycache__", ".pytest_cache",
            "data", "state"}
PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}\b"),
    "Discord-shaped token": re.compile(r"\b[A-Za-z0-9_-]{24,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}\b"),
    "personal home path": re.compile(r"/(?:home|Users)/(?!example-user(?:/|$))[A-Za-z0-9_.-]+/"),
}


def included_files(directory: Path):
    for path in sorted(directory.iterdir()):
        if path.name in EXCLUDED or path.name.startswith((".demo-", ".test-")):
            continue
        if path.is_symlink():
            raise ValueError(f"Review symlink before publication: {path.relative_to(ROOT)}")
        if path.is_dir():
            yield from included_files(path)
        else:
            yield path


def main() -> int:
    errors = []
    manifest = json.loads((ROOT / "examples/evidence_sha256.json").read_text())
    for name, expected in manifest.items():
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(f"Immutable evidence changed: {name}")
    count = 0
    for path in included_files(ROOT):
        count += 1
        name = path.relative_to(ROOT)
        if (path.name.startswith(".env") and path.name != ".env.example"
                or path.suffix.lower() in {".pem", ".key", ".sqlite", ".db", ".zip"}
                or path.name in {"google_token.json", "credentials.json"}):
            errors.append(f"Review excluded/credential-like file: {name}")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeError:
            errors.append(f"Review binary file: {name}")
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                errors.append(f"Potential {label}: {name}")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Privacy preflight: {count} included text files checked; "
          f"{len(manifest)} immutable evidence hashes match; no configured patterns found.")
    print("Heuristic only. Excludes local runtime/cache directories; review before publishing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
