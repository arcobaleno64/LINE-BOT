#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

TAIPEI_TZ = timezone(timedelta(hours=8))
ARTIFACT_DIRS = {
    "task": "tasks",
    "research": "research",
    "plan": "plans",
    "code": "code",
    "test": "test",
    "verify": "verify",
    "decision": "decisions",
    "improvement": "improvement",
    "status": "status",
}
ARTIFACT_EXTENSIONS = {
    "task": ".task.md",
    "research": ".research.md",
    "plan": ".plan.md",
    "code": ".code.md",
    "test": ".test.md",
    "verify": ".verify.md",
    "decision": ".decision.md",
    "improvement": ".improvement.md",
    "status": ".status.json",
}
TAIPEI_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+08:00$")
MAX_ARTIFACT_FILE_BYTES = 512 * 1024
_main_module = sys.modules.get("guard_status_validator") or sys.modules.get("__main__")
GuardError = getattr(_main_module, "GuardError", None)
if GuardError is None:
    class GuardError(Exception):
        pass

__all__ = [
    "artifact_path",
    "find_artifact_paths",
    "read_bounded_file",
    "load_json",
    "load_text",
    "current_taipei_timestamp",
    "write_json",
    "parse_taipei_datetime",
    "override_log_path",
    "load_override_log",
]

def artifact_path(artifacts_root: Path, task_id: str, artifact_type: str) -> Path:
    if artifact_type not in ARTIFACT_DIRS:
        raise GuardError(f"Unknown artifact type: {artifact_type}")
    return artifacts_root / ARTIFACT_DIRS[artifact_type] / f"{task_id}{ARTIFACT_EXTENSIONS[artifact_type]}"


def find_artifact_paths(artifacts_root: Path, task_id: str, artifact_type: str) -> List[Path]:
    if artifact_type == "improvement":
        return sorted((artifacts_root / ARTIFACT_DIRS[artifact_type]).glob(f"{task_id}*.improvement.md"))
    path = artifact_path(artifacts_root, task_id, artifact_type)
    return [path] if path.exists() else []


def read_bounded_file(path: Path, *, missing_label: Optional[str], too_large_label: str) -> Optional[bytes]:
    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_ARTIFACT_FILE_BYTES + 1)
    except FileNotFoundError as exc:
        if missing_label is None:
            return None
        raise GuardError(f"Missing {missing_label}: {path}") from exc
    except OSError as exc:
        raise GuardError(f"Unable to read {path}: {exc}") from exc
    if len(payload) > MAX_ARTIFACT_FILE_BYTES:
        raise GuardError(f"{too_large_label}: {path} exceeds size ceiling of {MAX_ARTIFACT_FILE_BYTES} bytes")
    return payload


def load_json(path: Path) -> dict:
    payload = read_bounded_file(path, missing_label="JSON file", too_large_label="JSON file too large")
    assert payload is not None
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardError(f"Invalid JSON in {path}: {exc}") from exc


def load_text(path: Path) -> str:
    payload = read_bounded_file(path, missing_label="text file", too_large_label="Text file too large")
    assert payload is not None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GuardError(f"Invalid UTF-8 in text file {path}: {exc}") from exc


def current_taipei_timestamp() -> str:
    return datetime.now(TAIPEI_TZ).isoformat(timespec="seconds")


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_taipei_datetime(value: str) -> Optional[datetime]:
    if not TAIPEI_TIMESTAMP_PATTERN.match(str(value).strip()):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None
    return parsed.astimezone(TAIPEI_TZ)


def override_log_path(artifacts_root: Path, task_id: str) -> Path:
    return artifacts_root / ARTIFACT_DIRS["status"] / f"{task_id}.override_log.json"


def load_override_log(path: Path) -> List[dict]:
    payload_bytes = read_bounded_file(path, missing_label=None, too_large_label="Override log too large")
    if payload_bytes is None:
        return []
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GuardError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise GuardError(f"Invalid override log in {path}: expected a JSON array")
    for index, entry in enumerate(payload, start=1):
        if not isinstance(entry, dict):
            raise GuardError(f"Invalid override log in {path}: entry #{index} must be an object")
    return payload


