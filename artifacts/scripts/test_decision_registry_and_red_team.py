"""Split unit tests for decision registry and red team scorecard per TASK-1054."""
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


class TestValidateRows:
    def test_zero_delta_ok(self):
        rows = [vsd.Row(case="RT-001", reviewer_delta=0, notes="")]
        assert vsd.validate_rows(rows) == []

    def test_nonzero_delta_with_notes_ok(self):
        rows = [vsd.Row(case="RT-001", reviewer_delta=1, notes="justified change")]
        assert vsd.validate_rows(rows) == []

    def test_nonzero_delta_without_notes_fail(self):
        rows = [vsd.Row(case="RT-001", reviewer_delta=-1, notes="None")]
        failures = vsd.validate_rows(rows)
        assert len(failures) == 1
        assert "RT-001" in failures[0]

    def test_empty_notes_fail(self):
        rows = [vsd.Row(case="RT-002", reviewer_delta=1, notes="")]
        failures = vsd.validate_rows(rows)
        assert len(failures) == 1


# ─────────────────────────────────────────────
# workflow_constants
# ─────────────────────────────────────────────

class TestValidateRowsEdges:
    def test_multiple_failures(self):
        rows = [
            vsd.Row(case="RT-001", reviewer_delta=1, notes=""),
            vsd.Row(case="RT-002", reviewer_delta=-1, notes="None"),
            vsd.Row(case="RT-003", reviewer_delta=0, notes=""),
        ]
        failures = vsd.validate_rows(rows)
        assert len(failures) == 2
        cases = " ".join(failures)
        assert "RT-001" in cases
        assert "RT-002" in cases

    def test_all_passing(self):
        rows = [
            vsd.Row(case="RT-001", reviewer_delta=0, notes=""),
            vsd.Row(case="RT-002", reviewer_delta=1, notes="Good reason"),
            vsd.Row(case="RT-003", reviewer_delta=-1, notes="Noted reason"),
        ]
        assert vsd.validate_rows(rows) == []

    def test_empty_rows(self):
        assert vsd.validate_rows([]) == []


# ─────────────────────────────────────────────
# build_decision_registry: additional edges
# ─────────────────────────────────────────────

class TestBdrBuildEntry:
    def _make_decision(self, tmp_path, task_id="TASK-001"):
        root = tmp_path
        (root / "artifacts" / "decisions").mkdir(parents=True)
        content = textwrap.dedent(f"""\
            # Decision Log: {task_id}
            ## Metadata
            - Artifact Type: decision
            - Task ID: {task_id}
            - Owner: Claude
            - Status: done
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Issue
            Need to choose framework
            ## Chosen Option
            React
            ## Reasoning
            Community support
        """)
        p = root / "artifacts" / "decisions" / f"{task_id}.decision.md"
        p.write_text(content, encoding="utf-8")
        return root, p

    def test_valid_decision(self, tmp_path):
        root, p = self._make_decision(tmp_path)
        entry = bdr.build_entry(root, p)
        assert entry.task_id == "TASK-001"
        assert "React" in entry.summary

    def test_decision_type_general(self, tmp_path):
        root, p = self._make_decision(tmp_path)
        entry = bdr.build_entry(root, p)
        assert entry.decision_type == "general_decision"

class TestBdrBuildRegistry:
    def test_empty_dir(self, tmp_path):
        d = tmp_path / "artifacts" / "decisions"
        d.mkdir(parents=True)
        registry = bdr.build_registry(tmp_path)
        assert isinstance(registry, dict)
        assert registry["total"] == 0

    def test_with_entries(self, tmp_path):
        d = tmp_path / "artifacts" / "decisions"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Decision Log: TASK-001
            ## Metadata
            - Artifact Type: decision
            - Task ID: TASK-001
            - Owner: Claude
            - Status: done
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Issue
            Test
            ## Chosen Option
            Option A
            ## Reasoning
            Because
        """)
        (d / "TASK-001.decision.md").write_text(content, encoding="utf-8")
        registry = bdr.build_registry(tmp_path)
        assert registry["total"] == 1

    def test_extract_metadata_date(self):
        text = "- Last Updated: 2026-01-15T10:00:00+08:00\n"
        assert bdr.extract_metadata_date(text) == "2026-01-15T10:00:00+08:00"

    def test_extract_decision_type_guard_exception(self):
        sections = {"guard exception": "some content"}
        assert bdr.extract_decision_type("", sections) == "guard_exception"

    def test_extract_summary_from_issue(self):
        sections = {"issue": "Need to decide something important"}
        assert "Need to decide" in bdr.extract_summary(sections)

    def test_fallback_same_task_ref_missing(self, tmp_path):
        result = bdr.fallback_same_task_ref(tmp_path, "plans", "TASK-001")
        assert result == []

    def test_fallback_same_task_ref_exists(self, tmp_path):
        p = tmp_path / "artifacts" / "plans" / "TASK-001.plan.md"
        p.parent.mkdir(parents=True)
        p.write_text("plan", encoding="utf-8")
        result = bdr.fallback_same_task_ref(tmp_path, "plans", "TASK-001")
        assert len(result) == 1
        assert "TASK-001.plan.md" in result[0]


# ─────────────────────────────────────────────
# validate_scorecard_deltas: helpers
# ─────────────────────────────────────────────

class TestVsdParseRows:
    def test_valid_rows(self):
        markdown = textwrap.dedent("""\
            | Case | Phase | Expected | Outcome | Exit | Baseline | Delta | Final | Evidence | Notes |
            |------|-------|----------|---------|------|----------|-------|-------|----------|-------|
            | TC-01 | static | pass | pass | 0 | 8 | 0 | 8 | `log.txt` | |
            | TC-02 | static | pass | fail | 1 | 7 | -1 | 6 | `log2.txt` | Regression found |
        """)
        rows = vsd.parse_rows(markdown)
        assert len(rows) == 2
        assert rows[0].case == "TC-01"
        assert rows[1].reviewer_delta == -1

    def test_no_table(self):
        rows = vsd.parse_rows("# Scorecard\nNo table here\n")
        assert rows == []

    def test_validate_zero_delta_ok(self):
        rows = [vsd.Row(case="TC-01", reviewer_delta=0, notes="")]
        failures = vsd.validate_rows(rows)
        assert failures == []

    def test_validate_nonzero_delta_without_notes(self):
        rows = [vsd.Row(case="TC-01", reviewer_delta=-1, notes="")]
        failures = vsd.validate_rows(rows)
        assert len(failures) == 1
        assert "TC-01" in failures[0]

    def test_validate_nonzero_delta_with_notes(self):
        rows = [vsd.Row(case="TC-01", reviewer_delta=-1, notes="Regression found")]
        failures = vsd.validate_rows(rows)
        assert failures == []

    def test_validate_placeholder_notes(self):
        for placeholder in ("none", "TBD", "待補"):
            rows = [vsd.Row(case="TC-01", reviewer_delta=1, notes=placeholder)]
            failures = vsd.validate_rows(rows)
            assert len(failures) == 1, f"Expected failure for placeholder '{placeholder}'"


# ─────────────────────────────────────────────
# detect_plan_code_scope_drift: additional
# ─────────────────────────────────────────────

class TestArsParseReport:
    def test_valid_report(self):
        markdown = textwrap.dedent("""\
            # Report
            | Case | Phase | Expected | Outcome | Exit | Evidence | Notes |
            | TC-01 | static | pass | pass | 0 | `log.txt` | |
            | TC-02 | live | pass | fail | 1 | `log2.txt` | Bug |
        """)
        rows = ars.parse_report(markdown)
        assert len(rows) == 2
        assert rows[0].case == "TC-01"
        assert rows[0].case_passed
        assert not rows[1].case_passed

    def test_empty_report(self):
        rows = ars.parse_report("# No table here\n")
        assert rows == []

class TestArsBuildScorecard:
    def test_generates_valid_scorecard(self, tmp_path):
        rows = [
            ars.CaseRow("TC-01", "static", "pass", "pass", "0", "log.txt", ""),
            ars.CaseRow("TC-02", "live", "pass", "fail", "1", "log.txt", "Bug"),
        ]
        report_path = tmp_path / "report.md"
        scorecard = ars.build_scorecard(rows, report_path)
        assert "TC-01" in scorecard
        assert "TC-02" in scorecard
        assert "Cases: 2" in scorecard
        assert "Case Passed: 1" in scorecard
        assert "Case Failed: 1" in scorecard

    def test_auto_score_pass(self):
        row = ars.CaseRow("TC-01", "static", "pass", "pass", "0", "log.txt", "")
        assert ars.auto_score(row) == 2

    def test_auto_score_fail(self):
        row = ars.CaseRow("TC-01", "static", "pass", "fail", "1", "log.txt", "")
        assert ars.auto_score(row) == 0


# ─────────────────────────────────────────────
# validate_context_stack extras
# ─────────────────────────────────────────────

class TestBdrExtractDecisionType:
    def test_from_section(self):
        text = "## Metadata\nstuff\n## Decision Type\nworkflow_change\n## Issue\nstuff\n"
        sections = bdr.parse_sections(text)
        assert bdr.extract_decision_type(text, sections) == "workflow_change"

    def test_from_type_line(self):
        text = "## Metadata\nstuff\n## Issue\nstuff\n- Type: design_choice\n"
        sections = bdr.parse_sections(text)
        assert bdr.extract_decision_type(text, sections) == "design_choice"

    def test_guard_exception_fallback(self):
        text = "## Metadata\nstuff\n## Guard Exception\nAllow drift\n"
        sections = bdr.parse_sections(text)
        assert bdr.extract_decision_type(text, sections) == "guard_exception"

    def test_general_decision_fallback(self):
        text = "## Metadata\nstuff\n"
        sections = bdr.parse_sections(text)
        assert bdr.extract_decision_type(text, sections) == "general_decision"

class TestBdrExtractSummary:
    def test_from_summary_section(self):
        text = "## Summary\nThis is the summary.\n\nMore detail.\n"
        sections = bdr.parse_sections(text)
        assert bdr.extract_summary(sections) == "This is the summary."

    def test_from_chosen_option(self):
        text = "## Chosen Option\nOption A selected.\n"
        sections = bdr.parse_sections(text)
        assert bdr.extract_summary(sections) == "Option A selected."

    def test_from_issue(self):
        text = "## Issue\nSomething broke.\n"
        sections = bdr.parse_sections(text)
        assert bdr.extract_summary(sections) == "Something broke."

    def test_empty_sections(self):
        assert bdr.extract_summary({}) == ""

    def test_truncation(self):
        text = "## Summary\n" + "x" * 300 + "\n"
        sections = bdr.parse_sections(text)
        assert len(bdr.extract_summary(sections)) <= 200

class TestBdrExtractFieldTokens:
    def test_single_line_affects(self):
        text = "- Affects: TASK-001, TASK-002\n"
        result = bdr.extract_field_tokens(text, "affects")
        assert "TASK-001" in result
        assert "TASK-002" in result

    def test_multiline_affects(self):
        text = "- Affects: TASK-001\n  TASK-002\n  TASK-003\n\nSomething else\n"
        result = bdr.extract_field_tokens(text, "affects")
        assert "TASK-001" in result
        assert "TASK-002" in result

    def test_stops_at_section(self):
        text = "- Affects: TASK-001\n## Next Section\nmore stuff\n"
        result = bdr.extract_field_tokens(text, "affects")
        assert result == ["TASK-001"]

    def test_stops_at_new_field(self):
        text = "- Affects: TASK-001\n- Related Research: something\n"
        result = bdr.extract_field_tokens(text, "affects")
        assert result == ["TASK-001"]

    def test_related_research(self):
        text = "- Related Research: TASK-050\n"
        result = bdr.extract_field_tokens(text, "related_research")
        assert "TASK-050" in result

class TestBdrNormalizeRef:
    def test_artifacts_path(self):
        assert bdr.normalize_ref("artifacts/plans/TASK-001.plan.md", "plans") == "artifacts/plans/TASK-001.plan.md"

    def test_dir_relative_path(self):
        assert bdr.normalize_ref("plans/TASK-001.plan.md", "plans") == "artifacts/plans/TASK-001.plan.md"

    def test_task_id_only_plans(self):
        assert bdr.normalize_ref("TASK-001", "plans") == "artifacts/plans/TASK-001.plan.md"

    def test_task_id_only_research(self):
        assert bdr.normalize_ref("TASK-001", "research") == "artifacts/research/TASK-001.research.md"

    def test_basename_md(self):
        assert bdr.normalize_ref("TASK-001.plan.md", "plans") == "artifacts/plans/TASK-001.plan.md"

    def test_empty_string(self):
        assert bdr.normalize_ref("", "plans") == ""

    def test_passthrough(self):
        assert bdr.normalize_ref("some/random/path.txt", "plans") == "some/random/path.txt"

    def test_backslash_normalized(self):
        result = bdr.normalize_ref("artifacts\\plans\\TASK-001.plan.md", "plans")
        assert result == "artifacts/plans/TASK-001.plan.md"

class TestBdrBuildEntry_v2:
    def test_complete_decision(self, tmp_path):
        root = tmp_path
        d = root / "artifacts" / "decisions"
        d.mkdir(parents=True)
        (root / "artifacts" / "plans").mkdir(parents=True)
        (root / "artifacts" / "plans" / "TASK-001.plan.md").write_text("plan", encoding="utf-8")
        content = textwrap.dedent("""\
            # Decision Log: TASK-001
            ## Metadata
            - Artifact Type: decision
            - Task ID: TASK-001
            - Owner: Claude
            - Status: done
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Issue
            Something needed deciding
            ## Chosen Option
            We chose option A
            ## Reasoning
            It was the best
            - Affects: TASK-001
            - Related Research: TASK-001
        """)
        (d / "TASK-001.decision.md").write_text(content, encoding="utf-8")
        entry = bdr.build_entry(root, d / "TASK-001.decision.md")
        assert entry.task_id == "TASK-001"
        assert entry.summary
        assert entry.date == "2026-01-15T10:00:00+08:00"
        assert entry.parse_status == "complete"

    def test_partial_decision(self, tmp_path):
        root = tmp_path
        d = root / "artifacts" / "decisions"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Decision Log: TASK-002
            ## Metadata
            - Artifact Type: decision
            - Task ID: TASK-002
        """)
        (d / "TASK-002.decision.md").write_text(content, encoding="utf-8")
        entry = bdr.build_entry(root, d / "TASK-002.decision.md")
        assert entry.parse_status == "partial"

class TestBdrBuildRegistry_v2:
    def test_empty_dir(self, tmp_path):
        d = tmp_path / "artifacts" / "decisions"
        d.mkdir(parents=True)
        result = bdr.build_registry(tmp_path)
        assert result["total"] == 0
        assert result["entries"] == []

    def test_with_entries(self, tmp_path):
        d = tmp_path / "artifacts" / "decisions"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Decision Log: TASK-001
            ## Metadata
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Issue
            Something
        """)
        (d / "TASK-001.decision.md").write_text(content, encoding="utf-8")
        result = bdr.build_registry(tmp_path)
        assert result["total"] == 1

class TestBdrFallbackSameTaskRef:
    def test_exists(self, tmp_path):
        (tmp_path / "artifacts" / "plans").mkdir(parents=True)
        (tmp_path / "artifacts" / "plans" / "TASK-001.plan.md").write_text("x", encoding="utf-8")
        refs = bdr.fallback_same_task_ref(tmp_path, "plans", "TASK-001")
        assert refs == ["artifacts/plans/TASK-001.plan.md"]

    def test_not_exists(self, tmp_path):
        (tmp_path / "artifacts" / "plans").mkdir(parents=True)
        refs = bdr.fallback_same_task_ref(tmp_path, "plans", "TASK-999")
        assert refs == []

class TestBdrHelpers:
    def test_normalize_newlines(self):
        assert bdr.normalize_newlines("a\r\nb\r\n") == "a\nb\n"

    def test_first_paragraph_empty(self):
        assert bdr.first_paragraph("") == ""
        assert bdr.first_paragraph(None) == ""

    def test_first_paragraph_multi(self):
        assert bdr.first_paragraph("first paragraph\n\nsecond paragraph") == "first paragraph"

    def test_collapse_whitespace(self):
        assert bdr.collapse_whitespace("  a   b  c  ") == "a b c"

    def test_extract_task_id_valid(self):
        assert bdr.extract_task_id(Path("TASK-001.decision.md")) == "TASK-001"

    def test_extract_task_id_invalid(self):
        with pytest.raises(ValueError, match="Unsupported"):
            bdr.extract_task_id(Path("invalid.md"))

    def test_extract_metadata_date(self):
        assert bdr.extract_metadata_date("- Last Updated: 2026-01-15T10:00:00+08:00\n") == "2026-01-15T10:00:00+08:00"

    def test_extract_metadata_date_missing(self):
        assert bdr.extract_metadata_date("no date here") == ""

    def test_clean_ref_token_strips(self):
        assert bdr.clean_ref_token("  `TASK-001`  ") == "TASK-001"
        assert bdr.clean_ref_token("- `TASK-002`") == "TASK-002"
        assert bdr.clean_ref_token("* TASK-003") == "TASK-003"

    def test_split_ref_tokens(self):
        result = bdr.split_ref_tokens(["TASK-001, TASK-002", "TASK-003"])
        assert result == ["TASK-001", "TASK-002", "TASK-003"]

    def test_dedupe_preserving_order(self):
        assert bdr.dedupe_preserving_order(["a", "b", "a", "c"]) == ["a", "b", "c"]

    def test_normalize_refs(self):
        result = bdr.normalize_refs(["TASK-001", "TASK-002"], "plans")
        assert "artifacts/plans/TASK-001.plan.md" in result
        assert "artifacts/plans/TASK-002.plan.md" in result


# ─────────────────────────────────────────────
# validate_context_stack — unit tests
# ─────────────────────────────────────────────

class TestParseArgsCoverage:
    """Cover parse_args return lines for ars, bdr, prv, vsd."""

    def test_ars_parse_args(self, tmp_path):
        report = tmp_path / "report.md"
        report.write_text("# Report\n", encoding="utf-8")
        args = ars.parse_args(["--report", str(report)])
        assert args.report == str(report)

    def test_bdr_parse_args(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["bdr", "--root", "/tmp"])
        args = bdr.parse_args()
        assert args.root == "/tmp"

    def test_prv_parse_args(self, tmp_path):
        cases = tmp_path / "cases.json"
        cases.write_text("[]", encoding="utf-8")
        args = prv.parse_args(["--root", str(tmp_path), "--cases", str(cases)])
        assert args.root == str(tmp_path)

    def test_vsd_parse_args(self, tmp_path):
        sc = tmp_path / "scorecard.md"
        sc.write_text("# Scorecard\n", encoding="utf-8")
        args = vsd.parse_args(["--scorecard", str(sc)])
        assert args.scorecard == str(sc)



# ── discover_templates tests ──


import discover_templates as dt

class TestBuildDecisionRegistryCoverageCatchup:
    def test_normalize_linked_artifacts_strips_prefix_and_dedupes(self):
        tokens = ["./foo/bar.md", "foo/bar.md", "C:\\path\\to\\file"]
        result = bdr.normalize_linked_artifacts(tokens)
        assert "foo/bar.md" in result
        assert "C:/path/to/file" in result
        assert len(result) == len(set(result))

    def test_normalize_linked_artifacts_skips_empty(self):
        assert bdr.normalize_linked_artifacts(["", "  "]) == []

class TestCheckTaoTrace:
    def test_no_csv_file(self, tmp_path):
        artifacts_root = tmp_path / "artifacts"
        artifacts_root.mkdir()
        warnings = gsv.check_tao_trace(artifacts_root, "TASK-900")
        assert len(warnings) == 1
        assert "risk_classification.csv not found" in warnings[0]

    def test_task_not_in_csv(self, tmp_path):
        artifacts_root = tmp_path / "artifacts"
        (artifacts_root / "registry").mkdir(parents=True)
        csv_path = artifacts_root / "registry" / "risk_classification.csv"
        csv_path.write_text("task_id,risk_level\nTASK-800,high-risk\n", encoding="utf-8")
        warnings = gsv.check_tao_trace(artifacts_root, "TASK-999")
        assert len(warnings) == 1
        assert "not found in risk_classification.csv" in warnings[0]

    def test_low_risk_skip(self, tmp_path):
        artifacts_root = tmp_path / "artifacts"
        (artifacts_root / "registry").mkdir(parents=True)
        csv_path = artifacts_root / "registry" / "risk_classification.csv"
        csv_path.write_text("task_id,risk_level\nTASK-999,low-risk\n", encoding="utf-8")
        warnings = gsv.check_tao_trace(artifacts_root, "TASK-999")
        assert warnings == []

    def test_high_risk_with_tao(self, tmp_path):
        artifacts_root = tmp_path / "artifacts"
        (artifacts_root / "registry").mkdir(parents=True)
        (artifacts_root / "code").mkdir(parents=True)
        (artifacts_root / "verify").mkdir(parents=True)
        csv_path = artifacts_root / "registry" / "risk_classification.csv"
        csv_path.write_text("task_id,risk_level\nTASK-900,high-risk\n", encoding="utf-8")
        (artifacts_root / "code" / "TASK-900.code.md").write_text(
            "# Code\n## TAO Trace\nstep\n", encoding="utf-8"
        )
        (artifacts_root / "verify" / "TASK-900.verify.md").write_text(
            "# Verify\n## TAO Trace\nstep\n", encoding="utf-8"
        )
        warnings = gsv.check_tao_trace(artifacts_root, "TASK-900")
        assert warnings == []

    def test_high_risk_missing_tao(self, tmp_path):
        artifacts_root = tmp_path / "artifacts"
        (artifacts_root / "registry").mkdir(parents=True)
        (artifacts_root / "code").mkdir(parents=True)
        (artifacts_root / "verify").mkdir(parents=True)
        csv_path = artifacts_root / "registry" / "risk_classification.csv"
        csv_path.write_text("task_id,risk_level\nTASK-900,high-risk\n", encoding="utf-8")
        (artifacts_root / "code" / "TASK-900.code.md").write_text(
            "# Code\nno tao here\n", encoding="utf-8"
        )
        (artifacts_root / "verify" / "TASK-900.verify.md").write_text(
            "# Verify\nno tao here\n", encoding="utf-8"
        )
        warnings = gsv.check_tao_trace(artifacts_root, "TASK-900")
        assert len(warnings) == 2
        assert any("code artifact" in w for w in warnings)
        assert any("verify artifact" in w for w in warnings)


# ─────────────────────────────────────────────
# classify_existing_tasks
# ─────────────────────────────────────────────

