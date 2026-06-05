#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from workflow_constants import DECISION_CLASSES

TAIPEI = timezone(timedelta(hours=8))
TASK_PATTERN = re.compile(r"^(TASK-[A-Za-z0-9-]+)\.decision\.md$")
SECTION_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
TYPE_LINE_PATTERN = re.compile(r"^(?:-\s*)?Type:\s*(.+?)\s*$", re.MULTILINE)
LAST_UPDATED_PATTERN = re.compile(r"^- Last Updated:\s*(.+?)\s*$", re.MULTILINE)
FIELD_PATTERNS = {
    "affects": re.compile(r"^(?:-\s*)?Affects:\s*(.*)$", re.MULTILINE),
    "related_research": re.compile(r"^(?:-\s*)?Related Research:\s*(.*)$", re.MULTILINE),
    "linked_artifacts": re.compile(r"^(?:-\s*)?Linked Artifacts:\s*(.*)$", re.MULTILINE),
}


@dataclass(frozen=True)
class RegistryEntry:
    task_id: str
    source_file: str
    decision_type: str
    decision_class: str
    affected_gate: str
    summary: str
    plan_refs: list[str]
    research_refs: list[str]
    linked_artifacts: list[str]
    date: str
    parse_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "source_file": self.source_file,
            "decision_type": self.decision_type,
            "decision_class": self.decision_class,
            "affected_gate": self.affected_gate,
            "summary": self.summary,
            "plan_refs": self.plan_refs,
            "research_refs": self.research_refs,
            "linked_artifacts": self.linked_artifacts,
            "date": self.date,
            "parse_status": self.parse_status,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a machine-readable registry from decision artifacts.")
    parser.add_argument("--root", default=".", help="Repository root. Default: current directory")
    return parser.parse_args()


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def parse_sections(text: str) -> dict[str, str]:
    matches = list(SECTION_PATTERN.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).strip().lower()] = text[start:end].strip()
    return sections


def first_paragraph(section_text: str | None) -> str:
    if not section_text:
        return ""
    paragraphs = [collapse_whitespace(block) for block in re.split(r"\n\s*\n", section_text) if block.strip()]
    return paragraphs[0] if paragraphs else ""


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_task_id(path: Path) -> str:
    match = TASK_PATTERN.match(path.name)
    if not match:
        raise ValueError(f"Unsupported decision artifact name: {path.name}")
    return match.group(1)


def extract_metadata_date(text: str) -> str:
    match = LAST_UPDATED_PATTERN.search(text)
    return collapse_whitespace(match.group(1)) if match else ""


def extract_decision_type(text: str, sections: dict[str, str]) -> str:
    decision_type = first_paragraph(sections.get("decision class")) or first_paragraph(sections.get("decision type"))
    if decision_type:
        normalized = collapse_whitespace(decision_type)
        return normalized if normalized in DECISION_CLASSES else normalized

    line_match = TYPE_LINE_PATTERN.search(text)
    if line_match:
        return collapse_whitespace(line_match.group(1))

    if "guard exception" in sections:
        return "guard_exception"
    return "general_decision"


def extract_summary(sections: dict[str, str]) -> str:
    for section_name in ("summary", "chosen option", "issue"):
        paragraph = first_paragraph(sections.get(section_name))
        if paragraph:
            return paragraph[:200]
    return ""


def extract_affected_gate(sections: dict[str, str]) -> str:
    return first_paragraph(sections.get("affected gate"))


def extract_field_tokens(text: str, label: str) -> list[str]:
    pattern = FIELD_PATTERNS[label]
    tokens: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        initial = match.group(1).strip()
        collected: list[str] = []
        if initial:
            collected.append(initial)
        next_index = index + 1
        while next_index < len(lines):
            candidate = lines[next_index]
            stripped = candidate.strip()
            if not stripped:
                break
            if stripped.startswith("## "):
                break
            if re.match(r"^(?:-\s*)?[A-Za-z][A-Za-z ]+:\s*", stripped):
                break
            collected.append(stripped)
            next_index += 1
        tokens.extend(split_ref_tokens(collected))
    return dedupe_preserving_order(tokens)


def split_ref_tokens(chunks: Iterable[str]) -> list[str]:
    tokens: list[str] = []
    for chunk in chunks:
        for part in re.split(r"[\n,]", chunk):
            cleaned = clean_ref_token(part)
            if cleaned:
                tokens.append(cleaned)
    return tokens


def clean_ref_token(token: str) -> str:
    cleaned = token.strip().strip("`").strip()
    cleaned = re.sub(r"^[*-]\s*", "", cleaned)
    cleaned = cleaned.strip().strip("`").strip()
    return cleaned


def dedupe_preserving_order(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def normalize_ref(token: str, artifact_dir: str) -> str:
    candidate = token.replace("\\", "/").lstrip("./").strip("/")
    if not candidate:
        return ""

    if candidate.startswith("artifacts/") and candidate.endswith(".md"):
        return candidate

    if candidate.startswith(f"{artifact_dir}/") and candidate.endswith(".md"):
        return f"artifacts/{candidate}"

    task_match = re.fullmatch(r"(TASK-[A-Za-z0-9-]+)", candidate)
    if task_match:
        suffix = "plan" if artifact_dir == "plans" else "research"
        return f"artifacts/{artifact_dir}/{task_match.group(1)}.{suffix}.md"

    basename = Path(candidate).name
    if basename.endswith(".md") and basename.startswith("TASK-"):
        return f"artifacts/{artifact_dir}/{basename}"

    return candidate


def normalize_refs(tokens: list[str], artifact_dir: str) -> list[str]:
    normalized = [normalize_ref(token, artifact_dir) for token in tokens]
    return dedupe_preserving_order([token for token in normalized if token])


def normalize_linked_artifacts(tokens: list[str]) -> list[str]:
    linked: list[str] = []
    for token in tokens:
        candidate = token.replace("\\", "/").lstrip("./").strip()
        if candidate:
            linked.append(candidate)
    return dedupe_preserving_order(linked)


def fallback_same_task_ref(root: Path, artifact_dir: str, task_id: str) -> list[str]:
    suffix = "plan" if artifact_dir == "plans" else "research"
    relative = Path("artifacts") / artifact_dir / f"{task_id}.{suffix}.md"
    return [relative.as_posix()] if (root / relative).exists() else []


def build_entry(root: Path, decision_path: Path) -> RegistryEntry:
    raw_text = normalize_newlines(decision_path.read_text(encoding="utf-8"))
    sections = parse_sections(raw_text)
    task_id = extract_task_id(decision_path)
    decision_type = extract_decision_type(raw_text, sections)
    decision_class = decision_type
    affected_gate = extract_affected_gate(sections)
    summary = extract_summary(sections)
    plan_refs = normalize_refs(extract_field_tokens(raw_text, "affects"), "plans")
    research_refs = normalize_refs(extract_field_tokens(raw_text, "related_research"), "research")
    linked_artifacts = normalize_linked_artifacts(extract_field_tokens(raw_text, "linked_artifacts"))
    if not plan_refs:
        plan_refs = fallback_same_task_ref(root, "plans", task_id)
    if not research_refs:
        research_refs = fallback_same_task_ref(root, "research", task_id)
    date = extract_metadata_date(raw_text)

    parse_status = "complete" if all((decision_type, summary, plan_refs, date)) else "partial"
    return RegistryEntry(
        task_id=task_id,
        source_file=decision_path.relative_to(root).as_posix(),
        decision_type=decision_type,
        decision_class=decision_class,
        affected_gate=affected_gate,
        summary=summary,
        plan_refs=plan_refs,
        research_refs=research_refs,
        linked_artifacts=linked_artifacts,
        date=date,
        parse_status=parse_status,
    )


def build_registry(root: Path) -> dict[str, object]:
    decisions_dir = root / "artifacts" / "decisions"
    entries = [build_entry(root, path) for path in sorted(decisions_dir.glob("*.decision.md"))]
    return {
        "generated_at": datetime.now(UTC).astimezone(TAIPEI).isoformat(timespec="seconds"),
        "total": len(entries),
        "entries": [entry.to_dict() for entry in entries],
    }


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    registry = build_registry(root)
    output_path = root / "artifacts" / "registry" / "decision_registry.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
