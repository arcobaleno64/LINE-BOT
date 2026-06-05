#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import guard_status_validator as gsv
from workflow_constants import DEFAULT_ASSURANCE_LEVEL, DEFAULT_PROJECT_ADAPTER

ROOT_TRACKED_MODE = "root-tracked"
EXTERNAL_LEGACY_MODE = "external-legacy"
INPUT_MODES = (ROOT_TRACKED_MODE, EXTERNAL_LEGACY_MODE)

TASK_SECTION_ORDER = (
    "Metadata",
    "Objective",
    "Background",
    "Inputs",
    "Constraints",
    "Acceptance Criteria",
    "Dependencies",
    "Out of Scope",
    "Assurance Level",
    "Project Adapter",
    "Current Status Summary",
)

DECISION_SECTION_ORDER = (
    "Metadata",
    "Decision Class",
    "Affected Gate",
    "Scope",
    "Issue",
    "Options Considered",
    "Chosen Option",
    "Reasoning",
    "Implications",
    "Expiry",
    "Linked Artifacts",
    "Follow Up",
    "Guard Exception",
)

IMPROVEMENT_SECTION_ORDER = (
    "Metadata",
    "Risk Analysis (新增)",
    "1. What Happened",
    "2. Why It Was Not Prevented",
    "3. Failure Classification",
    "4. Corrective Action (Immediate)",
    "5. Preventive Action (System Level)",
    "6. Validation",
    "7. Impact Scope",
    "8. Final Rule",
    "9. Status",
)


@dataclass
class MigrationChange:
    relative_path: str
    changed: bool
    detail: str
    notes: List[str] = field(default_factory=list)


@dataclass
class VerifyMigrationAssessment:
    strategy: str
    confidence: str
    manual_review_required: bool
    unresolved_fields: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class MigrationReport:
    apply: bool
    changes: List[MigrationChange] = field(default_factory=list)

    def changed_count(self) -> int:
        return sum(1 for item in self.changes if item.changed)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate tracked artifacts to the structured assurance schema.")
    parser.add_argument("--root", default=".", help="Repository root. Default: current directory")
    parser.add_argument("--apply", action="store_true", help="Write migrated content back to disk")
    parser.add_argument(
        "--input-mode",
        choices=INPUT_MODES,
        default=ROOT_TRACKED_MODE,
        help="Migration mode. Use external-legacy only for imported legacy artifacts that require heuristic mapping.",
    )
    return parser.parse_args(argv)


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n")


def split_markdown_sections(text: str) -> Tuple[str, Dict[str, str]]:
    normalized = normalize_newlines(text).strip() + "\n"
    lines = normalized.splitlines()
    title = lines[0].strip() if lines else ""
    sections: Dict[str, str] = {}
    current_heading = None
    current_lines: List[str] = []
    for line in lines[1:]:
        heading_match = re.match(r"^##\s+(.+?)\s*$", line)
        if heading_match:
            if current_heading is not None:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = heading_match.group(1).strip()
            current_lines = []
            continue
        if current_heading is not None:
            current_lines.append(line)
    if current_heading is not None:
        sections[current_heading] = "\n".join(current_lines).strip()
    return title, sections


def render_markdown(title: str, ordered_sections: Iterable[Tuple[str, str]]) -> str:
    parts = [title.strip()]
    for heading, body in ordered_sections:
        body_text = body.strip() if body.strip() else "None"
        parts.append(f"## {heading}\n{body_text}")
    return "\n\n".join(parts).rstrip() + "\n"


def ensure_list_body(lines: Iterable[str]) -> str:
    values = [line.strip() for line in lines if line.strip()]
    return "\n".join(values) if values else "None"


def first_non_empty(*values: str) -> str:
    for value in values:
        if value and value.strip():
            return value.strip()
    return ""


def merge_named_lines(existing_body: str, new_lines: Iterable[str]) -> str:
    existing_lines = [line.strip() for line in existing_body.splitlines() if line.strip() and line.strip().lower() != "none"]
    merged: List[str] = []
    seen = set()
    for line in [*new_lines, *existing_lines]:
        normalized = line.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    return "\n".join(merged) if merged else "None"


def is_path_like_reference(token: str) -> bool:
    normalized = gsv.normalize_path_token(token)
    if not normalized or " " in normalized:
        return False
    if normalized.startswith(
        (
            "artifacts/",
            "docs/",
            "template/",
            "README",
            "README.",
            "OBSIDIAN",
            "BOOTSTRAP_PROMPT",
            "CLAUDE.md",
            "CODEX.md",
            "GEMINI.md",
            "AGENTS.md",
            "START_HERE",
        )
    ):
        return True
    return "/" in normalized and not normalized.lower().startswith("python")


def extract_path_like_tokens(text: str) -> List[str]:
    tokens = set()
    for item in gsv.parse_list_items(text):
        stripped_item = item.strip().strip("`").lower()
        if stripped_item.startswith(("python ", "pytest ", "git ", "powershell ", "pwsh ")):
            continue
        for token in gsv.extract_file_tokens(item):
            if is_path_like_reference(token):
                tokens.add(token)
    return sorted(tokens)


def load_git_head_text(root: Path, relative_path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "show", f"HEAD:{relative_path}"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    return result.stdout


def detect_docs_spec_task(text: str) -> bool:
    lowered = text.lower()
    signals = (
        "readme",
        "workflow file",
        "docs/",
        "schema",
        "artifact",
        "runbook",
        "documentation",
        "文件",
        "規格",
    )
    hits = sum(1 for signal in signals if signal in lowered)
    return hits >= 3


def migrate_task_text(text: str, assurance_level: str, project_adapter: str) -> str:
    title, sections = split_markdown_sections(text)
    effective_adapter = project_adapter
    if effective_adapter == DEFAULT_PROJECT_ADAPTER and detect_docs_spec_task(text):
        effective_adapter = DEFAULT_PROJECT_ADAPTER
    ordered_sections: List[Tuple[str, str]] = []
    for heading in TASK_SECTION_ORDER:
        if heading == "Assurance Level":
            body = sections.get(heading, assurance_level.upper())
        elif heading == "Project Adapter":
            body = sections.get(heading, effective_adapter)
        else:
            body = sections.get(heading, "None")
        ordered_sections.append((heading, body))
    return render_markdown(title, ordered_sections)


def infer_decision_class(text: str) -> Tuple[str, bool]:
    lowered = text.lower()
    if "exception type: allow-scope-drift" in lowered:
        return "scope-drift-waiver", False
    if "defer" in lowered or "延期" in lowered:
        return "defer", False
    if "reject" in lowered or "拒絕" in lowered:
        return "reject", False
    if "conflict" in lowered or "衝突" in lowered:
        return "conflict-resolution", False
    return "risk-acceptance", True


def infer_affected_gate(text: str) -> str:
    lowered = text.lower()
    if "gate e" in lowered or "pdca" in lowered or "resume" in lowered:
        return "Gate_E"
    if "scope drift" in lowered or "allow-scope-drift" in lowered:
        return "Gate_B"
    if "research" in lowered:
        return "Gate_A"
    if "build" in lowered or ".code.md" in lowered:
        return "Gate_C"
    return "Gate_D"


def linked_artifacts_for_task(root: Path, task_id: str) -> List[str]:
    results: List[str] = []
    artifact_map = {
        "task": f"artifacts/tasks/{task_id}.task.md",
        "research": f"artifacts/research/{task_id}.research.md",
        "plan": f"artifacts/plans/{task_id}.plan.md",
        "code": f"artifacts/code/{task_id}.code.md",
        "verify": f"artifacts/verify/{task_id}.verify.md",
        "status": f"artifacts/status/{task_id}.status.json",
        "improvement": f"artifacts/improvement/{task_id}.improvement.md",
    }
    for relative in artifact_map.values():
        if (root / relative).exists():
            results.append(relative)
    return results


def migrate_decision_text(root: Path, task_id: str, text: str) -> str:
    title, sections = split_markdown_sections(text)
    decision_class = sections.get("Decision Class", "").strip()
    used_default = False
    if not decision_class:
        decision_class, used_default = infer_decision_class(text)
    affected_gate = sections.get("Affected Gate", "").strip() or infer_affected_gate(text)
    scope_body = sections.get("Scope", "Current task artifact governance and exception handling.")
    linked = sections.get("Linked Artifacts", "").strip()
    if not linked:
        linked = ensure_list_body(f"- `{path}`" for path in linked_artifacts_for_task(root, task_id))
    follow_up = sections.get("Follow Up", "None")
    if used_default and "[WARN] migrated default" not in follow_up:
        follow_up = first_non_empty(
            follow_up,
            "None",
        )
        follow_up = f"[WARN] migrated default: Decision Class defaulted to risk-acceptance.\n{follow_up}"

    ordered_sections: List[Tuple[str, str]] = []
    for heading in DECISION_SECTION_ORDER:
        if heading == "Decision Class":
            body = decision_class
        elif heading == "Affected Gate":
            body = affected_gate
        elif heading == "Scope":
            body = scope_body
        elif heading == "Linked Artifacts":
            body = linked
        elif heading == "Follow Up":
            body = follow_up
        else:
            body = sections.get(heading, "None")
        ordered_sections.append((heading, body))
    return render_markdown(title, ordered_sections)


def extract_checkbox_items(section_text: str) -> List[Tuple[bool, str]]:
    items: List[Tuple[bool, str]] = []
    for line in section_text.splitlines():
        match = re.match(r"^- \[([xX ])\]\s*(.+?)\s*$", line.strip())
        if match:
            items.append((match.group(1).strip().lower() == "x", match.group(2).strip()))
    return items


def extract_heading_checklist_items(section_text: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    blocks = [block.strip() for block in re.split(r"\n\s*\n", section_text) if block.strip()]
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        heading_match = re.match(r"^###\s+(?:AC-\d+:\s*)?(.+?)\s*$", lines[0].strip())
        if not heading_match:
            continue
        fields = gsv.parse_structured_checklist_fields("\n".join(lines[1:]))
        result_raw = str(fields.get("result", "")).strip().lower()
        if result_raw.startswith("pass") or result_raw == "verified":
            result_value = "verified"
        elif result_raw.startswith("fail") or result_raw in {"failed", "unverified"}:
            result_value = "unverified"
        elif result_raw in {"unverifiable", "deferred"}:
            result_value = result_raw
        else:
            result_value = "unverified"
        item: Dict[str, str] = {
            "criterion": heading_match.group(1).strip(),
            "method": "Artifact and command evidence review",
            "evidence": str(fields.get("evidence", "")).strip() or "See Evidence Refs",
            "result": result_value,
        }
        if result_value != "verified":
            item["reason_code"] = "MANUAL_CHECK_DEFERRED"
        items.append(item)
    return items


def render_verify_item(fields: Dict[str, str]) -> str:
    block_lines = []
    for key in ("criterion", "method", "evidence", "result", "decision_ref", "reason_code", "reviewer", "timestamp"):
        value = str(fields.get(key, "")).strip()
        if value:
            block_lines.append(f"- **{key}**: {value}")
    return "\n".join(block_lines)


def select_trusted_structured_items(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    required_fields = {"criterion", "method", "evidence", "result"}
    trusted_items = [fields for fields in items if required_fields.issubset({key.strip().lower() for key in fields})]
    return trusted_items if trusted_items and len(trusted_items) == len(items) else []


def build_external_manual_review_item(
    criterion: str,
    evidence: str,
    *,
    source_label: str,
    original_result: str = "",
) -> Dict[str, str]:
    detail = evidence.strip() if evidence.strip() else "Legacy artifact content requires manual confirmation."
    if original_result:
        detail = f"{detail} Original legacy result hint: {original_result}."
    return {
        "criterion": criterion.strip() or "Legacy criterion requires manual rewrite",
        "method": f"Legacy artifact import review ({source_label})",
        "evidence": detail,
        "result": "deferred",
        "reason_code": "MANUAL_CHECK_DEFERRED",
    }


def assess_verify_migration(
    legacy_checklist: str,
    evidence_lines: List[str],
    existing_items: List[Dict[str, str]],
    heading_items: List[Dict[str, str]],
    checkbox_items: List[Tuple[bool, str]],
    input_mode: str,
) -> Tuple[str, VerifyMigrationAssessment]:
    trusted_structured_items = select_trusted_structured_items(existing_items)
    if input_mode == ROOT_TRACKED_MODE:
        rendered_items: List[str] = []
        if trusted_structured_items:
            rendered_items.extend(render_verify_item(fields) for fields in trusted_structured_items)
            return "\n\n".join(rendered_items), VerifyMigrationAssessment(
                strategy="structured-checklist",
                confidence="high",
                manual_review_required=False,
            )
        if heading_items:
            rendered_items.extend(render_verify_item(fields) for fields in heading_items)
            return "\n\n".join(rendered_items), VerifyMigrationAssessment(
                strategy="heading-block-heuristic",
                confidence="medium",
                manual_review_required=False,
                unresolved_fields=["criterion", "result"],
            )
        if checkbox_items:
            for index, (checked, criterion) in enumerate(checkbox_items):
                evidence_value = evidence_lines[index] if index < len(evidence_lines) else (evidence_lines[0] if evidence_lines else "See Evidence Refs")
                rendered_items.append(
                    render_verify_item(
                        {
                            "criterion": criterion,
                            "method": "Artifact and command evidence review",
                            "evidence": evidence_value,
                            "result": "verified" if checked else "unverified",
                            "reason_code": "" if checked else "MANUAL_CHECK_DEFERRED",
                        }
                    )
                )
            return "\n\n".join(rendered_items), VerifyMigrationAssessment(
                strategy="checkbox-heuristic",
                confidence="medium",
                manual_review_required=False,
                unresolved_fields=["criterion", "result", "evidence"],
            )
        fallback = "\n".join(
            [
                "- **criterion**: Legacy verify artifact requires manual rewrite",
                "- **method**: Artifact migration review",
                "- **evidence**: Legacy checklist could not be safely mapped",
                "- **result**: unverified",
                "- **reason_code**: MANUAL_CHECK_DEFERRED",
            ]
        )
        return fallback, VerifyMigrationAssessment(
            strategy="manual-rewrite-fallback",
            confidence="low",
            manual_review_required=True,
            unresolved_fields=["criterion", "method", "evidence", "result"],
        )

    if trusted_structured_items:
        return "\n\n".join(render_verify_item(fields) for fields in trusted_structured_items), VerifyMigrationAssessment(
            strategy="structured-checklist",
            confidence="high",
            manual_review_required=False,
        )

    rendered_items = []
    if heading_items:
        for item in heading_items:
            rendered_items.append(
                render_verify_item(
                    build_external_manual_review_item(
                        item.get("criterion", ""),
                        item.get("evidence", "") or "Legacy heading-block mapping requires manual confirmation.",
                        source_label="heading-block heuristic",
                        original_result=item.get("result", ""),
                    )
                )
            )
        return "\n\n".join(rendered_items), VerifyMigrationAssessment(
            strategy="heading-block-heuristic",
            confidence="medium",
            manual_review_required=True,
            unresolved_fields=["criterion", "result", "reviewer", "timestamp"],
            notes=["Non-structured heading blocks were downgraded to deferred manual-review items."],
        )

    if checkbox_items:
        for index, (_, criterion) in enumerate(checkbox_items):
            evidence_value = evidence_lines[index] if index < len(evidence_lines) else (evidence_lines[0] if evidence_lines else "")
            rendered_items.append(
                render_verify_item(
                    build_external_manual_review_item(
                        criterion,
                        evidence_value or "Legacy checkbox mapping requires manual confirmation.",
                        source_label="checkbox heuristic",
                    )
                )
            )
        return "\n\n".join(rendered_items), VerifyMigrationAssessment(
            strategy="checkbox-heuristic",
            confidence="low",
            manual_review_required=True,
            unresolved_fields=["criterion", "result", "evidence", "reviewer", "timestamp"],
            notes=["Legacy checkbox inputs are never promoted directly to pass in external-legacy mode."],
        )

    fallback = render_verify_item(
        build_external_manual_review_item(
            "Legacy verify artifact requires manual rewrite",
            "Legacy checklist could not be safely mapped.",
            source_label="manual rewrite fallback",
        )
    )
    return fallback, VerifyMigrationAssessment(
        strategy="manual-rewrite-fallback",
        confidence="low",
        manual_review_required=True,
        unresolved_fields=["criterion", "method", "evidence", "result", "reviewer", "timestamp"],
        notes=["No trusted checklist structure was found; manual rewrite is required."],
    )


def build_verify_summary(summary: str, assessment: VerifyMigrationAssessment, input_mode: str) -> str:
    if input_mode != EXTERNAL_LEGACY_MODE:
        return first_non_empty(summary, "Migrated from legacy verify artifact.")
    prefix = (
        f"Imported from external legacy verify artifact via {assessment.strategy}; "
        f"confidence={assessment.confidence}."
    )
    if assessment.manual_review_required:
        prefix += " Manual review required before treating this verify artifact as authoritative."
    return first_non_empty("\n".join([prefix, summary]).strip(), prefix)


def build_verify_recommendation(
    recommendation: str,
    assessment: VerifyMigrationAssessment,
    input_mode: str,
) -> str:
    if input_mode != EXTERNAL_LEGACY_MODE:
        return first_non_empty(recommendation, "None")
    note_lines = [
        f"[WARN] legacy import strategy: {assessment.strategy}",
        f"[WARN] confidence: {assessment.confidence}",
    ]
    if assessment.unresolved_fields:
        note_lines.append(f"[WARN] unresolved fields: {', '.join(assessment.unresolved_fields)}")
    if assessment.manual_review_required:
        note_lines.append("[WARN] manual follow-up: rewrite Acceptance Criteria Checklist before treating this verify artifact as authoritative.")
    note_lines.extend(assessment.notes)
    return merge_named_lines(recommendation, note_lines)


def improvement_profile_for_text(text: str) -> str:
    trigger_match = re.search(r"^- Trigger Type:\s*(.+)$", text, re.MULTILINE)
    trigger = trigger_match.group(1).strip().lower() if trigger_match else ""
    return "gate-e" if trigger == "blocked" else "retrospective"


def migrate_improvement_text(text: str) -> str:
    title, sections = split_markdown_sections(text)
    metadata = sections.get("Metadata", "")
    if "Improvement Profile:" not in metadata:
        profile = improvement_profile_for_text(text)
        metadata = metadata.rstrip() + f"\n- Improvement Profile: {profile}"
    ordered_sections = []
    for heading in IMPROVEMENT_SECTION_ORDER:
        ordered_sections.append((heading, sections.get(heading, "None")))
    return render_markdown(title, (("Metadata", metadata), *ordered_sections[1:]))


def migrate_verify_text(
    root: Path,
    task_id: str,
    state: str,
    assurance_level: str,
    project_adapter: str,
    text: str,
    input_mode: str,
) -> Tuple[str, VerifyMigrationAssessment]:
    relative_verify_path = f"artifacts/verify/{task_id}.verify.md"
    source_text = text
    if "Migrated from legacy verify artifact." in text:
        git_head_text = load_git_head_text(root, relative_verify_path)
        if git_head_text:
            source_text = git_head_text

    title, sections = split_markdown_sections(source_text)
    current_title, current_sections = split_markdown_sections(text)
    if current_sections.get("Metadata", "").strip():
        sections["Metadata"] = current_sections["Metadata"]
    title = current_title or title
    legacy_checklist = sections.get("Acceptance Criteria Checklist", "")
    existing_items = gsv.parse_verify_checklist_items(legacy_checklist)
    evidence_lines = gsv.parse_list_items(sections.get("Evidence", ""))
    evidence_refs_existing = [
        gsv.normalize_path_token(value)
        for value in gsv.parse_list_items(sections.get("Evidence Refs", ""))
        if gsv.normalize_path_token(value)
    ]
    extracted_evidence_refs = [] if evidence_refs_existing else extract_path_like_tokens(sections.get("Evidence", ""))
    decision_ref_path = f"artifacts/decisions/{task_id}.decision.md"
    decision_refs = [decision_ref_path] if (root / decision_ref_path).exists() else []
    heading_items = extract_heading_checklist_items(legacy_checklist)
    checkbox_items = extract_checkbox_items(legacy_checklist)
    checklist_body, assessment = assess_verify_migration(
        legacy_checklist,
        evidence_lines,
        existing_items,
        heading_items,
        checkbox_items,
        input_mode,
    )
    provisional = render_markdown(
        title,
        (
            ("Metadata", sections.get("Metadata", "")),
            ("Verification Summary", build_verify_summary(sections.get("Verification Summary", ""), assessment, input_mode)),
            ("Acceptance Criteria Checklist", checklist_body),
            ("Overall Maturity", "poc"),
            ("Deferred Items", first_non_empty(sections.get("Deferred Items", ""), sections.get("Remaining Gaps", ""), "None")),
            ("Evidence", first_non_empty(sections.get("Evidence", ""), "None")),
            ("Evidence Refs", ensure_list_body(f"- `{path}`" for path in sorted(set(evidence_refs_existing + extracted_evidence_refs)))),
            ("Decision Refs", ensure_list_body(f"- `{path}`" for path in decision_refs)),
            ("Build Guarantee", first_non_empty(sections.get("Build Guarantee", ""), "None (no .csproj modified)")),
            ("Pass Fail Result", first_non_empty(gsv.extract_single_line_section(text, "Pass Fail Result").lower(), "pass")),
            ("Recommendation", build_verify_recommendation(sections.get("Recommendation", ""), assessment, input_mode)),
        ),
    )
    verify_contract = gsv.collect_verify_contract(
        provisional,
        assurance_level=assurance_level,
        project_adapter=project_adapter,
        state=state,
    )
    deferred_items = sections.get("Deferred Items", "").strip()
    if not deferred_items:
        deferred_items = sections.get("Remaining Gaps", "").strip()
    if not deferred_items:
        deferred_items = ensure_list_body(f"- {item}" for item in verify_contract["open_verification_debts"])
    overall_maturity = str(verify_contract["computed_readiness"])
    pass_fail = "fail" if verify_contract["open_verification_debts"] else "pass"
    ordered_sections = (
        ("Metadata", sections.get("Metadata", "")),
        ("Verification Summary", build_verify_summary(sections.get("Verification Summary", ""), assessment, input_mode)),
        ("Acceptance Criteria Checklist", checklist_body),
        ("Overall Maturity", overall_maturity),
        ("Deferred Items", deferred_items or "None"),
        ("Evidence", first_non_empty(sections.get("Evidence", ""), "None")),
        ("Evidence Refs", ensure_list_body(f"- `{path}`" for path in sorted(set(evidence_refs_existing + extracted_evidence_refs)))),
        ("Decision Refs", ensure_list_body(f"- `{path}`" for path in decision_refs)),
        ("Build Guarantee", first_non_empty(sections.get("Build Guarantee", ""), "None (no .csproj modified)")),
        ("Pass Fail Result", pass_fail),
        ("Recommendation", build_verify_recommendation(sections.get("Recommendation", ""), assessment, input_mode)),
    )
    return render_markdown(title, ordered_sections), assessment


def migrate_status_payload(root: Path, task_id: str, status: dict) -> dict:
    artifacts_root = root / "artifacts"
    task_path = gsv.artifact_path(artifacts_root, task_id, "task")
    task_text = gsv.load_text(task_path) if task_path.exists() else ""
    state = gsv.resolve_status_state(status) or "drafted"
    assurance_level = gsv.resolve_assurance_level(task_text, status)
    project_adapter = gsv.resolve_project_adapter(task_text, status)
    existing = gsv.compute_existing_artifacts(artifacts_root, task_id)
    required = sorted(
        gsv.state_required_artifacts(
            state,
            existing,
            assurance_level=assurance_level,
            project_adapter=project_adapter,
        )
    )
    verify_path = gsv.artifact_path(artifacts_root, task_id, "verify")
    verify_contract = None
    if verify_path.exists():
        verify_contract = gsv.collect_verify_contract(
            gsv.load_text(verify_path),
            assurance_level=assurance_level,
            project_adapter=project_adapter,
            state=state,
        )
    blocked_reason = str(status.get("blocked_reason", "")).strip()
    if not blocked_reason and state == "blocked":
        blockers = status.get("blockers", [])
        if isinstance(blockers, list) and blockers:
            blocked_reason = str(blockers[0]).strip()
        blocked_reason = blocked_reason or "Blocked reason migrated from legacy status schema"
    migrated = {
        "task_id": task_id,
        "state": state,
        "current_owner": str(status.get("current_owner") or status.get("owner") or gsv.DEFAULT_STATUS_OWNER),
        "next_agent": str(status.get("next_agent") or gsv.default_next_agent_for_state(state)),
        "required_artifacts": required,
        "available_artifacts": sorted(existing),
        "missing_artifacts": sorted(set(required) - existing),
        "blocked_reason": blocked_reason if state == "blocked" else "",
        "last_updated": str(status.get("last_updated") or gsv.current_taipei_timestamp()),
        "assurance_level": assurance_level,
        "project_adapter": project_adapter,
        "open_verification_debts": verify_contract["open_verification_debts"] if verify_contract else [],
        "verification_readiness": (
            verify_contract["computed_readiness"]
            if verify_contract
            else gsv.derive_verification_readiness(assurance_level, project_adapter, state, [])
        ),
    }
    for optional_key in ("decision_waivers", "auto_upgrade_log", "Gate_E_passed", "Gate_E_evidence", "Gate_E_timestamp"):
        if optional_key in status:
            migrated[optional_key] = status[optional_key]
    return migrated


def write_if_changed(path: Path, content: str, apply: bool) -> bool:
    current = normalize_newlines(path.read_text(encoding="utf-8"))
    updated = normalize_newlines(content)
    if current == updated:
        return False
    if apply:
        path.write_text(updated, encoding="utf-8")
    return True


def write_json_if_changed(path: Path, payload: dict, apply: bool) -> bool:
    updated = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    current = path.read_text(encoding="utf-8")
    if current == updated:
        return False
    if apply:
        path.write_text(updated, encoding="utf-8")
    return True


def migrate_repository(root: Path, apply: bool, input_mode: str = ROOT_TRACKED_MODE) -> MigrationReport:
    report = MigrationReport(apply=apply)
    status_dir = root / "artifacts" / "status"
    for task_path in sorted((root / "artifacts" / "tasks").glob("TASK-*.task.md")):
        task_id = task_path.stem.split(".")[0]
        status_path = status_dir / f"{task_id}.status.json"
        status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
        migrated = migrate_task_text(
            task_path.read_text(encoding="utf-8"),
            assurance_level=str(status.get("assurance_level") or DEFAULT_ASSURANCE_LEVEL),
            project_adapter=str(status.get("project_adapter") or DEFAULT_PROJECT_ADAPTER),
        )
        changed = write_if_changed(task_path, migrated, apply)
        report.changes.append(MigrationChange(task_path.relative_to(root).as_posix(), changed, "task profile normalization"))

    for decision_path in sorted((root / "artifacts" / "decisions").glob("TASK-*.decision.md")):
        task_id = decision_path.stem.split(".")[0]
        migrated = migrate_decision_text(root, task_id, decision_path.read_text(encoding="utf-8"))
        changed = write_if_changed(decision_path, migrated, apply)
        report.changes.append(MigrationChange(decision_path.relative_to(root).as_posix(), changed, "decision taxonomy normalization"))

    for improvement_path in sorted((root / "artifacts" / "improvement").glob("TASK-*.improvement.md")):
        migrated = migrate_improvement_text(improvement_path.read_text(encoding="utf-8"))
        changed = write_if_changed(improvement_path, migrated, apply)
        report.changes.append(MigrationChange(improvement_path.relative_to(root).as_posix(), changed, "improvement profile normalization"))

    for verify_path in sorted((root / "artifacts" / "verify").glob("TASK-*.verify.md")):
        task_id = verify_path.stem.split(".")[0]
        status_path = status_dir / f"{task_id}.status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        migrated, assessment = migrate_verify_text(
            root,
            task_id,
            state=gsv.resolve_status_state(status) or "done",
            assurance_level=str(status.get("assurance_level") or DEFAULT_ASSURANCE_LEVEL),
            project_adapter=str(status.get("project_adapter") or DEFAULT_PROJECT_ADAPTER),
            text=verify_path.read_text(encoding="utf-8"),
            input_mode=input_mode,
        )
        changed = write_if_changed(verify_path, migrated, apply)
        notes = []
        if input_mode == EXTERNAL_LEGACY_MODE:
            notes.append(f"strategy={assessment.strategy}")
            notes.append(f"confidence={assessment.confidence}")
            if assessment.unresolved_fields:
                notes.append(f"unresolved_fields={','.join(assessment.unresolved_fields)}")
            if assessment.manual_review_required:
                notes.append("manual_review_required=true")
        report.changes.append(
            MigrationChange(
                verify_path.relative_to(root).as_posix(),
                changed,
                "verify structured checklist normalization",
                notes=notes,
            )
        )

    for status_path in sorted(status_dir.glob("TASK-*.status.json")):
        task_id = status_path.stem.split(".")[0]
        migrated = migrate_status_payload(root, task_id, json.loads(status_path.read_text(encoding="utf-8")))
        changed = write_json_if_changed(status_path, migrated, apply)
        report.changes.append(MigrationChange(status_path.relative_to(root).as_posix(), changed, "status schema normalization"))

    return report


def print_report(report: MigrationReport) -> None:
    mode = "apply" if report.apply else "dry-run"
    print(f"[OK] Artifact schema migration {mode} complete")
    print(f"[OK] changed_files={report.changed_count()} total_checked={len(report.changes)}")
    for change in report.changes:
        status = "[CHANGED]" if change.changed else "[OK]"
        print(f"{status} {change.relative_path} :: {change.detail}")
        for note in change.notes:
            print(f"  [NOTE] {note}")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    report = migrate_repository(root, apply=args.apply, input_mode=args.input_mode)
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
