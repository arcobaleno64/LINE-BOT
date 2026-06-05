#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional, Set

from workflow_constants import (
    ASSURANCE_LEVELS,
    DEFAULT_ASSURANCE_LEVEL,
    DEFAULT_PROJECT_ADAPTER,
    PROJECT_ADAPTERS,
)

LIST_ITEM_PATTERN = re.compile(r"^(?:- |\d+\. )")
TASK_INLINE_FLAG_PATTERN = re.compile(r"^\s*(?:-\s*)?([A-Za-z_][A-Za-z0-9_\- ]*)\s*:\s*(.+?)\s*$")
FILE_PATH_TOKEN_PATTERN = re.compile(r"\b(?:[A-Za-z]:[\\/])?[A-Za-z0-9_.\-\\/]+\.[A-Za-z0-9]{1,10}\b")

__all__ = [
    "extract_section",
    "parse_key_value_section",
    "parse_list_items",
    "normalize_path_token",
    "extract_file_tokens",
    "parse_csv_file_tokens",
    "compute_snapshot_sha256",
    "extract_task_inline_flags",
    "task_requests_lightweight",
    "task_declares_premortem",
    "collapse_whitespace",
    "extract_single_line_section",
    "normalize_assurance_level",
    "normalize_project_adapter",
    "resolve_assurance_level",
    "resolve_project_adapter",
]

def extract_section(text: str, heading: str) -> str:
    match = re.search(rf"## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def parse_key_value_section(section_text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw_line in section_text.splitlines():
        match = re.match(r"^-\s*([^:]+):\s*(.*)$", raw_line.strip())
        if match:
            values[match.group(1).strip().lower()] = match.group(2).strip()
    return values


def parse_list_items(section_text: str) -> List[str]:
    items: List[str] = []
    current: List[str] = []
    for raw_line in section_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            if current:
                current.append("")
            continue
        stripped = line.strip()
        if LIST_ITEM_PATTERN.match(stripped):
            if current:
                items.append("\n".join(current).strip())
            current = [LIST_ITEM_PATTERN.sub("", stripped, count=1)]
        elif current:
            current.append(stripped)
        else:
            current = [stripped]
    if current:
        items.append("\n".join(current).strip())
    return [item for item in items if item and item.lower() != "none"]


def normalize_path_token(token: str) -> str:
    value = token.strip().strip("`\"'.,:;()[]{}")
    value = value.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", value):
        value = value[2:]
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return value


def extract_file_tokens(section_text: str) -> Set[str]:
    tokens: Set[str] = set()
    for item in parse_list_items(section_text):
        for inline in re.findall(r"`([^`\n]+)`", item):
            normalized = normalize_path_token(inline)
            if "." in normalized:
                tokens.add(normalized)
        for match in FILE_PATH_TOKEN_PATTERN.findall(item):
            normalized = normalize_path_token(match)
            if "." in normalized:
                tokens.add(normalized)
    return tokens


def parse_csv_file_tokens(value: str) -> Set[str]:
    if not value or value.strip().lower() == "none":
        return set()
    tokens: Set[str] = set()
    for part in value.split(","):
        normalized = normalize_path_token(part)
        if normalized:
            tokens.add(normalized)
    return tokens


def compute_snapshot_sha256(paths: Set[str]) -> str:
    payload = "\n".join(sorted(paths))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def extract_task_inline_flags(task_text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for raw_line in task_text.splitlines():
        match = TASK_INLINE_FLAG_PATTERN.match(raw_line)
        if not match:
            continue
        key = match.group(1).strip().lower().replace(" ", "_")
        values[key] = match.group(2).strip()
    return values


def task_requests_lightweight(task_text: str) -> bool:
    value = extract_task_inline_flags(task_text).get("lightweight", "")
    return value.strip().lower() == "true"


def task_declares_premortem(task_text: str) -> bool:
    return "premortem" in extract_task_inline_flags(task_text)


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_single_line_section(text: str, heading: str) -> str:
    section = extract_section(text, heading)
    if not section:
        return ""
    return next(
        (collapse_whitespace(line) for line in section.splitlines() if line.strip()),
        "",
    )


def normalize_assurance_level(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in ASSURANCE_LEVELS else DEFAULT_ASSURANCE_LEVEL


def normalize_project_adapter(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in PROJECT_ADAPTERS else DEFAULT_PROJECT_ADAPTER


def resolve_assurance_level(task_text: str = "", status: Optional[dict] = None) -> str:
    flags = extract_task_inline_flags(task_text)
    task_value = (
        flags.get("assurance_level")
        or extract_single_line_section(task_text, "Assurance Level")
    )
    if task_value:
        return normalize_assurance_level(task_value)
    if isinstance(status, dict):
        return normalize_assurance_level(status.get("assurance_level", ""))
    return DEFAULT_ASSURANCE_LEVEL


def resolve_project_adapter(task_text: str = "", status: Optional[dict] = None) -> str:
    flags = extract_task_inline_flags(task_text)
    task_value = (
        flags.get("project_adapter")
        or extract_single_line_section(task_text, "Project Adapter")
    )
    if task_value:
        return normalize_project_adapter(task_value)
    if isinstance(status, dict):
        return normalize_project_adapter(status.get("project_adapter", ""))
    return DEFAULT_PROJECT_ADAPTER


