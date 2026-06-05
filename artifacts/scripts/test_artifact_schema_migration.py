"""Split unit tests for artifact schema migration and legacy verify corpus per TASK-1054."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import subprocess as _subprocess
import sys
import textwrap
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import unittest.mock

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import guard_status_validator as gsv
import guard_contract_validator as gcv
import prompt_regression_validator as prv
import build_decision_registry as bdr
import aggregate_red_team_scorecard as ars
import validate_scorecard_deltas as vsd
import validate_context_stack as vcs
import migrate_artifact_schema as mas
import legacy_verify_corpus as lvc
import workflow_constants as wc
import classify_existing_tasks as cet
import backfill_pdca_labels as bpl
import discover_templates as dt
import update_repository_profile as urp
import repo_health_dashboard as rhd
import run_red_team_suite as rrts

TAIPEI_TZ = timezone(timedelta(hours=8))

def _make_artifact_tree(tmp_path, task_id, artifact_types):
    """Helper: create minimal artifact files in a tmp_path artifacts tree."""
    for atype in artifact_types:
        d = tmp_path / gsv.ARTIFACT_DIRS[atype]
        d.mkdir(parents=True, exist_ok=True)
        ext = gsv.ARTIFACT_EXTENSIONS[atype]
        if ext.endswith(".json"):
            (d / f"{task_id}{ext}").write_text(
                json.dumps({"task_id": task_id, "state": "drafted"}, indent=2),
                encoding="utf-8",
            )
        else:
            (d / f"{task_id}{ext}").write_text(f"# Artifact\n- Task ID: {task_id}\n", encoding="utf-8")

def _ts():
    """Return a valid Taipei timestamp string."""
    return "2026-01-15T10:00:00+08:00"

def _future_ts():
    """Return a future Taipei timestamp for waiver expiry."""
    return "2099-12-31T23:59:59+08:00"

def _make_full_status(task_id, state="drafted", **overrides):
    """Build a valid modern status.json dict.

    TASK-1008 strict mode requires `assurance_level`; TASK-1047 added it as
    a default here so that test fixtures default to a valid status payload.
    Tests that intentionally exercise the missing-field path should pass
    `assurance_level=None` or pop it from the returned dict.
    """
    base = {
        "task_id": task_id,
        "state": state,
        "current_owner": "Claude",
        "next_agent": "Claude",
        "required_artifacts": ["task", "status"],
        "available_artifacts": ["task", "status"],
        "missing_artifacts": [],
        "assurance_level": "poc",
        "project_adapter": "generic",
        "verification_readiness": "poc",
        "open_verification_debts": [],
        "blocked_reason": "",
        "last_updated": _ts(),
    }
    base.update(overrides)
    return base

def _write_status(tmp_path, task_id, status_dict):
    d = tmp_path / "status"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{task_id}.status.json"
    p.write_text(json.dumps(status_dict, indent=2) + "\n", encoding="utf-8")
    return p

def _write_markdown_artifact(tmp_path, task_id, atype, extra_content=""):
    """Create a minimal valid markdown artifact."""
    markers = gsv.MARKERS[atype]
    dirname = gsv.ARTIFACT_DIRS[atype]
    ext = gsv.ARTIFACT_EXTENSIONS[atype]
    d = tmp_path / dirname
    d.mkdir(parents=True, exist_ok=True)

    allowed = gsv.ARTIFACT_ALLOWED_STATUSES.get(atype, {"drafted"})
    status_val = next(iter(sorted(allowed)))

    def _first_alt(m):
        # MARKERS may contain tuple-of-alternatives (v2 governance extension); the
        # test fixture only needs one valid alternative. See docs/artifact_schema.md §5.13.
        return m[0] if isinstance(m, tuple) else m

    lines = [_first_alt(markers[0]) + f" {task_id}"]
    lines.append("## Metadata")
    lines.append(f"- Artifact Type: {atype}")
    lines.append(f"- Task ID: {task_id}")
    lines.append("- Owner: Claude")
    lines.append(f"- Status: {status_val}")
    lines.append(f"- Last Updated: {_ts()}")
    lines.append("")

    # Add all remaining markers as sections (skip those provided in extra_content)
    for raw_marker in markers[1:]:
        marker = _first_alt(raw_marker)
        if marker.startswith("## "):
            if extra_content and marker in extra_content:
                continue
            lines.append(marker)
            lines.append("Content placeholder")
            lines.append("")
        elif marker.endswith(":") and not marker.startswith("#"):
            # Inline field like "Task ID:" already handled in metadata
            pass

    if extra_content:
        lines.append(extra_content)
    content = "\n".join(lines) + "\n"
    p = d / f"{task_id}{ext}"
    p.write_text(content, encoding="utf-8")
    return p

def _build_task_artifact(tmp_path, task_id):
    d = tmp_path / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        # Task: Test Task
        ## Metadata
        - Artifact Type: task
        - Task ID: {task_id}
        - Owner: Claude
        - Status: approved
        - Last Updated: {_ts()}
        ## Objective
        Test objective
        ## Constraints
        None
        ## Acceptance Criteria
        Done when tested
        ## Assurance Level
        poc
        ## Project Adapter
        generic
    """)
    p = d / f"{task_id}.task.md"
    p.write_text(content, encoding="utf-8")
    return p

def _build_plan_artifact(tmp_path, task_id, ready="yes", risk_count=4):
    d = tmp_path / "plans"
    d.mkdir(parents=True, exist_ok=True)
    risks = ""
    for i in range(1, risk_count + 1):
        sev = "blocking" if i <= 2 else "non-blocking"
        risks += textwrap.dedent(f"""\
            R{i}: Risk {i}
            - Risk: Something might break
            - Trigger: When X happens
            - Detection: Monitor logs
            - Mitigation: Roll back
            - Severity: {sev}
        """)
    content = textwrap.dedent(f"""\
        # Plan: {task_id}
        ## Metadata
        - Artifact Type: plan
        - Task ID: {task_id}
        - Owner: Claude
        - Status: approved
        - Last Updated: {_ts()}
        ## Scope
        Test scope
        ## Files Likely Affected
        - `src/main.py`
        - `tests/test_main.py`
        ## Proposed Changes
        Change things
        ## Validation Strategy
        Run tests
        ## Risks
        {risks}
        ## Ready For Coding
        {ready}
    """)
    p = d / f"{task_id}.plan.md"
    p.write_text(content, encoding="utf-8")
    return p

def _build_code_artifact(tmp_path, task_id):
    d = tmp_path / "code"
    d.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        # Code Result: {task_id}
        ## Metadata
        - Artifact Type: code
        - Task ID: {task_id}
        - Owner: Claude
        - Status: ready
        - Last Updated: {_ts()}
        ## Files Changed
        - `src/main.py`
        - `tests/test_main.py`
        ## Summary Of Changes
        Implemented feature
        ## Mapping To Plan
        - plan_item: 1.1, status: done, evidence: "Implemented in src/main.py"
    """)
    p = d / f"{task_id}.code.md"
    p.write_text(content, encoding="utf-8")
    return p

def _build_verify_artifact(tmp_path, task_id, result="pass"):
    d = tmp_path / "verify"
    d.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        # Verification: {task_id}
        ## Metadata
        - Artifact Type: verify
        - Task ID: {task_id}
        - Owner: Claude
        - Status: {result}
        - Last Updated: {_ts()}
        ## Acceptance Criteria Checklist
        - **Criterion**: Tests pass
        - **Method**: pytest
        - **Evidence**: All green
        - **Result**: verified
        - **Reviewer**: Claude
        - **Timestamp**: {_ts()}
        ## Pass Fail Result
        {result}
        ## Build Guarantee
        Commit abc1234
    """)
    p = d / f"{task_id}.verify.md"
    p.write_text(content, encoding="utf-8")
    return p

def _build_research_artifact(tmp_path, task_id):
    d = tmp_path / "research"
    d.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent(f"""\
        # Research: {task_id}
        ## Metadata
        - Artifact Type: research
        - Task ID: {task_id}
        - Owner: Claude
        - Status: ready
        - Last Updated: {_ts()}
        ## Research Questions
        How does X work?
        ## Confirmed Facts
        - X uses Y approach `docs/x.md`
        - Z is faster https://example.com/z
        ## Relevant References
        See docs
        ## Uncertain Items
        - UNVERIFIED: Might be slow
        ## Constraints For Implementation
        Must use Y
        ## Sources
        [1] Author. "Title." https://example.com (2026-01-15 retrieved)
        [2] Author2. "Title2." https://example2.com (2026-01-14 retrieved)
    """)
    p = d / f"{task_id}.research.md"
    p.write_text(content, encoding="utf-8")
    return p

def _setup_done_tree(tmp_path, task_id="TASK-001"):
    """Set up a complete artifact tree for 'done' state."""
    _build_task_artifact(tmp_path, task_id)
    _build_plan_artifact(tmp_path, task_id)
    _build_code_artifact(tmp_path, task_id)
    _build_verify_artifact(tmp_path, task_id)
    status = _make_full_status(task_id, "done",
        required_artifacts=["task", "code", "verify", "status"],
        available_artifacts=["task", "plan", "code", "verify", "status"],
        missing_artifacts=[])
    _write_status(tmp_path, task_id, status)
    return task_id

def _mock_subprocess_run(returncode=0, stdout="", stderr=""):
    """Helper to create a mock subprocess.CompletedProcess."""
    mock = MagicMock(spec=subprocess.CompletedProcess)
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock

def _setup_valid_done_tree(tmp_path, task_id="TASK-001"):
    """Set up a complete artifact tree for 'done' state with properly formatted artifacts."""
    _write_markdown_artifact(tmp_path, task_id, "task", "## Objective\nTest objective\n## Constraints\nSome constraints\n## Acceptance Criteria\nDone when tested\n## Assurance Level\npoc\n## Project Adapter\ngeneric\n")
    plan_extra = (
        "## Scope\nTest scope\n"
        "## Files Likely Affected\n- `src/main.py`\n- `tests/test_main.py`\n"
        "## Proposed Changes\nChange things\n"
        "## Validation Strategy\nRun tests\n"
        "## Risks\n"
        "R1: Risk 1\n- Risk: Something\n- Trigger: When X\n- Detection: Monitor\n- Mitigation: Rollback\n- Severity: blocking\n"
        "R2: Risk 2\n- Risk: Something\n- Trigger: When Y\n- Detection: Monitor\n- Mitigation: Rollback\n- Severity: blocking\n"
        "R3: Risk 3\n- Risk: Something\n- Trigger: When Z\n- Detection: Monitor\n- Mitigation: Rollback\n- Severity: non-blocking\n"
        "R4: Risk 4\n- Risk: Something\n- Trigger: When W\n- Detection: Monitor\n- Mitigation: Rollback\n- Severity: non-blocking\n"
        "## Ready For Coding\nyes\n"
    )
    _write_markdown_artifact(tmp_path, task_id, "plan", plan_extra)
    code_extra = "## Files Changed\n- `src/main.py`\n- `tests/test_main.py`\n## Summary Of Changes\nImplemented feature\n"
    _write_markdown_artifact(tmp_path, task_id, "code", code_extra)
    verify_extra = "## Build Guarantee\nCommit abc123\n## Pass Fail Result\npass\n"
    _write_markdown_artifact(tmp_path, task_id, "verify", verify_extra)
    research_extra = (
        "## Research Questions\n- How does X work?\n"
        "## Confirmed Facts\n- X works via Y — see https://example.com/docs\n"
        "## Sources\n[1] Example Org. \"Example Doc.\" https://example.com/docs (2026-01-15 retrieved)\n[2] Another Org. \"Ref Guide.\" https://example.org/ref (2026-01-15 retrieved)\n"
        "## Relevant References\n- https://example.com\n"
        "## Uncertain Items\n- UNVERIFIED: Z might also apply\n"
        "## Constraints For Implementation\nMust use Y approach\n"
    )
    _write_markdown_artifact(tmp_path, task_id, "research", research_extra)
    status = _make_full_status(task_id, "done",
        required_artifacts=["task", "code", "verify", "research", "status"],
        available_artifacts=["task", "plan", "code", "verify", "research", "status"],
        missing_artifacts=[])
    _write_status(tmp_path, task_id, status)
    return task_id

def _make_diff_evidence_code(tmp_path, evidence_type, snapshot_files, extra_fields=None):
    """Helper: create a code artifact with ## Diff Evidence section."""
    sha = gsv.compute_snapshot_sha256(snapshot_files) if snapshot_files else ""
    lines = [
        "## Diff Evidence",
        f"- Evidence Type: {evidence_type}",
        f"- Changed Files Snapshot: {', '.join(sorted(snapshot_files))}",
        f"- Snapshot SHA256: {sha}",
    ]
    if extra_fields:
        for k, v in extra_fields.items():
            lines.append(f"- {k}: {v}")
    code_path = tmp_path / "code.md"
    code_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code_path

_FAKE_BASE = "a" * 40

_FAKE_HEAD = "b" * 40

def _make_diff_evidence_code(tmp_path, evidence_type, snapshot_files, extra_fields=None):
    """Helper: create a code artifact with ## Diff Evidence section."""
    sha = gsv.compute_snapshot_sha256(snapshot_files) if snapshot_files else ""
    lines = [
        "## Diff Evidence",
        f"- Evidence Type: {evidence_type}",
        f"- Changed Files Snapshot: {', '.join(sorted(snapshot_files))}",
        f"- Snapshot SHA256: {sha}",
    ]
    if extra_fields:
        for k, v in extra_fields.items():
            lines.append(f"- {k}: {v}")
    code_path = tmp_path / "code.md"
    code_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code_path

_FAKE_BASE = "a" * 40

_FAKE_HEAD = "b" * 40


class TestArtifactSchemaMigration:
    LEGACY_CORPUS_CASE_IDS = (
        "structured-checklist-complete",
        "heading-block-partial",
        "checkbox-list-mixed",
        "unparseable-fragment",
    )

    def _seed_repo(self, tmp_path):
        for relative in (
            "artifacts/tasks",
            "artifacts/decisions",
            "artifacts/verify",
            "artifacts/status",
        ):
            (tmp_path / relative).mkdir(parents=True, exist_ok=True)
        (tmp_path / "artifacts" / "tasks" / "TASK-001.task.md").write_text(
            textwrap.dedent("""\
                # Task: TASK-001
                ## Metadata
                - Task ID: TASK-001
                - Artifact Type: task
                - Owner: Claude
                - Status: approved
                - Last Updated: 2026-01-15T10:00:00+08:00
                ## Objective
                Goal
                ## Background
                None
                ## Inputs
                None
                ## Constraints
                Keep scope fixed
                ## Acceptance Criteria
                - [x] A
                ## Dependencies
                None
                ## Out of Scope
                - None
                ## Current Status Summary
                Planned
            """),
            encoding="utf-8",
        )
        (tmp_path / "artifacts" / "decisions" / "TASK-001.decision.md").write_text(
            textwrap.dedent("""\
                # Decision Log: TASK-001
                ## Metadata
                - Task ID: TASK-001
                - Artifact Type: decision
                - Owner: Claude
                - Status: done
                - Last Updated: 2026-01-15T10:00:00+08:00
                ## Issue
                Verify migration
                ## Chosen Option
                Keep migration conservative
                ## Reasoning
                Preserve traceability
            """),
            encoding="utf-8",
        )
        (tmp_path / "artifacts" / "verify" / "TASK-001.verify.md").write_text(
            textwrap.dedent("""\
                # Verification: TASK-001
                ## Metadata
                - Task ID: TASK-001
                - Artifact Type: verify
                - Owner: Claude
                - Status: pass
                - Last Updated: 2026-01-15T10:00:00+08:00
                ## Acceptance Criteria Checklist
                - [x] A
                ## Evidence
                - `artifacts/tasks/TASK-001.task.md`
                ## Build Guarantee
                None (no .csproj modified)
                ## Pass Fail Result
                pass
                ## Remaining Gaps
                None
            """),
            encoding="utf-8",
        )
        (tmp_path / "artifacts" / "status" / "TASK-001.status.json").write_text(
            json.dumps(
                {
                    "task_id": "TASK-001",
                    "current_state": "verify_ready",
                    "owner": "Claude",
                    "last_updated": "2026-01-15T10:00:00+08:00",
                    "artifacts": {"task": "artifacts/tasks/TASK-001.task.md"},
                    "next_action": "Migrate",
                    "blockers": [],
                    "available_artifacts": ["decision", "status", "task", "verify"],
                    "assurance_level": "poc",
                    "project_adapter": "generic",
                    "open_verification_debts": [],
                    "state": "done",
                    "required_artifacts": ["task", "code", "verify", "status"],
                    "missing_artifacts": ["code"],
                    "blocked_reason": "",
                    "current_owner": "Claude",
                    "next_agent": "Claude",
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    def _write_verify_from_corpus(self, tmp_path, case_id):
        case = lvc.load_corpus_case(case_id)
        verify_path = tmp_path / "artifacts" / "verify" / "TASK-001.verify.md"
        verify_path.write_text(case.text.replace("TASK-LEGACY", "TASK-001"), encoding="utf-8")
        return case, verify_path

    def test_dry_run_does_not_modify_files(self, tmp_path):
        self._seed_repo(tmp_path)
        before = (tmp_path / "artifacts" / "verify" / "TASK-001.verify.md").read_text(encoding="utf-8")
        report = mas.migrate_repository(tmp_path, apply=False)
        after = (tmp_path / "artifacts" / "verify" / "TASK-001.verify.md").read_text(encoding="utf-8")
        assert report.changed_count() > 0
        assert before == after

    def test_apply_is_idempotent(self, tmp_path):
        self._seed_repo(tmp_path)
        first = mas.migrate_repository(tmp_path, apply=True)
        second = mas.migrate_repository(tmp_path, apply=True)
        assert first.changed_count() > 0
        assert second.changed_count() == 0
        verify_text = (tmp_path / "artifacts" / "verify" / "TASK-001.verify.md").read_text(encoding="utf-8")
        assert "## Overall Maturity" in verify_text
        assert "- **result**: verified" in verify_text
        status_payload = json.loads((tmp_path / "artifacts" / "status" / "TASK-001.status.json").read_text(encoding="utf-8"))
        assert "current_state" not in status_payload
        assert status_payload["verification_readiness"] == "poc"

    def test_legacy_verify_corpus_manifest_is_complete(self):
        cases = {case.case_id for case in lvc.load_corpus_cases()}
        assert cases == set(self.LEGACY_CORPUS_CASE_IDS)

    @pytest.mark.parametrize("case_id", LEGACY_CORPUS_CASE_IDS)
    def test_external_legacy_corpus_cases(self, tmp_path, case_id):
        self._seed_repo(tmp_path)
        case, verify_path = self._write_verify_from_corpus(tmp_path, case_id)
        report = mas.migrate_repository(tmp_path, apply=True, input_mode=mas.EXTERNAL_LEGACY_MODE)
        verify_text = verify_path.read_text(encoding="utf-8")
        checklist_items = gsv.parse_verify_checklist_items(gsv.extract_section(verify_text, "Acceptance Criteria Checklist"))
        verify_contract = gsv.collect_verify_contract(verify_text, assurance_level="poc", project_adapter="generic", state="done")
        assert report.changed_count() > 0
        assert case.summary_fragment in verify_text
        assert checklist_items
        assert all(item.get("result") == case.expected_checklist_result for item in checklist_items)
        if case.expected_reason_code:
            assert all(item.get("reason_code") == case.expected_reason_code for item in checklist_items)
        else:
            assert all(not item.get("reason_code") for item in checklist_items)
        if case.expected_unresolved_fields:
            unresolved_fields = ", ".join(case.expected_unresolved_fields)
            assert f"[WARN] unresolved fields: {unresolved_fields}" in verify_text
        else:
            assert "[WARN] unresolved fields:" not in verify_text
        if case.manual_review_required:
            assert "Manual review required before treating this verify artifact as authoritative." in verify_text
            assert verify_contract["open_verification_debts"]
        else:
            assert "Manual review required before treating this verify artifact as authoritative." not in verify_text
            assert not verify_contract["open_verification_debts"]
        assert f"## Pass Fail Result\n{case.expected_pass_fail_result}" in verify_text

    def test_parse_args_accepts_external_legacy_mode(self):
        args = mas.parse_args(["--input-mode", mas.EXTERNAL_LEGACY_MODE])
        assert args.input_mode == mas.EXTERNAL_LEGACY_MODE

    def test_evidence_refs_ignore_command_lines(self, tmp_path):
        self._seed_repo(tmp_path)
        verify_path = tmp_path / "artifacts" / "verify" / "TASK-001.verify.md"
        verify_path.write_text(
            textwrap.dedent("""\
                # Verification: TASK-001
                ## Metadata
                - Task ID: TASK-001
                - Artifact Type: verify
                - Owner: Claude
                - Status: pass
                - Last Updated: 2026-01-15T10:00:00+08:00
                ## Acceptance Criteria Checklist
                - **criterion**: A
                - **method**: Artifact review
                - **evidence**: `artifacts/tasks/TASK-001.task.md`
                - **result**: verified
                ## Evidence
                - `python -m pytest artifacts/scripts/test_guard_units.py` -> `991 passed`
                - `artifacts/tasks/TASK-001.task.md`
                ## Build Guarantee
                None (no .csproj modified)
                ## Pass Fail Result
                pass
                ## Remaining Gaps
                None
            """),
            encoding="utf-8",
        )
        mas.migrate_repository(tmp_path, apply=True, input_mode=mas.ROOT_TRACKED_MODE)
        verify_text = verify_path.read_text(encoding="utf-8")
        evidence_refs = gsv.parse_list_items(gsv.extract_section(verify_text, "Evidence Refs"))
        normalized_refs = [gsv.normalize_path_token(item) for item in evidence_refs]
        assert "artifacts/tasks/TASK-001.task.md" in normalized_refs
        assert not any("pytest" in item for item in evidence_refs)


# ─────────────────────────────────────────────
# prompt_regression_validator
# ─────────────────────────────────────────────

class TestMigrateArtifactSchemaCoverageCatchup:
    def test_first_non_empty_returns_empty_when_all_blank(self):
        assert mas.first_non_empty("", "   ", "") == ""

    def test_merge_named_lines_dedupes_repeats(self):
        result = mas.merge_named_lines("foo", ["foo", "bar", "bar", ""])
        assert result.count("foo") == 1
        assert result.count("bar") == 1
        assert "\n" in result

    def test_merge_named_lines_empty_returns_none(self):
        assert mas.merge_named_lines("", []) == "None"

    def test_is_path_like_reference_rejects_whitespace(self):
        assert mas.is_path_like_reference("has space") is False

    def test_is_path_like_reference_rejects_empty(self):
        assert mas.is_path_like_reference("") is False

    def test_is_path_like_reference_accepts_prefix(self):
        assert mas.is_path_like_reference("artifacts/tasks/X.task.md") is True

    def test_load_git_head_text_returns_stdout_on_success(self, monkeypatch, tmp_path):
        class _FakeResult:
            stdout = "HEAD body"
        monkeypatch.setattr(mas.subprocess, "run", lambda *a, **kw: _FakeResult())
        assert mas.load_git_head_text(tmp_path, "any.md") == "HEAD body"

    def test_load_git_head_text_returns_empty_on_error(self, monkeypatch, tmp_path):
        def _raise(*args, **kwargs):
            raise _subprocess.CalledProcessError(1, ["git"])
        monkeypatch.setattr(mas.subprocess, "run", _raise)
        assert mas.load_git_head_text(tmp_path, "missing.md") == ""

    def test_detect_docs_spec_task_true_when_signals_accumulate(self):
        text = "readme\nworkflow file\ndocs/x\nschema\nartifact"
        assert mas.detect_docs_spec_task(text) is True

    def test_detect_docs_spec_task_false_when_signals_thin(self):
        assert mas.detect_docs_spec_task("unrelated topic") is False

    def test_migrate_task_text_keeps_generic_when_docs_spec_signals(self):
        text = (
            "# Task: TASK-X\n"
            "## Metadata\n"
            "- Task ID: TASK-X\n"
            "## Objective\n"
            "Update README workflow file docs/ schema runbook documentation\n"
        )
        result = mas.migrate_task_text(text, assurance_level="poc", project_adapter=mas.DEFAULT_PROJECT_ADAPTER)
        assert "## Project Adapter" in result
        assert mas.DEFAULT_PROJECT_ADAPTER in result

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Exception type: allow-scope-drift", ("scope-drift-waiver", False)),
            ("we decided to defer", ("defer", False)),
            ("propose to reject", ("reject", False)),
            ("there is a conflict", ("conflict-resolution", False)),
            ("plain risk", ("risk-acceptance", True)),
        ],
    )
    def test_infer_decision_class_branches(self, text, expected):
        assert mas.infer_decision_class(text) == expected

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Gate E fired during PDCA", "Gate_E"),
            ("scope drift noticed", "Gate_B"),
            ("allow-scope-drift flagged", "Gate_B"),
            ("missing research context", "Gate_A"),
            ("build failure observed", "Gate_C"),
            (".code.md missing", "Gate_C"),
            ("just verification gap", "Gate_D"),
        ],
    )
    def test_infer_affected_gate_branches(self, text, expected):
        assert mas.infer_affected_gate(text) == expected

    def test_extract_heading_checklist_items_skips_nonheading_blocks(self):
        section = "just plain text\nwith no heading"
        assert mas.extract_heading_checklist_items(section) == []

    def test_extract_heading_checklist_items_skips_blank_block(self):
        assert mas.extract_heading_checklist_items("\n\n   \n\n") == []

    @pytest.mark.parametrize(
        "raw_result,expected",
        [
            ("deferred", "deferred"),
            ("unverifiable", "unverifiable"),
            ("bogus-value", "unverified"),
        ],
    )
    def test_extract_heading_checklist_result_mapping(self, raw_result, expected):
        section = (
            "### AC-1: foo\n"
            f"- **result**: {raw_result}\n"
            "- **evidence**: ev\n"
        )
        items = mas.extract_heading_checklist_items(section)
        assert items, f"expected items, got none for {raw_result}"
        assert items[0]["result"] == expected
        if expected != "verified":
            assert items[0]["reason_code"] == "MANUAL_CHECK_DEFERRED"

    def test_assess_verify_root_tracked_heading_items_path(self):
        heading_items = [
            {
                "criterion": "C1",
                "method": "M",
                "evidence": "E",
                "result": "verified",
            }
        ]
        body, assessment = mas.assess_verify_migration(
            legacy_checklist="",
            evidence_lines=[],
            existing_items=[],
            heading_items=heading_items,
            checkbox_items=[],
            input_mode=mas.ROOT_TRACKED_MODE,
        )
        assert assessment.strategy == "heading-block-heuristic"
        assert assessment.manual_review_required is False
        assert "C1" in body

    def test_assess_verify_root_tracked_manual_rewrite_fallback(self):
        body, assessment = mas.assess_verify_migration(
            legacy_checklist="",
            evidence_lines=[],
            existing_items=[],
            heading_items=[],
            checkbox_items=[],
            input_mode=mas.ROOT_TRACKED_MODE,
        )
        assert assessment.strategy == "manual-rewrite-fallback"
        assert assessment.manual_review_required is True
        assert "requires manual rewrite" in body

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("- Trigger Type: blocked", "gate-e"),
            ("- Trigger Type: failure", "retrospective"),
            ("no trigger here", "retrospective"),
        ],
    )
    def test_improvement_profile_for_text(self, text, expected):
        assert mas.improvement_profile_for_text(text) == expected

    def test_migrate_improvement_text_adds_profile_when_missing(self):
        text = (
            "# Improvement: TASK-X\n"
            "## Metadata\n"
            "- Task ID: TASK-X\n"
            "- Source Task: TASK-X\n"
            "- Trigger Type: failure\n"
            "## 1. What Happened\n"
            "event\n"
        )
        result = mas.migrate_improvement_text(text)
        assert "Improvement Profile:" in result

    def test_migrate_verify_text_reloads_from_git_head(self, monkeypatch, tmp_path):
        (tmp_path / "artifacts" / "verify").mkdir(parents=True)
        head_text = (
            "# Verification: TASK-100\n"
            "## Metadata\n"
            "- Task ID: TASK-100\n"
            "- Artifact Type: verify\n"
            "- Owner: Claude\n"
            "- Status: pass\n"
            "- Last Updated: 2026-01-15T10:00:00+08:00\n"
            "## Acceptance Criteria Checklist\n"
            "- **criterion**: c\n"
            "- **method**: m\n"
            "- **evidence**: e\n"
            "- **result**: verified\n"
            "## Evidence\n"
            "- `artifacts/tasks/TASK-100.task.md`\n"
            "## Build Guarantee\n"
            "None (no .csproj modified)\n"
            "## Pass Fail Result\n"
            "pass\n"
        )

        class _FakeResult:
            def __init__(self, stdout):
                self.stdout = stdout

        monkeypatch.setattr(mas.subprocess, "run", lambda *a, **kw: _FakeResult(head_text))
        current = (
            "# Verification: TASK-100\n"
            "## Metadata\n"
            "- Task ID: TASK-100\n"
            "- Artifact Type: verify\n"
            "- Owner: Claude\n"
            "- Status: pass\n"
            "- Last Updated: 2026-01-15T10:00:00+08:00\n"
            "## Acceptance Criteria Checklist\n"
            "Migrated from legacy verify artifact.\n"
            "## Build Guarantee\n"
            "None (no .csproj modified)\n"
            "## Pass Fail Result\n"
            "pass\n"
        )
        migrated, assessment = mas.migrate_verify_text(
            tmp_path,
            "TASK-100",
            state="done",
            assurance_level="poc",
            project_adapter="generic",
            text=current,
            input_mode=mas.ROOT_TRACKED_MODE,
        )
        assert "- **criterion**: c" in migrated

    def test_migrate_verify_fills_deferred_items_from_debts(self, tmp_path):
        verify_text = (
            "# Verification: TASK-200\n"
            "## Metadata\n"
            "- Task ID: TASK-200\n"
            "- Artifact Type: verify\n"
            "- Owner: Claude\n"
            "- Status: pass\n"
            "- Last Updated: 2026-01-15T10:00:00+08:00\n"
            "## Verification Summary\n"
            "Summary\n"
            "## Acceptance Criteria Checklist\n"
            "- **criterion**: C\n"
            "- **method**: M\n"
            "- **evidence**: E\n"
            "- **result**: deferred\n"
            "- **reason_code**: MANUAL_CHECK_DEFERRED\n"
            "## Evidence\n"
            "None\n"
            "## Build Guarantee\n"
            "None (no .csproj modified)\n"
            "## Pass Fail Result\n"
            "pass\n"
        )
        migrated, _ = mas.migrate_verify_text(
            tmp_path,
            "TASK-200",
            state="done",
            assurance_level="poc",
            project_adapter="generic",
            text=verify_text,
            input_mode=mas.ROOT_TRACKED_MODE,
        )
        deferred_block = gsv.extract_section(migrated, "Deferred Items")
        assert "deferred: C" in deferred_block

    def test_migrate_status_payload_preserves_blocker_reason_and_waiver(self, tmp_path):
        (tmp_path / "artifacts" / "tasks").mkdir(parents=True)
        (tmp_path / "artifacts" / "status").mkdir(parents=True)
        status = {
            "state": "blocked",
            "current_owner": "Claude",
            "last_updated": "2026-01-15T10:00:00+08:00",
            "blockers": ["external dependency"],
            "decision_waivers": [
                {
                    "gate": "Gate_B",
                    "reason": "waiting",
                    "approver": "human",
                    "expires": "2026-12-31T23:59:59+08:00",
                }
            ],
        }
        migrated = mas.migrate_status_payload(tmp_path, "TASK-300", status)
        assert migrated["blocked_reason"] == "external dependency"
        assert "decision_waivers" in migrated

    def test_migrate_repository_covers_improvement_directory(self, tmp_path):
        for sub in ("tasks", "decisions", "improvement", "verify", "status"):
            (tmp_path / "artifacts" / sub).mkdir(parents=True)
        (tmp_path / "artifacts" / "improvement" / "TASK-400.improvement.md").write_text(
            (
                "# Improvement: TASK-400\n"
                "## Metadata\n"
                "- Task ID: TASK-400\n"
                "- Source Task: TASK-400\n"
                "- Trigger Type: failure\n"
                "- Last Updated: 2026-01-15T10:00:00+08:00\n"
                "## 1. What Happened\n"
                "none\n"
            ),
            encoding="utf-8",
        )
        report = mas.migrate_repository(tmp_path, apply=True)
        imp_rows = [c for c in report.changes if c.relative_path.endswith("TASK-400.improvement.md")]
        assert imp_rows, "expected improvement row in migration report"
        imp_text = (tmp_path / "artifacts" / "improvement" / "TASK-400.improvement.md").read_text(encoding="utf-8")
        assert "Improvement Profile:" in imp_text

    def test_print_report_emits_notes(self, capsys):
        report = mas.MigrationReport(apply=False)
        change = mas.MigrationChange(
            relative_path="artifacts/verify/TASK-X.verify.md",
            changed=True,
            detail="demo",
            notes=["strategy=manual", "confidence=low"],
        )
        report.changes.append(change)
        mas.print_report(report)
        captured = capsys.readouterr().out
        assert "[CHANGED] artifacts/verify/TASK-X.verify.md" in captured
        assert "[NOTE] strategy=manual" in captured

class TestLegacyVerifyCorpusCoverageCatchup:
    def test_load_corpus_case_missing_raises(self):
        with pytest.raises(KeyError):
            lvc.load_corpus_case("does-not-exist-fixture")

