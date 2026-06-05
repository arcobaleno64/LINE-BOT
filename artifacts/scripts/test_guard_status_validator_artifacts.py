"""Split unit tests for guard_status_validator artifact validators per TASK-1054."""
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


class TestValidateResearchCitations:
    def test_missing_sources(self, tmp_path):
        p = tmp_path / "research.md"
        p.write_text("# Research\n## Other\nContent", encoding="utf-8")
        findings = gsv.validate_research_citations("TASK-001", p)
        assert any(f.severity == "CRITICAL" for f in findings)

    def test_empty_sources(self, tmp_path):
        p = tmp_path / "research.md"
        p.write_text("# Research\n## Sources\nNone", encoding="utf-8")
        findings = gsv.validate_research_citations("TASK-001", p)
        assert any("at least 2" in f.message for f in findings)

    def test_valid_sources(self, tmp_path):
        p = tmp_path / "research.md"
        sources = (
            "## Sources\n"
            '[1] Author A. "Title A." https://example.com/a (2025-01-15 retrieved)\n'
            '[2] Author B. "Title B." https://example.com/b (2025-01-16 retrieved)\n'
        )
        p.write_text(f"# Research\n{sources}", encoding="utf-8")
        findings = gsv.validate_research_citations("TASK-001", p)
        assert findings == []

    def test_single_source_warning(self, tmp_path):
        p = tmp_path / "research.md"
        sources = (
            "## Sources\n"
            '[1] Author. "Title." https://example.com (2025-01-15 retrieved)\n'
        )
        p.write_text(f"# Research\n{sources}", encoding="utf-8")
        findings = gsv.validate_research_citations("TASK-001", p)
        assert any(f.severity == "MAJOR" and "at least 2" in f.message for f in findings)


# ─────────────────────────────────────────────
# validate_status_schema
# ─────────────────────────────────────────────

class TestValidateStatusSchema:
    def _modern_status(self, task_id="TASK-001", state="drafted"):
        return {
            "task_id": task_id,
            "state": state,
            "current_owner": "Claude Code",
            "next_agent": "Claude Code",
            "required_artifacts": ["task", "status"],
            "available_artifacts": ["task", "status"],
            "missing_artifacts": [],
            "assurance_level": "poc",
            "project_adapter": "generic",
            "verification_readiness": "poc",
            "open_verification_debts": [],
            "blocked_reason": "",
            "last_updated": "2026-01-15T10:00:00+08:00",
        }

    def test_valid_modern(self):
        result = gsv.validate_status_schema(self._modern_status(), "TASK-001")
        assert result.ok

    def test_task_id_mismatch(self):
        result = gsv.validate_status_schema(self._modern_status("TASK-002"), "TASK-001")
        assert not result.ok
        assert any("mismatch" in e for e in result.errors)

    def test_invalid_state(self):
        result = gsv.validate_status_schema(self._modern_status(state="invalid"), "TASK-001")
        assert not result.ok

    def test_missing_keys(self):
        status = {"task_id": "TASK-001", "state": "drafted", "last_updated": "2026-01-15T10:00:00+08:00"}
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("missing required keys" in e for e in result.errors)

    def test_blocked_requires_reason(self):
        status = self._modern_status(state="blocked")
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("blocked_reason" in e for e in result.errors)

    def test_blocked_with_reason(self):
        status = self._modern_status(state="blocked")
        status["blocked_reason"] = "Waiting on upstream"
        result = gsv.validate_status_schema(status, "TASK-001")
        assert result.ok

    def test_unknown_artifact_in_list(self):
        status = self._modern_status()
        status["required_artifacts"] = ["task", "unknown_type"]
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("unknown artifacts" in e for e in result.errors)

    def test_legacy_schema_valid(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "drafted",
            "owner": "Claude",
            "last_updated": "2026-01-15T10:00:00+08:00",
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert result.ok

    def test_legacy_blocked_without_blockers(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "blocked",
            "owner": "Claude",
            "last_updated": "2026-01-15T10:00:00+08:00",
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("blockers" in e for e in result.errors)

    def test_invalid_verification_readiness(self):
        status = self._modern_status()
        status["verification_readiness"] = "bad-state"
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("verification_readiness" in e for e in result.errors)

    def test_production_ready_with_open_debts_warns(self):
        status = self._modern_status(state="done")
        status["assurance_level"] = "production"
        status["project_adapter"] = "generic"
        status["open_verification_debts"] = ["TASK-001#AC-2"]
        status["verification_readiness"] = "production-ready"
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("verification_readiness mismatch" in w for w in result.warnings)


# ─────────────────────────────────────────────
# validate_premortem
# ─────────────────────────────────────────────

class TestValidatePremortem:
    def _make_plan(self, tmp_path, risks_section):
        p = tmp_path / "plan.md"
        p.write_text(
            f"# Plan: TASK-001\n## Scope\nSomething\n## Risks\n{risks_section}\n## Files Likely Affected\n- `a.py`\n",
            encoding="utf-8",
        )
        return p

    def _make_task(self, tmp_path, title="Implement Feature"):
        p = tmp_path / "task.md"
        p.write_text(f"# Task: {title}\n## Metadata\n", encoding="utf-8")
        return p

    def test_missing_risks_section(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n## Scope\nSomething\n", encoding="utf-8")
        result = gsv.validate_premortem(plan, None)
        assert not result.ok
        assert any("## Risks section not found" in e for e in result.errors)

    def test_empty_risks(self, tmp_path):
        plan = self._make_plan(tmp_path, "none")
        result = gsv.validate_premortem(plan, None)
        assert not result.ok

    def test_valid_premortem(self, tmp_path):
        risks = textwrap.dedent("""\
            R1: Connection pool exhaustion
            - Risk: High traffic causes pool depletion
            - Trigger: >1000 concurrent connections
            - Detection: Connection timeout alerts
            - Mitigation: Circuit breaker pattern
            - Severity: blocking

            R2: Schema migration failure
            - Risk: Migration script fails
            - Trigger: Database version mismatch
            - Detection: CI migration test
            - Mitigation: Rollback script
            - Severity: non-blocking

            R3: API backward incompatibility
            - Risk: Breaking changes in response format
            - Trigger: Client parsing failure
            - Detection: Contract tests
            - Mitigation: API versioning
            - Severity: non-blocking
        """)
        plan = self._make_plan(tmp_path, risks)
        task = self._make_task(tmp_path)
        result = gsv.validate_premortem(plan, task)
        assert result.ok, f"Unexpected errors: {result.errors}"

    def test_missing_required_field(self, tmp_path):
        risks = "R1: Issue\n- Risk: Something\n- Severity: blocking\n"
        plan = self._make_plan(tmp_path, risks)
        result = gsv.validate_premortem(plan, None)
        assert not result.ok
        assert any("Trigger:" in e for e in result.errors)

    def test_invalid_severity(self, tmp_path):
        risks = textwrap.dedent("""\
            R1: Issue
            - Risk: Something
            - Trigger: Event
            - Detection: Monitor
            - Mitigation: Fix
            - Severity: critical
        """)
        plan = self._make_plan(tmp_path, risks)
        result = gsv.validate_premortem(plan, None)
        assert not result.ok
        assert any("blocking" in e and "non-blocking" in e for e in result.errors)


# ═════════════════════════════════════════════
# FIXTURE-BASED TESTS FOR guard_contract_validator
# ═════════════════════════════════════════════


# ─────────────────────────────────────────────
# normalize_text
# ─────────────────────────────────────────────

class TestValidateStatusSchemaDecisionWaivers:
    def _modern_status(self, **overrides):
        base = {
            "task_id": "TASK-001",
            "state": "drafted",
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
            "last_updated": "2026-01-15T10:00:00+08:00",
        }
        base.update(overrides)
        return base

    def test_valid_waiver(self):
        status = self._modern_status(decision_waivers=[{
            "gate": "Gate_A",
            "reason": "Research not needed",
            "approver": "User",
            "expires": "2099-12-31T23:59:59+08:00",
        }])
        result = gsv.validate_status_schema(status, "TASK-001")
        assert result.ok

    def test_waiver_not_list(self):
        status = self._modern_status(decision_waivers="invalid")
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("decision_waivers" in e and "list" in e for e in result.errors)

    def test_waiver_entry_not_dict(self):
        status = self._modern_status(decision_waivers=["bad"])
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("must be an object" in e for e in result.errors)

    def test_waiver_missing_fields(self):
        status = self._modern_status(decision_waivers=[{"gate": "Gate_A"}])
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("missing required fields" in e for e in result.errors)

    def test_waiver_invalid_gate(self):
        status = self._modern_status(decision_waivers=[{
            "gate": "Gate_Z",
            "reason": "test",
            "approver": "User",
            "expires": "2099-12-31T23:59:59+08:00",
        }])
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("gate must be one of" in e for e in result.errors)

    def test_waiver_expired(self):
        status = self._modern_status(decision_waivers=[{
            "gate": "Gate_A",
            "reason": "test",
            "approver": "User",
            "expires": "2020-01-01T00:00:00+08:00",
        }])
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("expired" in e for e in result.errors)

class TestValidateStatusSchemaAutoUpgradeLog:
    def _modern_status(self, **overrides):
        base = {
            "task_id": "TASK-001",
            "state": "drafted",
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
            "last_updated": "2026-01-15T10:00:00+08:00",
        }
        base.update(overrides)
        return base

    def test_valid_auto_upgrade_log(self):
        status = self._modern_status(auto_upgrade_log=[{
            "timestamp": "2026-01-15T10:00:00+08:00",
            "reason": "plan has non-empty risks",
            "from_mode": "lightweight",
            "to_mode": "full",
        }])
        result = gsv.validate_status_schema(status, "TASK-001")
        assert result.ok

    def test_auto_upgrade_log_not_list(self):
        status = self._modern_status(auto_upgrade_log="bad")
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("auto_upgrade_log" in e and "list" in e for e in result.errors)

    def test_auto_upgrade_log_entry_not_dict(self):
        status = self._modern_status(auto_upgrade_log=["bad"])
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("must be an object" in e for e in result.errors)

    def test_auto_upgrade_log_missing_field(self):
        status = self._modern_status(auto_upgrade_log=[{"timestamp": "2026-01-15T10:00:00+08:00"}])
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("missing required field" in e for e in result.errors)

    def test_auto_upgrade_log_bad_timestamp(self):
        status = self._modern_status(auto_upgrade_log=[{
            "timestamp": "not-a-timestamp",
            "reason": "test",
            "from_mode": "lightweight",
            "to_mode": "full",
        }])
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("timestamp" in e.lower() for e in result.errors)

    def test_legacy_empty_owner(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "drafted",
            "owner": "",
            "last_updated": "2026-01-15T10:00:00+08:00",
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("owner" in e and "non-empty" in e for e in result.errors)

    def test_legacy_artifacts_not_dict(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "drafted",
            "owner": "Claude",
            "last_updated": "2026-01-15T10:00:00+08:00",
            "artifacts": "bad",
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("artifacts" in e and "object" in e for e in result.errors)

    def test_legacy_non_blocked_with_blockers_warning(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "drafted",
            "owner": "Claude",
            "last_updated": "2026-01-15T10:00:00+08:00",
            "blockers": ["something"],
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert result.ok
        assert any("blockers" in w and "not blocked" in w for w in result.warnings)

    def test_non_blocked_with_reason_warning(self):
        status = self._modern_status(blocked_reason="stale reason")
        result = gsv.validate_status_schema(status, "TASK-001")
        assert result.ok
        assert any("blocked_reason" in w and "not blocked" in w for w in result.warnings)

    def test_required_artifacts_not_list(self):
        status = self._modern_status(required_artifacts="bad")
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.ok
        assert any("required_artifacts" in e and "list" in e for e in result.errors)


# ─────────────────────────────────────────────
# categorize_override_error
# ─────────────────────────────────────────────

class TestValidateCodeMappingToPlan:
    def _make_code(self, tmp_path, mapping_section):
        p = tmp_path / "code.md"
        content = f"# Code Result: TASK-001\n## Metadata\n## Files Changed\n- `a.py`\n## Summary Of Changes\nDone\n## Mapping To Plan\n{mapping_section}\n"
        p.write_text(content, encoding="utf-8")
        return p

    def test_no_section(self, tmp_path):
        p = tmp_path / "code.md"
        p.write_text("# Code\n## Summary\nDone\n", encoding="utf-8")
        result = gsv.validate_code_mapping_to_plan(p.read_text(encoding="utf-8"), p)
        assert result.ok

    def test_no_plan_item_bullets(self, tmp_path):
        p = self._make_code(tmp_path, "- Implemented everything as planned.")
        result = gsv.validate_code_mapping_to_plan(p.read_text(encoding="utf-8"), p)
        assert result.ok

    def test_valid_entries(self, tmp_path):
        mapping = '- plan_item: 1.1, status: done, evidence: "commit abc"\n- plan_item: 1.2, status: partial, evidence: "WIP"\n'
        p = self._make_code(tmp_path, mapping)
        result = gsv.validate_code_mapping_to_plan(p.read_text(encoding="utf-8"), p)
        assert not result.warnings

    def test_invalid_entry_format(self, tmp_path):
        mapping = '- plan_item: 1.1, status: done, evidence: "ok"\n- plan_item: bad format\n'
        p = self._make_code(tmp_path, mapping)
        result = gsv.validate_code_mapping_to_plan(p.read_text(encoding="utf-8"), p)
        assert len(result.warnings) == 1
        assert "Mapping To Plan entry must match" in result.warnings[0]


# ─────────────────────────────────────────────
# validate_verify_checklist_schema
# ─────────────────────────────────────────────

class TestValidateVerifyChecklistSchema:
    def _make_verify(self, tmp_path, checklist_section):
        p = tmp_path / "verify.md"
        content = (
            "# Verification: TASK-001\n"
            "## Verification Summary\nCovered by targeted checklist.\n"
            "## Acceptance Criteria Checklist\n"
            f"{checklist_section}\n"
            "## Overall Maturity\npoc\n"
            "## Deferred Items\nNone\n"
            "## Pass Fail Result\npass\n"
        )
        p.write_text(content, encoding="utf-8")
        return p

    def test_no_section(self, tmp_path):
        p = tmp_path / "verify.md"
        p.write_text("# Verify\n## Pass Fail Result\npass\n", encoding="utf-8")
        result = gsv.validate_verify_checklist_schema(p.read_text(encoding="utf-8"), p)
        assert not result.warnings

    def test_valid_structured_checklist(self, tmp_path):
        section = textwrap.dedent("""\
            - **criterion**: Build passes
            - **method**: CI pipeline
            - **evidence**: Pipeline #42 green
            - **result**: verified
            - **reviewer**: Claude
            - **timestamp**: 2026-01-15T10:00:00+08:00
        """)
        p = self._make_verify(tmp_path, section)
        result = gsv.validate_verify_checklist_schema(p.read_text(encoding="utf-8"), p)
        assert not result.warnings

    def test_missing_fields_warning(self, tmp_path):
        section = textwrap.dedent("""\
            - **criterion**: Build passes
            - **method**: CI
        """)
        p = self._make_verify(tmp_path, section)
        result = gsv.validate_verify_checklist_schema(p.read_text(encoding="utf-8"), p)
        assert len(result.warnings) > 0
        assert any("missing" in w for w in result.warnings)

    def test_invalid_timestamp_warning(self, tmp_path):
        section = textwrap.dedent("""\
            - **criterion**: Build passes
            - **method**: CI
            - **evidence**: ok
            - **result**: verified
            - **reviewer**: Claude
            - **timestamp**: bad-timestamp
        """)
        p = self._make_verify(tmp_path, section)
        result = gsv.validate_verify_checklist_schema(p.read_text(encoding="utf-8"), p)
        assert any("timestamp" in w.lower() for w in result.warnings)

    def test_production_rejects_deferred(self, tmp_path):
        section = textwrap.dedent("""\
            - **criterion**: Runtime behavior confirmed
            - **method**: Manual run
            - **evidence**: Pending device access
            - **result**: deferred
            - **reviewer**: Claude
            - **timestamp**: 2026-01-15T10:00:00+08:00
            - **reason_code**: MANUAL_CHECK_DEFERRED
        """)
        p = tmp_path / "verify.md"
        p.write_text(
            textwrap.dedent(f"""\
                # Verification: TASK-001
                ## Verification Summary
                Runtime verification pending.
                ## Acceptance Criteria Checklist
                {section}
                ## Overall Maturity
                production-blocked
                ## Deferred Items
                Device access pending
                ## Decision Refs
                None
                ## Evidence Refs
                None
                ## Build Guarantee
                build ok
                ## Pass Fail Result
                fail
            """),
            encoding="utf-8",
        )
        result = gsv.validate_verify_checklist_schema(
            p.read_text(encoding="utf-8"),
            p,
            assurance_level="production",
        )
        assert any("not allowed" in e for e in result.errors)

    def test_docs_spec_allows_adapter_reason_code(self, tmp_path):
        section = textwrap.dedent("""\
            - **criterion**: Rendered markdown review
            - **method**: Manual inspection
            - **evidence**: Static diff
            - **result**: deferred
            - **reason_code**: NOT_APPLICABLE_BY_ADAPTER
        """)
        p = self._make_verify(tmp_path, section)
        result = gsv.validate_verify_checklist_schema(
            p.read_text(encoding="utf-8"),
            p,
            assurance_level="poc",
            project_adapter="docs-spec",
        )
        assert not any("reason_code" in e for e in result.errors)

    def test_poc_requires_structured_items_warning(self, tmp_path):
        p = self._make_verify(tmp_path, "- [x] Legacy checkbox item")
        result = gsv.validate_verify_checklist_schema(p.read_text(encoding="utf-8"), p)
        assert any("requires at least one structured checklist item" in w for w in result.warnings)

    def test_pass_cannot_coexist_with_open_debts(self, tmp_path):
        section = textwrap.dedent("""\
            - **criterion**: Runtime behavior confirmed
            - **method**: Manual run
            - **evidence**: Pending environment
            - **result**: deferred
            - **reason_code**: MANUAL_CHECK_DEFERRED
        """)
        p = self._make_verify(tmp_path, section)
        result = gsv.validate_verify_checklist_schema(p.read_text(encoding="utf-8"), p)
        assert any("Pass Fail Result cannot be 'pass'" in e for e in result.errors)

class TestCollectVerifyContract:
    def test_collects_open_verification_debts(self, tmp_path):
        verify = tmp_path / "verify.md"
        verify.write_text(
            textwrap.dedent("""\
                # Verification: TASK-001
                ## Verification Summary
                Summary
                ## Acceptance Criteria Checklist
                - **criterion**: Device run completed
                - **method**: Manual execution
                - **evidence**: Device unavailable
                - **result**: deferred
                - **reason_code**: MANUAL_CHECK_DEFERRED
                ## Overall Maturity
                poc
                ## Deferred Items
                - deferred: Device run completed
                ## Pass Fail Result
                fail
            """),
            encoding="utf-8",
        )
        contract = gsv.collect_verify_contract(verify.read_text(encoding="utf-8"))
        assert contract["open_verification_debts"] == ["deferred: Device run completed"]
        assert contract["computed_readiness"] == "poc"


# ─────────────────────────────────────────────
# validate_improvement_artifact
# ─────────────────────────────────────────────

class TestValidateImprovementArtifact:
    def _make_improvement(self, tmp_path, **overrides):
        fields = {
            "source_task": "TASK-001",
            "trigger_type": "failure",
            "preventive": "Add guard",
            "validation": "Run CI",
            "final_rule": "Always validate",
            "status": "approved",
        }
        fields.update(overrides)
        content = textwrap.dedent(f"""\
            # Process Improvement
            ## Metadata
            - Artifact Type: improvement
            - Source Task: {fields['source_task']}
            - Trigger Type: {fields['trigger_type']}
            - Owner: Claude
            - Status: {fields['status']}
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## 1. What Happened
            Something broke
            ## 2. Why It Was Not Prevented
            No guard existed
            ## 3. Failure Classification
            Process gap
            ## 5. Preventive Action (System Level)
            {fields['preventive']}
            ## 6. Validation
            {fields['validation']}
            ## 8. Final Rule
            {fields['final_rule']}
            ## 9. Status
            {fields['status']}
        """)
        p = tmp_path / "improvement.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_valid(self, tmp_path):
        p = self._make_improvement(tmp_path)
        result = gsv.validate_improvement_artifact(p.read_text(encoding="utf-8"), p, "TASK-001")
        assert result.ok

    def test_missing_source_task(self, tmp_path):
        p = self._make_improvement(tmp_path, source_task="")
        result = gsv.validate_improvement_artifact(p.read_text(encoding="utf-8"), p, "TASK-001")
        assert not result.ok
        assert any("Source Task" in e for e in result.errors)

    def test_wrong_source_task(self, tmp_path):
        p = self._make_improvement(tmp_path, source_task="TASK-999")
        result = gsv.validate_improvement_artifact(p.read_text(encoding="utf-8"), p, "TASK-001")
        assert not result.ok
        assert any("reference" in e.lower() or "TASK-001" in e for e in result.errors)

    def test_invalid_trigger_type(self, tmp_path):
        p = self._make_improvement(tmp_path, trigger_type="unknown")
        result = gsv.validate_improvement_artifact(p.read_text(encoding="utf-8"), p, "TASK-001")
        assert not result.ok
        assert any("Trigger Type" in e for e in result.errors)

    def test_empty_section(self, tmp_path):
        p = self._make_improvement(tmp_path, preventive="none")
        result = gsv.validate_improvement_artifact(p.read_text(encoding="utf-8"), p, "TASK-001")
        assert not result.ok


# ─────────────────────────────────────────────
# compare_reconstructed_scope
# ─────────────────────────────────────────────

class TestValidatePremortemEdges:
    def _make_plan(self, tmp_path, risks):
        p = tmp_path / "plan.md"
        p.write_text(f"# Plan\n## Risks\n{risks}\n", encoding="utf-8")
        return p

    def _make_task(self, tmp_path, title):
        p = tmp_path / "task.md"
        p.write_text(f"# Task: {title}\n## Metadata\n", encoding="utf-8")
        return p

    def test_insufficient_risk_count_for_code_task(self, tmp_path):
        risks = textwrap.dedent("""\
            R1: Issue
            - Risk: Something
            - Trigger: Event
            - Detection: Monitor
            - Mitigation: Fix
            - Severity: blocking
        """)
        plan = self._make_plan(tmp_path, risks)
        task = self._make_task(tmp_path, "Implement Feature")
        result = gsv.validate_premortem(plan, task)
        assert not result.ok
        assert any("at least" in e and "numbered risks" in e for e in result.errors)

    def test_banned_phrase_warning(self, tmp_path):
        risks = textwrap.dedent("""\
            R1: Issue one
            - Risk: Something may break 風險低
            - Trigger: Event
            - Detection: Monitor
            - Mitigation: Fix
            - Severity: blocking
            R2: Issue two
            - Risk: Another thing
            - Trigger: Event2
            - Detection: Monitor2
            - Mitigation: Fix2
            - Severity: non-blocking
            R3: Issue three
            - Risk: Third thing
            - Trigger: Event3
            - Detection: Monitor3
            - Mitigation: Fix3
            - Severity: non-blocking
        """)
        plan = self._make_plan(tmp_path, risks)
        result = gsv.validate_premortem(plan, None)
        assert result.ok
        assert any("風險低" in w for w in result.warnings)

    def test_hotfix_policy_fewer_risks_ok(self, tmp_path):
        risks = textwrap.dedent("""\
            R1: Hotfix risk
            - Risk: Deployment failure
            - Trigger: Bad deploy
            - Detection: Monitor
            - Mitigation: Rollback
            - Severity: non-blocking
        """)
        plan = self._make_plan(tmp_path, risks)
        task = self._make_task(tmp_path, "Hotfix: critical bug")
        result = gsv.validate_premortem(plan, task)
        assert result.ok

    def test_insufficient_blocking_count(self, tmp_path):
        risks = textwrap.dedent("""\
            R1: Issue one
            - Risk: Something
            - Trigger: Event
            - Detection: Monitor
            - Mitigation: Fix
            - Severity: non-blocking
            R2: Issue two
            - Risk: Another
            - Trigger: Event2
            - Detection: Monitor2
            - Mitigation: Fix2
            - Severity: non-blocking
            R3: Issue three
            - Risk: Third
            - Trigger: Event3
            - Detection: Monitor3
            - Mitigation: Fix3
            - Severity: non-blocking
        """)
        plan = self._make_plan(tmp_path, risks)
        task = self._make_task(tmp_path, "Implement feature")
        result = gsv.validate_premortem(plan, task)
        assert not result.ok
        assert any("blocking risks" in e for e in result.errors)


# ─────────────────────────────────────────────
# validate_research_artifact
# ─────────────────────────────────────────────

class TestValidateResearchArtifact:
    def _setup_research(self, tmp_path, task_id="TASK-001", research_text="", status_state="researched"):
        arts = tmp_path / "artifacts"
        for d in ("tasks", "research", "status"):
            (arts / d).mkdir(parents=True, exist_ok=True)
        # Status
        status = {
            "task_id": task_id,
            "state": status_state,
            "current_owner": "Claude",
            "next_agent": "Claude",
            "required_artifacts": ["task", "research", "status"],
            "available_artifacts": ["task", "research", "status"],
            "missing_artifacts": [],
            "blocked_reason": "",
            "last_updated": "2026-01-15T10:00:00+08:00",
        }
        (arts / "status" / f"{task_id}.status.json").write_text(
            json.dumps(status, indent=2), encoding="utf-8"
        )
        # Research
        p = arts / "research" / f"{task_id}.research.md"
        p.write_text(research_text, encoding="utf-8")
        return p

    def test_recommendation_forbidden(self, tmp_path):
        text = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            - Q1
            ## Confirmed Facts
            - Fact one https://example.com
            ## Uncertain Items
            - UNVERIFIED: Maybe
            ## Relevant References
            - Ref
            ## Constraints For Implementation
            - Must use X
            ## Recommendation
            Do this instead
            ## Sources
            [1] Author. "Title." https://example.com (2026-01-15 retrieved)
            [2] Author2. "Title2." https://example2.com (2026-01-15 retrieved)
        """)
        p = self._setup_research(tmp_path, research_text=text)
        result = gsv.validate_research_artifact("TASK-001", text, p)
        assert not result.ok
        assert any("Recommendation" in e for e in result.errors)

    def test_unverified_in_confirmed_facts(self, tmp_path):
        text = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            - Q1
            ## Confirmed Facts
            - UNVERIFIED: This should be in uncertain https://example.com
            ## Uncertain Items
            - UNVERIFIED: Maybe
            ## Relevant References
            - Ref
            ## Constraints For Implementation
            - Must do X
            ## Sources
            [1] Author. "Title." https://example.com (2026-01-15 retrieved)
            [2] Author2. "Title2." https://example2.com (2026-01-15 retrieved)
        """)
        p = self._setup_research(tmp_path, research_text=text)
        result = gsv.validate_research_artifact("TASK-001", text, p)
        assert not result.ok
        assert any("UNVERIFIED" in e and "Confirmed Facts" in e for e in result.errors)

    def test_uncertain_without_prefix(self, tmp_path):
        text = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            - Q1
            ## Confirmed Facts
            - Fact https://example.com
            ## Uncertain Items
            - Maybe something
            ## Relevant References
            - Ref
            ## Constraints For Implementation
            - Must do X
            ## Sources
            [1] Author. "Title." https://example.com (2026-01-15 retrieved)
            [2] Author2. "Title2." https://example2.com (2026-01-15 retrieved)
        """)
        p = self._setup_research(tmp_path, research_text=text)
        result = gsv.validate_research_artifact("TASK-001", text, p)
        assert not result.ok
        assert any("UNVERIFIED:" in e for e in result.errors)


# ─────────────────────────────────────────────
# build_decision_registry: parsing helpers
# ─────────────────────────────────────────────

class TestVerifyResultIsPass:
    def test_pass(self, tmp_path):
        p = tmp_path / "verify.md"
        p.write_text("# Verify\n## Pass Fail Result\npass\n", encoding="utf-8")
        assert gsv.verify_result_is_pass(p) is True

    def test_fail(self, tmp_path):
        p = tmp_path / "verify.md"
        p.write_text("# Verify\n## Pass Fail Result\nfail\n", encoding="utf-8")
        assert gsv.verify_result_is_pass(p) is False

    def test_missing(self, tmp_path):
        p = tmp_path / "verify.md"
        p.write_text("# Verify\nNo result section\n", encoding="utf-8")
        assert gsv.verify_result_is_pass(p) is False

class TestParseStructuredChecklistFields:
    def test_bold_format(self):
        text = "- **criterion**: Build passes\n- **method**: CI\n"
        fields = gsv.parse_structured_checklist_fields(text)
        assert fields["criterion"] == "Build passes"
        assert fields["method"] == "CI"

    def test_plain_format(self):
        text = "- criterion: Build passes\n- method: CI\n"
        fields = gsv.parse_structured_checklist_fields(text)
        assert fields["criterion"] == "Build passes"

    def test_empty(self):
        assert gsv.parse_structured_checklist_fields("no fields") == {}


# ─────────────────────────────────────────────
# classify_premortem_policy
# ─────────────────────────────────────────────

class TestLoadArchiveSnapshot:
    def test_no_archive_path(self, tmp_path):
        code_path = tmp_path / "code.md"
        evidence = {}
        result = gsv.load_archive_snapshot(tmp_path, code_path, evidence, set())
        assert result == (None, None, None)

    def test_mismatched_archive_fields(self, tmp_path):
        code_path = tmp_path / "code.md"
        evidence = {"archive path": "archive.txt"}
        files, rel, err = gsv.load_archive_snapshot(tmp_path, code_path, evidence, set())
        assert err is not None
        assert "together" in err

    def test_invalid_sha256_format(self, tmp_path):
        code_path = tmp_path / "code.md"
        evidence = {"archive path": "archive.txt", "archive sha256": "not-a-sha"}
        files, rel, err = gsv.load_archive_snapshot(tmp_path, code_path, evidence, set())
        assert "hexadecimal" in err

    def test_archive_file_missing(self, tmp_path):
        import hashlib
        code_path = tmp_path / "code.md"
        evidence = {
            "archive path": "archive.txt",
            "archive sha256": "a" * 64,
        }
        files, rel, err = gsv.load_archive_snapshot(tmp_path, code_path, evidence, set())
        assert "does not exist" in err

    def test_sha256_mismatch(self, tmp_path):
        import hashlib
        archive = tmp_path / "archive.txt"
        archive.write_bytes(b"src/main.py\n")
        code_path = tmp_path / "code.md"
        evidence = {
            "archive path": "archive.txt",
            "archive sha256": "b" * 64,
        }
        files, rel, err = gsv.load_archive_snapshot(tmp_path, code_path, evidence, set())
        assert "does not match" in err

    def test_valid_archive(self, tmp_path):
        import hashlib
        archive_bytes = b"src/main.py\ntests/test_main.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(archive_bytes)
        sha = hashlib.sha256(archive_bytes).hexdigest()
        code_path = tmp_path / "code.md"
        snapshot = {"src/main.py", "tests/test_main.py"}
        evidence = {"archive path": "archive.txt", "archive sha256": sha}
        files, rel, err = gsv.load_archive_snapshot(tmp_path, code_path, evidence, snapshot)
        assert err is None
        assert files == snapshot

    def test_blank_line_in_archive(self, tmp_path):
        import hashlib
        archive_bytes = b"src/main.py\n\ntests/test_main.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(archive_bytes)
        sha = hashlib.sha256(archive_bytes).hexdigest()
        code_path = tmp_path / "code.md"
        evidence = {"archive path": "archive.txt", "archive sha256": sha}
        files, rel, err = gsv.load_archive_snapshot(tmp_path, code_path, evidence, set())
        assert "blank line" in err

    def test_unsorted_archive(self, tmp_path):
        import hashlib
        archive_bytes = b"tests/test_main.py\nsrc/main.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(archive_bytes)
        sha = hashlib.sha256(archive_bytes).hexdigest()
        code_path = tmp_path / "code.md"
        evidence = {"archive path": "archive.txt", "archive sha256": sha}
        files, rel, err = gsv.load_archive_snapshot(tmp_path, code_path, evidence, set())
        assert "sorted" in err

    def test_snapshot_mismatch(self, tmp_path):
        import hashlib
        archive_bytes = b"src/main.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(archive_bytes)
        sha = hashlib.sha256(archive_bytes).hexdigest()
        code_path = tmp_path / "code.md"
        evidence = {"archive path": "archive.txt", "archive sha256": sha}
        files, rel, err = gsv.load_archive_snapshot(tmp_path, code_path, evidence, {"other.py"})
        assert "does not match Changed Files Snapshot" in err

    def test_archive_exceeds_replay_byte_cap(self, tmp_path):
        import hashlib
        archive_bytes = b"a" * (gsv.MAX_DIFF_EVIDENCE_REPLAY_BYTES + 1)
        archive = tmp_path / "archive.txt"
        archive.write_bytes(archive_bytes)
        sha = hashlib.sha256(archive_bytes).hexdigest()
        code_path = tmp_path / "code.md"
        evidence = {"archive path": "archive.txt", "archive sha256": sha}
        files, rel, err = gsv.load_archive_snapshot(tmp_path, code_path, evidence, set())
        assert err is not None
        assert "exceeds replay byte cap" in err


# ─────────────────────────────────────────────
# validate_markdown_artifact
# ─────────────────────────────────────────────

class TestValidateMarkdownArtifact:
    def test_valid_task(self, tmp_path):
        p = _build_task_artifact(tmp_path, "TASK-001")
        result = gsv.validate_markdown_artifact(p, "task", "TASK-001")
        assert not result.errors

    def test_missing_marker(self, tmp_path):
        d = tmp_path / "tasks"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "TASK-001.task.md"
        p.write_text("# Wrong Header\n- Task ID: TASK-001\n", encoding="utf-8")
        result = gsv.validate_markdown_artifact(p, "task", "TASK-001")
        assert any("missing required markers" in e for e in result.errors)

    def test_missing_task_id(self, tmp_path):
        d = tmp_path / "tasks"
        d.mkdir(parents=True, exist_ok=True)
        content = textwrap.dedent("""\
            # Task: Test
            ## Metadata
            - Artifact Type: task
            - Task ID: TASK-999
            - Owner: Claude
            - Status: drafted
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Objective
            test
            ## Constraints
            none
            ## Acceptance Criteria
            done
        """)
        p = d / "TASK-001.task.md"
        p.write_text(content, encoding="utf-8")
        result = gsv.validate_markdown_artifact(p, "task", "TASK-001")
        assert any("missing exact task id" in e for e in result.errors)

    def test_plan_ready_for_coding_yes(self, tmp_path):
        p = _build_plan_artifact(tmp_path, "TASK-001", ready="yes")
        result = gsv.validate_markdown_artifact(p, "plan", "TASK-001")
        assert not any("Ready For Coding" in e for e in result.errors)

    def test_plan_not_ready_error(self, tmp_path):
        p = _build_plan_artifact(tmp_path, "TASK-001", ready="maybe")
        result = gsv.validate_markdown_artifact(p, "plan", "TASK-001")
        assert any("Ready For Coding" in e for e in result.errors)

    def test_verify_pass_fail_result(self, tmp_path):
        p = _build_verify_artifact(tmp_path, "TASK-001", result="pass")
        result = gsv.validate_markdown_artifact(p, "verify", "TASK-001")
        assert not any("Pass Fail Result" in e for e in result.errors)

    def test_verify_missing_pass_fail(self, tmp_path):
        d = tmp_path / "verify"
        d.mkdir(parents=True, exist_ok=True)
        content = textwrap.dedent("""\
            # Verification: TASK-001
            ## Metadata
            - Artifact Type: verify
            - Task ID: TASK-001
            - Owner: Claude
            - Status: pass
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Acceptance Criteria Checklist
            Content
            ## Pass Fail Result
            unknown
            ## Build Guarantee
            Commit xyz
        """)
        p = d / "TASK-001.verify.md"
        p.write_text(content, encoding="utf-8")
        result = gsv.validate_markdown_artifact(p, "verify", "TASK-001")
        assert any("Pass Fail Result" in e for e in result.errors)

    def test_invalid_status_value(self, tmp_path):
        d = tmp_path / "tasks"
        d.mkdir(parents=True, exist_ok=True)
        content = textwrap.dedent("""\
            # Task: Test
            ## Metadata
            - Artifact Type: task
            - Task ID: TASK-001
            - Owner: Claude
            - Status: invalid_status
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Objective
            test
            ## Constraints
            none
            ## Acceptance Criteria
            done
        """)
        p = d / "TASK-001.task.md"
        p.write_text(content, encoding="utf-8")
        result = gsv.validate_markdown_artifact(p, "task", "TASK-001")
        assert any("invalid Status" in e for e in result.errors)

    def test_code_mapping_to_plan_warnings(self, tmp_path):
        p = _build_code_artifact(tmp_path, "TASK-001")
        result = gsv.validate_markdown_artifact(p, "code", "TASK-001")
        assert not any("Mapping To Plan" in w for w in result.errors)

    def test_research_artifact_validation(self, tmp_path):
        _write_status(tmp_path, "TASK-001", _make_full_status("TASK-001"))
        p = _build_research_artifact(tmp_path, "TASK-001")
        result = gsv.validate_markdown_artifact(p, "research", "TASK-001")
        # Should validate without critical errors
        assert not any("## Recommendation" in e for e in result.errors)


# ─────────────────────────────────────────────
# validate_artifact_presence
# ─────────────────────────────────────────────

class TestValidateArtifactPresence:
    def test_drafted_with_task_and_status(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        status = _make_full_status(task_id, "drafted")
        _write_status(tmp_path, task_id, status)
        result = gsv.validate_artifact_presence(tmp_path, task_id, "drafted", status)
        assert not result.errors

    def test_drafted_missing_task(self, tmp_path):
        task_id = "TASK-001"
        status = _make_full_status(task_id, "drafted")
        _write_status(tmp_path, task_id, status)
        result = gsv.validate_artifact_presence(tmp_path, task_id, "drafted", status)
        assert any("Missing required" in e for e in result.errors)

    def test_coding_needs_plan_and_code(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _build_plan_artifact(tmp_path, task_id)
        _build_code_artifact(tmp_path, task_id)
        status = _make_full_status(task_id, "coding",
            required_artifacts=["task", "plan", "code", "status"],
            available_artifacts=["task", "plan", "code", "status"],
            missing_artifacts=[])
        _write_status(tmp_path, task_id, status)
        result = gsv.validate_artifact_presence(tmp_path, task_id, "coding", status)
        # Should not have missing artifact errors
        assert not any("Missing required" in e for e in result.errors)

    def test_done_requires_verify_pass(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _build_plan_artifact(tmp_path, task_id)
        _build_code_artifact(tmp_path, task_id)
        _build_verify_artifact(tmp_path, task_id, result="fail")
        status = _make_full_status(task_id, "done",
            required_artifacts=["task", "code", "verify", "status"],
            available_artifacts=["task", "plan", "code", "verify", "status"],
            missing_artifacts=[])
        _write_status(tmp_path, task_id, status)
        result = gsv.validate_artifact_presence(tmp_path, task_id, "done", status)
        assert any("Pass Fail Result = pass" in e for e in result.errors)

    def test_done_with_verify_pass(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _build_plan_artifact(tmp_path, task_id)
        _build_code_artifact(tmp_path, task_id)
        _build_verify_artifact(tmp_path, task_id, result="pass")
        status = _make_full_status(task_id, "done",
            required_artifacts=["task", "code", "verify", "status"],
            available_artifacts=["task", "plan", "code", "verify", "status"],
            missing_artifacts=[])
        _write_status(tmp_path, task_id, status)
        result = gsv.validate_artifact_presence(tmp_path, task_id, "done", status)
        assert not any("Pass Fail Result" in e for e in result.errors)

    def test_lightweight_mode_skips_plan(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _build_research_artifact(tmp_path, task_id)
        _build_code_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id))
        status = _make_full_status(task_id, "coding")
        _write_status(tmp_path, task_id, status)
        result = gsv.validate_artifact_presence(
            tmp_path, task_id, "coding", status,
            validation_mode=gsv.AUTO_CLASSIFY_LIGHTWEIGHT)
        assert any("Missing required artifacts" in e for e in result.errors)

    def test_available_artifacts_mismatch_warning(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        status = _make_full_status(task_id, "drafted",
            available_artifacts=["task", "research", "status"])  # research doesn't exist
        _write_status(tmp_path, task_id, status)
        result = gsv.validate_artifact_presence(tmp_path, task_id, "drafted", status)
        assert any("available_artifacts mismatch" in w for w in result.warnings)


# ─────────────────────────────────────────────
# validate_transition
# ─────────────────────────────────────────────

class TestValidateAll:
    def test_valid_drafted(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        result = gsv.validate_all(tmp_path, task_id)
        assert not result.errors

    def test_invalid_task_id(self, tmp_path):
        result = gsv.validate_all(tmp_path, "bad-id")
        assert any("Invalid task id" in e for e in result.errors)


# ─────────────────────────────────────────────
# build_reconcile_defaults
# ─────────────────────────────────────────────

class TestGsvValidateStatusSchema:
    def test_modern_valid(self, tmp_path):
        status = _make_full_status("TASK-001", "drafted")
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.errors

    def test_task_id_mismatch(self):
        status = _make_full_status("TASK-001", "drafted")
        result = gsv.validate_status_schema(status, "TASK-002")
        assert any("mismatch" in e for e in result.errors)

    def test_invalid_state(self):
        status = _make_full_status("TASK-001", "nonexistent")
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("Invalid state" in e for e in result.errors)

class TestGsvValidateArtifactPresenceDeeper:
    def test_coding_missing_plan_warning(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _build_code_artifact(tmp_path, task_id)
        status = _make_full_status(task_id, "coding",
            required_artifacts=["task", "plan", "code", "status"],
            available_artifacts=["task", "code", "status"],
            missing_artifacts=["plan"])
        _write_status(tmp_path, task_id, status)
        result = gsv.validate_artifact_presence(tmp_path, task_id, "coding", status)
        assert any("Missing required" in e for e in result.errors)

    def test_plan_not_ready_for_coding(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _build_plan_artifact(tmp_path, task_id, ready="no")
        _build_code_artifact(tmp_path, task_id)
        status = _make_full_status(task_id, "coding",
            required_artifacts=["task", "plan", "code", "status"],
            available_artifacts=["task", "plan", "code", "status"],
            missing_artifacts=[])
        _write_status(tmp_path, task_id, status)
        result = gsv.validate_artifact_presence(tmp_path, task_id, "coding", status)
        assert any("Ready For Coding" in e for e in result.errors)

class TestGsvValidateResearchArtifact:
    def test_missing_sources(self, tmp_path):
        task_id = "TASK-001"
        d = tmp_path / "artifacts" / "research"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            Q1
            ## Confirmed Facts
            - Fact 1 https://example.com/source
            ## Constraints For Implementation
            Constraint 1
        """)
        p = d / "TASK-001.research.md"
        p.write_text(content, encoding="utf-8")
        _write_status(tmp_path / "artifacts", task_id, _make_full_status(task_id))
        result = gsv.validate_research_artifact(task_id, content, p)
        assert isinstance(result, gsv.ValidationResult)

    def test_valid_sources(self, tmp_path):
        task_id = "TASK-001"
        d = tmp_path / "artifacts" / "research"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            Q1
            ## Confirmed Facts
            - Fact 1 https://example.com/source
            ## Constraints For Implementation
            Constraint 1
            ## Sources
            [1] Author. "Title." https://example.com (2026-01-15 retrieved)
            [2] Author2. "Title2." https://example2.com (2026-01-14 retrieved)
        """)
        p = d / "TASK-001.research.md"
        p.write_text(content, encoding="utf-8")
        _write_status(tmp_path / "artifacts", task_id, _make_full_status(task_id))
        result = gsv.validate_research_artifact(task_id, content, p)
        assert not result.errors

class TestGsvValidatePremortemDeeper:
    def test_plan_with_insufficient_risks(self, tmp_path):
        p = _build_plan_artifact(tmp_path, "TASK-001", risk_count=2)
        task = _build_task_artifact(tmp_path, "TASK-001")
        result = gsv.validate_premortem(p, task)
        assert any("at least" in e for e in result.errors)

    def test_plan_with_no_risks_section(self, tmp_path):
        d = tmp_path / "plans"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Plan: TASK-001
            ## Metadata
            - Artifact Type: plan
            - Task ID: TASK-001
            - Owner: Claude
            - Status: approved
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Scope
            Test
        """)
        p = d / "TASK-001.plan.md"
        p.write_text(content, encoding="utf-8")
        result = gsv.validate_premortem(p, None)
        assert any("Risks" in e for e in result.errors)


# ─────────────────────────────────────────────
# Phase 3b: closing the 90% gap
# ─────────────────────────────────────────────

class TestGsvLegacyStatusSchema:
    def test_valid_legacy(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "drafted",
            "owner": "Claude",
            "last_updated": _ts(),
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not result.errors

    def test_missing_owner(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "drafted",
            "owner": "",
            "last_updated": _ts(),
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("owner" in e for e in result.errors)

    def test_blocked_no_blockers(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "blocked",
            "owner": "Claude",
            "last_updated": _ts(),
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("blockers" in e for e in result.errors)

    def test_blocked_with_blockers(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "blocked",
            "owner": "Claude",
            "last_updated": _ts(),
            "blockers": ["dependency not ready"],
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert not any("blockers" in e for e in result.errors)

    def test_non_blocked_with_blockers_warns(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "drafted",
            "owner": "Claude",
            "last_updated": _ts(),
            "blockers": ["leftover blocker"],
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("blockers" in w for w in result.warnings)

    def test_bad_artifacts_type(self):
        status = {
            "task_id": "TASK-001",
            "current_state": "drafted",
            "owner": "Claude",
            "last_updated": _ts(),
            "artifacts": "not-a-dict",
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("artifacts" in e for e in result.errors)

class TestGsvModernStatusSchemaDeeper:
    def test_unknown_artifact_in_lists(self):
        status = _make_full_status("TASK-001", "drafted")
        status["required_artifacts"] = ["task", "status", "nonexistent_type"]
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("unknown artifacts" in e for e in result.errors)

    def test_non_list_required_artifacts(self):
        status = _make_full_status("TASK-001", "drafted")
        status["required_artifacts"] = "not-a-list"
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("must be a list" in e for e in result.errors)

    def test_blocked_no_reason(self):
        status = _make_full_status("TASK-001", "blocked")
        status["blocked_reason"] = ""
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("blocked_reason" in e for e in result.errors)

    def test_non_blocked_with_reason_warns(self):
        status = _make_full_status("TASK-001", "drafted")
        status["blocked_reason"] = "old reason"
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("blocked_reason" in w for w in result.warnings)

class TestGsvResearchArtifactEdgeCases:
    def _setup_research(self, tmp_path, task_id, content):
        d = tmp_path / "artifacts" / "research"
        d.mkdir(parents=True)
        p = d / f"{task_id}.research.md"
        p.write_text(content, encoding="utf-8")
        _write_status(tmp_path / "artifacts", task_id, _make_full_status(task_id))
        return p

    def test_recommendation_forbidden(self, tmp_path):
        content = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            Q1
            ## Confirmed Facts
            - Fact 1 https://example.com/source
            ## Constraints For Implementation
            Constraint 1
            ## Recommendation
            Do X
            ## Sources
            [1] Author. "Title." https://example.com (2026-01-15 retrieved)
            [2] Author2. "Title2." https://example2.com (2026-01-15 retrieved)
        """)
        p = self._setup_research(tmp_path, "TASK-001", content)
        result = gsv.validate_research_artifact("TASK-001", content, p)
        assert any("Recommendation" in e for e in result.errors)

    def test_empty_confirmed_facts(self, tmp_path):
        content = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            Q1
            ## Confirmed Facts
            ## Constraints For Implementation
            Constraint 1
            ## Sources
            [1] Author. "Title." https://example.com (2026-01-15 retrieved)
            [2] Author2. "Title2." https://example2.com (2026-01-15 retrieved)
        """)
        p = self._setup_research(tmp_path, "TASK-001", content)
        result = gsv.validate_research_artifact("TASK-001", content, p)
        assert any("Confirmed Facts" in e for e in result.errors)

    def test_unverified_in_confirmed_facts(self, tmp_path):
        content = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            Q1
            ## Confirmed Facts
            - UNVERIFIED: Something not confirmed https://example.com
            ## Constraints For Implementation
            Constraint 1
            ## Sources
            [1] Author. "Title." https://example.com (2026-01-15 retrieved)
            [2] Author2. "Title2." https://example2.com (2026-01-15 retrieved)
        """)
        p = self._setup_research(tmp_path, "TASK-001", content)
        result = gsv.validate_research_artifact("TASK-001", content, p)
        assert any("UNVERIFIED" in e for e in result.errors)

    def test_uncertain_items_without_prefix(self, tmp_path):
        content = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            Q1
            ## Confirmed Facts
            - Fact 1 https://example.com
            ## Uncertain Items
            - Missing the prefix
            ## Constraints For Implementation
            Constraint 1
            ## Sources
            [1] Author. "Title." https://example.com (2026-01-15 retrieved)
            [2] Author2. "Title2." https://example2.com (2026-01-15 retrieved)
        """)
        p = self._setup_research(tmp_path, "TASK-001", content)
        result = gsv.validate_research_artifact("TASK-001", content, p)
        assert any("UNVERIFIED:" in e for e in result.errors)

    def test_empty_constraints(self, tmp_path):
        content = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            Q1
            ## Confirmed Facts
            - Fact 1 https://example.com
            ## Constraints For Implementation
            None
            ## Sources
            [1] Author. "Title." https://example.com (2026-01-15 retrieved)
            [2] Author2. "Title2." https://example2.com (2026-01-15 retrieved)
        """)
        p = self._setup_research(tmp_path, "TASK-001", content)
        result = gsv.validate_research_artifact("TASK-001", content, p)
        assert any("Constraints" in e for e in result.errors)

    def test_mixed_github_sources(self, tmp_path):
        content = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: ready
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Research Questions
            Q1
            ## Confirmed Facts
            - Fact 1 https://github.com/owner1/myrepo
            - Fact 2 https://github.com/owner2/myrepo
            ## Constraints For Implementation
            Constraint 1
            ## Sources
            [1] Author. "Title." https://github.com/owner1/myrepo (2026-01-15 retrieved)
            [2] Author2. "Title2." https://github.com/owner2/myrepo (2026-01-15 retrieved)
        """)
        p = self._setup_research(tmp_path, "TASK-001", content)
        result = gsv.validate_research_artifact("TASK-001", content, p)
        assert any("mixed truth source" in w for w in result.warnings)

class TestGsvValidateResearchCitations:
    def _write_research(self, tmp_path, task_id, sources_text):
        d = tmp_path / "artifacts" / "research"
        d.mkdir(parents=True)
        content = textwrap.dedent(f"""\
            # Research: {task_id}
            ## Sources
            {sources_text}
        """)
        p = d / f"{task_id}.research.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_no_sources_section(self, tmp_path):
        task_id = "TASK-001"
        d = tmp_path / "artifacts" / "research"
        d.mkdir(parents=True)
        content = "# Research\n## Metadata\nstuff\n"
        p = d / f"{task_id}.research.md"
        p.write_text(content, encoding="utf-8")
        findings = gsv.validate_research_citations(task_id, p)
        assert any(f.severity == "CRITICAL" for f in findings)

    def test_sources_is_none(self, tmp_path):
        task_id = "TASK-001"
        p = self._write_research(tmp_path, task_id, "None")
        findings = gsv.validate_research_citations(task_id, p)
        assert any(f.severity == "CRITICAL" for f in findings)

    def test_only_one_source(self, tmp_path):
        task_id = "TASK-001"
        p = self._write_research(tmp_path, task_id,
            '[1] Author. "Title." https://example.com (2026-01-15 retrieved)')
        findings = gsv.validate_research_citations(task_id, p)
        assert any("at least 2" in f.message for f in findings)

    def test_url_only_line_with_partial_date(self, tmp_path):
        task_id = "TASK-001"
        sources = '[1] Author. "T." https://a.com (2026-01-15 retrieved)\nhttps://bare.com (2026-01 retrieved)'
        p = self._write_research(tmp_path, task_id, sources)
        findings = gsv.validate_research_citations(task_id, p)
        assert any(f.severity == "MINOR" for f in findings)

    def test_url_only_line_without_date(self, tmp_path):
        task_id = "TASK-001"
        sources = '[1] Author. "T." https://a.com (2026-01-15 retrieved)\nhttps://bare.com'
        p = self._write_research(tmp_path, task_id, sources)
        findings = gsv.validate_research_citations(task_id, p)
        assert any("MAJOR" == f.severity for f in findings)

    def test_non_matching_line(self, tmp_path):
        task_id = "TASK-001"
        sources = '[1] Author. "T." https://a.com (2026-01-15 retrieved)\njust plain text'
        p = self._write_research(tmp_path, task_id, sources)
        findings = gsv.validate_research_citations(task_id, p)
        assert any("MAJOR" == f.severity for f in findings)

class TestGsvValidateMarkdownArtifact:
    def test_valid_plan(self, tmp_path):
        d = tmp_path / "plans"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Plan: TASK-001
            ## Metadata
            - Artifact Type: plan
            - Task ID: TASK-001
            - Owner: Claude
            - Status: approved
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Scope
            Test scope
            ## Proposed Changes
            Change A
            ## Files Likely Affected
            - src/main.py
            ## Validation Strategy
            Run tests
            ## Ready For Coding
            yes
            ## Risks
            R1: Risk
            - Trigger: trigger
            - Detection: detection
            - Mitigation: mitigation
            - Severity: blocking
            R2: Another
            - Trigger: t
            - Detection: d
            - Mitigation: m
            - Severity: blocking
            R3: Third
            - Trigger: t
            - Detection: d
            - Mitigation: m
            - Severity: non-blocking
            R4: Fourth
            - Trigger: t
            - Detection: d
            - Mitigation: m
            - Severity: non-blocking
        """)
        p = d / "TASK-001.plan.md"
        p.write_text(content, encoding="utf-8")
        result = gsv.validate_markdown_artifact(p, "plan", "TASK-001")
        assert not result.errors

    def test_plan_missing_ready_for_coding(self, tmp_path):
        d = tmp_path / "plans"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Plan: TASK-001
            ## Metadata
            - Artifact Type: plan
            - Task ID: TASK-001
            - Owner: Claude
            - Status: approved
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Scope
            Test
        """)
        p = d / "TASK-001.plan.md"
        p.write_text(content, encoding="utf-8")
        result = gsv.validate_markdown_artifact(p, "plan", "TASK-001")
        assert any("Ready For Coding" in e for e in result.errors)

    def test_verify_missing_pass_fail(self, tmp_path):
        d = tmp_path / "verify"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Verify: TASK-001
            ## Metadata
            - Artifact Type: verify
            - Task ID: TASK-001
            - Owner: Claude
            - Status: done
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Build Guarantee
            Test
        """)
        p = d / "TASK-001.verify.md"
        p.write_text(content, encoding="utf-8")
        result = gsv.validate_markdown_artifact(p, "verify", "TASK-001")
        assert any("Pass Fail Result" in e for e in result.errors)

    def test_invalid_status_value(self, tmp_path):
        d = tmp_path / "tasks"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Task: TASK-001
            ## Metadata
            - Artifact Type: task
            - Task ID: TASK-001
            - Owner: Claude
            - Status: invalid_status_value
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Objective
            Test
            ## Constraints
            None
            ## Acceptance Criteria
            Done
        """)
        p = d / "TASK-001.task.md"
        p.write_text(content, encoding="utf-8")
        result = gsv.validate_markdown_artifact(p, "task", "TASK-001")
        assert any("invalid Status" in e for e in result.errors)

    def test_missing_owner(self, tmp_path):
        d = tmp_path / "tasks"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Task: TASK-001
            ## Metadata
            - Artifact Type: task
            - Task ID: TASK-001
            - Status: drafted
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Objective
            Test
            ## Constraints
            None
            ## Acceptance Criteria
            Done
        """)
        p = d / "TASK-001.task.md"
        p.write_text(content, encoding="utf-8")
        result = gsv.validate_markdown_artifact(p, "task", "TASK-001")
        assert any("Owner" in e for e in result.errors), f"Expected Owner error, got: {result.errors}"

class TestGsvLoadArchiveSnapshot:
    def test_path_without_sha(self, tmp_path):
        code = tmp_path / "code.md"
        code.write_text("x", encoding="utf-8")
        evidence = {"archive path": "archive.txt"}
        _, _, error = gsv.load_archive_snapshot(tmp_path, code, evidence, set())
        assert error is not None
        assert "together" in error

    def test_sha_without_path(self, tmp_path):
        code = tmp_path / "code.md"
        code.write_text("x", encoding="utf-8")
        evidence = {"archive sha256": "abc123"}
        _, _, error = gsv.load_archive_snapshot(tmp_path, code, evidence, set())
        assert error is not None
        assert "together" in error

    def test_both_empty(self, tmp_path):
        code = tmp_path / "code.md"
        code.write_text("x", encoding="utf-8")
        evidence = {}
        result, _, error = gsv.load_archive_snapshot(tmp_path, code, evidence, set())
        assert result is None
        assert error is None

    def test_archive_not_found(self, tmp_path):
        code = tmp_path / "code.md"
        code.write_text("x", encoding="utf-8")
        import hashlib
        evidence = {"archive path": "missing.txt", "archive sha256": "abc123"}
        _, _, error = gsv.load_archive_snapshot(tmp_path, code, evidence, set())
        assert error is not None

    def test_archive_sha_mismatch(self, tmp_path):
        import hashlib
        code = tmp_path / "code.md"
        code.write_text("x", encoding="utf-8")
        archive = tmp_path / "archive.txt"
        archive.write_text("file1.py\nfile2.py\n", encoding="utf-8")
        evidence = {"archive path": "archive.txt", "archive sha256": "0000000000000000000000000000000000000000000000000000000000000000"}
        _, _, error = gsv.load_archive_snapshot(tmp_path, code, evidence, {"file1.py", "file2.py"})
        assert error is not None
        assert "SHA256" in error

    def test_archive_valid(self, tmp_path):
        import hashlib
        code = tmp_path / "code.md"
        code.write_text("x", encoding="utf-8")
        archive = tmp_path / "archive.txt"
        archive.write_text("file1.py\nfile2.py\n", encoding="utf-8")
        real_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        evidence = {"archive path": "archive.txt", "archive sha256": real_hash}
        result, rel, error = gsv.load_archive_snapshot(tmp_path, code, evidence, {"file1.py", "file2.py"})
        assert error is None
        assert result is not None

class TestGsvValidateStatusSchemaLegacy:
    def test_legacy_schema_missing_owner(self, tmp_path):
        status = {
            "task_id": "TASK-001",
            "current_state": "drafted",
            "last_updated": _ts(),
        }
        result = gsv.validate_status_schema(status, "TASK-001")
        assert any("owner" in e.lower() for e in result.errors), f"Expected owner error, got: {result.errors}"

class TestGsvValidateVerifyChecklist:
    def test_valid_checklist(self, tmp_path):
        text = textwrap.dedent("""\
            ## Verification Summary
            Covered.

            ## Acceptance Criteria Checklist

            - Criterion: Tests pass
            - Method: pytest
            - Reviewer: Claude
            - Evidence: All tests green
            - Result: verified
            - Timestamp: 2026-01-15T10:00:00+08:00

            ## Overall Maturity
            poc

            ## Deferred Items
            None

            ## Pass Fail Result
            pass
        """)
        path = tmp_path / "verify.md"
        path.write_text(text, encoding="utf-8")
        result = gsv.validate_verify_checklist_schema(text, path)
        assert not result.warnings

    def test_missing_fields(self, tmp_path):
        text = textwrap.dedent("""\
            ## Verification Summary
            Covered.

            ## Acceptance Criteria Checklist

            - Criterion: Tests pass

            ## Overall Maturity
            poc

            ## Deferred Items
            None
        """)
        path = tmp_path / "verify.md"
        result = gsv.validate_verify_checklist_schema(text, path)
        assert any("missing" in w for w in result.warnings)

class TestGsvValidateArtifactPresenceCoding:
    def test_coding_plan_not_ready(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        # Modify plan to not be ready for coding
        plan_path = tmp_path / "plans" / "TASK-001.plan.md"
        text = plan_path.read_text(encoding="utf-8")
        text = text.replace("yes", "no")
        plan_path.write_text(text, encoding="utf-8")
        # Set state to coding
        sp = tmp_path / "status" / "TASK-001.status.json"
        s = json.loads(sp.read_text(encoding="utf-8"))
        s["state"] = "coding"
        sp.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = gsv.validate_all(tmp_path, "TASK-001")
        assert any("Ready For Coding" in e for e in result.errors)

class TestGsvValidateResearchArtifactDeeper:
    def test_research_with_invalid_source_format(self, tmp_path):
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        task_content = textwrap.dedent("""\
            # Task: TASK-001
            ## Metadata
            - Artifact Type: task
            - Task ID: TASK-001
            - Owner: Claude
            - Status: drafted
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Objective
            Test
        """)
        (tasks_dir / "TASK-001.task.md").write_text(task_content, encoding="utf-8")
        research_dir = tmp_path / "research"
        research_dir.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Research: TASK-001
            ## Metadata
            - Artifact Type: research
            - Task ID: TASK-001
            - Owner: Claude
            - Status: done
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Findings
            Some findings
            ## Sources
            1. First source
            2. Second source
        """)
        (research_dir / "TASK-001.research.md").write_text(content, encoding="utf-8")
        status_dir = tmp_path / "status"
        status_dir.mkdir(parents=True)
        (status_dir / "TASK-001.status.json").write_text(
            json.dumps({"task_id": "TASK-001", "state": "researched", "last_updated": _ts()}), encoding="utf-8"
        )
        result = gsv.validate_research_artifact("TASK-001", content, research_dir / "TASK-001.research.md")
        # Should warn about source format
        assert result.errors or result.warnings

class TestGsvValidatePremortimDeeper:
    def test_high_risk_signals_no_blocking_risk(self, tmp_path):
        plan_content = textwrap.dedent("""\
            # Plan: TASK-001
            ## Metadata
            - Artifact Type: plan
            - Task ID: TASK-001
            - Owner: Claude
            - Status: approved
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Scope
            Test
            ## Ready For Coding
            yes
            ## Risks
            R1: Risk
            - Trigger: trigger
            - Detection: detection
            - Mitigation: mitigation
            - Severity: non-blocking
        """)
        plan_path = tmp_path / "plan.md"
        plan_path.write_text(plan_content, encoding="utf-8")
        task_content = textwrap.dedent("""\
            # Task: TASK-001
            ## Metadata
            - Artifact Type: task
            - Task ID: TASK-001
            - Owner: Claude
            - Status: drafted
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Objective
            Test
            ## Inline Flags
            - task_type: security
        """)
        task_path = tmp_path / "task.md"
        task_path.write_text(task_content, encoding="utf-8")
        result = gsv.validate_premortem(plan_path, task_path)
        # With security task type, should need blocking risks
        assert result.errors or result.warnings

class TestGsvValidateAllIntegration:
    def test_valid_done_state(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        result = gsv.validate_all(tmp_path, "TASK-001")
        assert result.ok

    def test_invalid_task_id(self, tmp_path):
        result = gsv.validate_all(tmp_path, "bad-id")
        assert not result.ok

    def test_lightweight_mode(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        result = gsv.validate_all(tmp_path, "TASK-001", validation_mode=gsv.AUTO_CLASSIFY_LIGHTWEIGHT)
        assert result.ok

class TestGsvPlanHasNonEmptyRisks:
    """Cover lines 362-363."""
    def test_with_risks(self):
        text = "## Risks\n- Risk 1: something\n"
        assert gsv.plan_has_non_empty_risks(text) is True

    def test_empty_risks(self):
        text = "## Risks\nNone\n"
        assert gsv.plan_has_non_empty_risks(text) is False

    def test_no_section(self):
        text = "## Other\nstuff\n"
        assert gsv.plan_has_non_empty_risks(text) is False

class TestGsvValidateImprovementMissingSource:
    """Cover line 1079."""
    def test_missing_source_task(self):
        text = (
            "# Process Improvement\n"
            "## Metadata\n"
            "- Artifact Type: improvement\n"
            "- Task ID: TASK-001\n"
            "- Trigger Type: blocked\n"
            "- Owner: Claude\n"
            "- Status: drafted\n"
            f"- Last Updated: {_ts()}\n\n"
            "## 1. What Happened\nTest\n"
        )
        result = gsv.validate_improvement_artifact(text, Path("TASK-001.improvement.md"), "TASK-001")
        assert any("Source Task" in e for e in result.errors)

class TestGsvWriteTransitionValidateAllFails:
    """Cover line 1664."""
    @unittest.mock.patch.object(gsv, "validate_all", return_value=gsv.ValidationResult(["some error"], []))
    @unittest.mock.patch.object(gsv, "validate_transition", return_value=gsv.ValidationResult([], []))
    def test_validate_all_errors_returned(self, mock_vt, mock_va, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        result = gsv.write_transition(tmp_path, "TASK-001", "done", "blocked")
        assert not result.ok
        assert "some error" in result.errors

class TestGsvLoadArchiveSnapshotBranches:
    """Cover lines 422, 427-428, 437-438, 441, 449, 451 — load_archive_snapshot error paths."""

    def _make_evidence(self, archive_path, archive_sha256):
        return {"archive path": archive_path, "archive sha256": archive_sha256}

    def test_archive_path_not_found(self, tmp_path):
        """Line 427-428: FileNotFoundError when reading archive."""
        evidence = self._make_evidence(
            "nonexistent_archive.txt",
            "a" * 64,
        )
        _files, _rel, err = gsv.load_archive_snapshot(tmp_path, Path("TASK-001.code.md"), evidence, set())
        assert err is not None
        assert "does not exist" in err

    def test_archive_os_error(self, tmp_path):
        """Line 429-430: OSError on read."""
        archive = tmp_path / "archive.txt"
        archive.mkdir()  # directory, not file — read_bytes raises
        evidence = self._make_evidence("archive.txt", "a" * 64)
        _files, _rel, err = gsv.load_archive_snapshot(tmp_path, Path("TASK-001.code.md"), evidence, set())
        assert err is not None
        assert "unable to read" in err or "does not exist" in err or "denied" in err.lower() or "Is a directory" in err or "Error" in err

    def test_archive_sha256_mismatch(self, tmp_path):
        """Line 432-433: SHA256 doesn't match."""
        archive = tmp_path / "archive.txt"
        archive.write_text("src/main.py\n", encoding="utf-8")
        evidence = self._make_evidence("archive.txt", "b" * 64)
        _files, _rel, err = gsv.load_archive_snapshot(tmp_path, Path("TASK-001.code.md"), evidence, {"src/main.py"})
        assert err is not None
        assert "SHA256 does not match" in err

    def test_archive_non_utf8(self, tmp_path):
        """Lines 437-438: UnicodeDecodeError."""
        archive = tmp_path / "archive.bin"
        content = b"\x80\x81\x82\x83"
        archive.write_bytes(content)
        import hashlib
        sha = hashlib.sha256(content).hexdigest()
        evidence = self._make_evidence("archive.bin", sha)
        _files, _rel, err = gsv.load_archive_snapshot(tmp_path, Path("TASK-001.code.md"), evidence, set())
        assert err is not None
        assert "UTF-8" in err

    def test_archive_blank_line(self, tmp_path):
        """Line 449: blank line in archive."""
        import hashlib
        content = "src/main.py\n\ntests/test.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(content.encode("utf-8"))
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        evidence = self._make_evidence("archive.txt", sha)
        _files, _rel, err = gsv.load_archive_snapshot(
            tmp_path, Path("TASK-001.code.md"), evidence, {"src/main.py", "tests/test.py"}
        )
        assert err is not None
        assert "blank line" in err

    def test_archive_invalid_path_traversal(self, tmp_path):
        """Line 451: path with mid-traversal '/../'."""
        import hashlib
        content = "src/../escape/file.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(content.encode("utf-8"))
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        evidence = self._make_evidence("archive.txt", sha)
        _files, _rel, err = gsv.load_archive_snapshot(
            tmp_path, Path("TASK-001.code.md"), evidence, {"src/../escape/file.py"}
        )
        assert err is not None
        assert "invalid path" in err

    def test_archive_unsorted(self, tmp_path):
        """Line 459: paths not sorted."""
        import hashlib
        content = "z/file.py\na/file.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(content.encode("utf-8"))
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        evidence = self._make_evidence("archive.txt", sha)
        _files, _rel, err = gsv.load_archive_snapshot(
            tmp_path, Path("TASK-001.code.md"), evidence, {"a/file.py", "z/file.py"}
        )
        assert err is not None
        assert "sorted" in err

    def test_archive_duplicate_path(self, tmp_path):
        """Line 454-455: duplicate path."""
        import hashlib
        content = "src/main.py\nsrc/main.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(content.encode("utf-8"))
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        evidence = self._make_evidence("archive.txt", sha)
        _files, _rel, err = gsv.load_archive_snapshot(
            tmp_path, Path("TASK-001.code.md"), evidence, {"src/main.py"}
        )
        assert err is not None
        assert "duplicate" in err

    def test_archive_snapshot_mismatch(self, tmp_path):
        """Line 462-464: archive files != snapshot files."""
        import hashlib
        content = "src/main.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(content.encode("utf-8"))
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        evidence = self._make_evidence("archive.txt", sha)
        _files, _rel, err = gsv.load_archive_snapshot(
            tmp_path, Path("TASK-001.code.md"), evidence, {"src/main.py", "src/extra.py"}
        )
        assert err is not None
        assert "does not match Changed Files Snapshot" in err

    def test_archive_success(self, tmp_path):
        """Happy path: archive matches snapshot."""
        import hashlib
        content = "src/extra.py\nsrc/main.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(content.encode("utf-8"))
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
        evidence = self._make_evidence("archive.txt", sha)
        files, rel, err = gsv.load_archive_snapshot(
            tmp_path, Path("TASK-001.code.md"), evidence, {"src/main.py", "src/extra.py"}
        )
        assert err is None
        assert files == {"src/main.py", "src/extra.py"}
        assert rel == "archive.txt"

    def test_archive_path_and_sha_must_appear_together(self, tmp_path):
        """Line 414: archive_path without sha256."""
        evidence = {"archive path": "archive.txt", "archive sha256": ""}
        _files, _rel, err = gsv.load_archive_snapshot(tmp_path, Path("TASK-001.code.md"), evidence, set())
        assert err is not None
        assert "together" in err

    def test_archive_sha_invalid_hex(self, tmp_path):
        """Line 420: invalid hex string."""
        evidence = {"archive path": "archive.txt", "archive sha256": "not-hex"}
        _files, _rel, err = gsv.load_archive_snapshot(tmp_path, Path("TASK-001.code.md"), evidence, set())
        assert err is not None
        assert "hexadecimal" in err

    def test_no_archive_returns_none(self, tmp_path):
        """Line 417-418: both empty → return None,None,None."""
        evidence = {"archive path": "", "archive sha256": ""}
        files, rel, err = gsv.load_archive_snapshot(tmp_path, Path("TASK-001.code.md"), evidence, set())
        assert files is None
        assert rel is None
        assert err is None

class TestGsvVerifyChecklistStructuredMissingField:
    """Cover line 1134 — structured checklist item missing a field."""
    def test_missing_evidence_field(self, tmp_path):
        text = (
            "## Acceptance Criteria Checklist\n\n"
            "- **Criterion**: Feature works\n"
            "- **Method**: Manual test\n"
            "- **Reviewer**: Alice\n"
            "- **Timestamp**: 2026-01-15T10:00:00+08:00\n"
        )
        path = tmp_path / "TASK-001.verify.md"
        result = gsv.validate_verify_checklist_schema(text, path)
        assert any("missing evidence field" in w or "missing result field" in w for w in result.warnings)

    def test_all_fields_present_no_warning(self, tmp_path):
        text = (
            "## Acceptance Criteria Checklist\n\n"
            "- **Criterion**: Feature works\n"
            "- **Method**: Manual test\n"
            "- **Evidence**: Screenshot attached\n"
            "- **Result**: verified\n"
            "- **Reviewer**: Alice\n"
            "- **Timestamp**: 2026-01-15T10:00:00+08:00\n"
        )
        path = tmp_path / "TASK-001.verify.md"
        result = gsv.validate_verify_checklist_schema(text, path)
        # No missing-field warnings
        missing_warnings = [w for w in result.warnings if "missing" in w and "field" in w]
        assert not missing_warnings

class TestGsvValidateAllScopeDriftGitBacked:
    """Cover lines 1413-1421 — validate_all calls detect_git_backed_scope_drift."""
    @unittest.mock.patch.object(gsv, "load_git_scope_context")
    def test_git_backed_drift_in_coding_state(self, mock_lgsc, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        # Set state to coding (validate_all reads state from status.json)
        sp = tmp_path / "status" / "TASK-001.status.json"
        status = json.loads(sp.read_text(encoding="utf-8"))
        status["state"] = "coding"
        sp.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Mock git scope context: task artifacts overlap actual_changed
        mock_lgsc.return_value = (
            tmp_path,
            {"src/main.py", "src/extra.py", "artifacts/tasks/TASK-001.task.md"},
            {"artifacts/tasks/TASK-001.task.md"},
            [],
        )
        result = gsv.validate_all(tmp_path, "TASK-001")
        # non-strict → waiver_candidate_errors go to warnings
        assert any("src/extra.py" in w for w in result.warnings)

class TestGsvValidateAllHistoricalDrift:
    """Cover lines 1425-1432 — validate_all falls through to detect_historical_diff_scope_drift."""
    @unittest.mock.patch.object(gsv, "detect_historical_diff_scope_drift")
    @unittest.mock.patch.object(gsv, "load_git_scope_context")
    def test_historical_drift_in_done_state(self, mock_lgsc, mock_hdsd, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        # done state (already set by _setup_valid_done_tree) → historical branch
        mock_lgsc.return_value = (tmp_path, set(), set(), [])
        mock_hdsd.return_value = gsv.ScopeCheckResult(
            [], ["drift warning candidate"], ["some warning"], {"src/drifted.py"}
        )
        result = gsv.validate_all(tmp_path, "TASK-001")
        # waiver_candidate_errors become warnings (non-strict)
        assert any("drift warning candidate" in w for w in result.warnings)
        assert any("some warning" in w for w in result.warnings)

class TestGsvValidateAllScopeDriftWaiver:
    """Cover lines 1443-1445 — scope drift waiver integration in validate_all."""
    @unittest.mock.patch.object(gsv, "validate_scope_drift_waiver")
    @unittest.mock.patch.object(gsv, "detect_historical_diff_scope_drift")
    @unittest.mock.patch.object(gsv, "load_git_scope_context")
    @unittest.mock.patch.object(gsv, "detect_plan_code_scope_drift")
    def test_waiver_triggered_on_drift(self, mock_pcsd, mock_lgsc, mock_hdsd, mock_vsdw, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        mock_pcsd.return_value = {"src/drifted.py"}
        mock_lgsc.return_value = (tmp_path, set(), set(), [])
        mock_hdsd.return_value = gsv.ScopeCheckResult([], [], [], set())
        mock_vsdw.return_value = gsv.ValidationResult(
            ["waiver not found for drift files"], ["waiver info"]
        )
        result = gsv.validate_all(tmp_path, "TASK-001", strict_scope=False)
        # validate_scope_drift_waiver was called
        mock_vsdw.assert_called_once()
        assert any("waiver not found" in e for e in result.errors)


# ── Phase 5b: Targeting remaining uncovered lines ───────────────────

class TestGsvLoadArchiveInvalidPath:
    """Cover line 422 — resolve_workspace_relative_path returns error for archive path."""
    def test_archive_path_with_slash_prefix(self, tmp_path):
        import hashlib
        evidence = {"archive path": "/etc/shadow", "archive sha256": "a" * 64}
        _files, _rel, err = gsv.load_archive_snapshot(tmp_path, Path("TASK-001.code.md"), evidence, set())
        assert err is not None
        assert "invalid Archive Path" in err

    def test_archive_path_escape(self, tmp_path):
        evidence = {"archive path": "../../secret", "archive sha256": "b" * 64}
        _files, _rel, err = gsv.load_archive_snapshot(tmp_path, Path("TASK-001.code.md"), evidence, set())
        assert err is not None
        assert "invalid Archive Path" in err

class TestGsvLoadArchiveEmptyFile:
    """Cover line 441 — archive file has no lines."""
    def test_empty_archive(self, tmp_path):
        import hashlib
        archive = tmp_path / "empty_archive.txt"
        archive.write_bytes(b"")
        sha = hashlib.sha256(b"").hexdigest()
        evidence = {"archive path": "empty_archive.txt", "archive sha256": sha}
        _files, _rel, err = gsv.load_archive_snapshot(tmp_path, Path("TASK-001.code.md"), evidence, set())
        assert err is not None
        assert "at least one" in err

class TestGsvVerifyChecklistNonMatchingFields:
    """Cover line 1134 — structured block with no matching key fields."""
    def test_block_with_only_evidence_result(self, tmp_path):
        text = (
            "## Verification Summary\n"
            "Covered.\n\n"
            "## Acceptance Criteria Checklist\n\n"
            "- **Evidence**: Screenshot\n"
            "- **Result**: verified\n"
            "\n## Overall Maturity\n"
            "poc\n\n"
            "## Deferred Items\n"
            "None\n\n"
            "## Pass Fail Result\n"
            "pass\n"
        )
        path = tmp_path / "TASK-001.verify.md"
        result = gsv.validate_verify_checklist_schema(text, path)
        assert any("requires at least one structured checklist item" in w for w in result.warnings)

class TestGsvValidateAllStrictScopePlanCodeDrift:
    """Cover line 1419 — strict_scope=True with plan-code drift."""
    @unittest.mock.patch.object(gsv, "load_git_scope_context")
    @unittest.mock.patch.object(gsv, "detect_plan_code_scope_drift")
    def test_strict_scope_plan_code_drift(self, mock_pcsd, mock_lgsc, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        sp = tmp_path / "status" / "TASK-001.status.json"
        status = json.loads(sp.read_text(encoding="utf-8"))
        status["state"] = "coding"
        sp.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        mock_pcsd.return_value = {"src/drifted.py"}
        mock_lgsc.return_value = (tmp_path, set(), set(), [])
        result = gsv.validate_all(tmp_path, "TASK-001", strict_scope=True)
        assert any("files changed not listed in" in e and "src/drifted.py" in e for e in result.errors)

class TestGsvValidateAllStrictScopeGitBackedDrift:
    """Cover line 1429 — strict_scope=True with git-backed drift."""
    @unittest.mock.patch.object(gsv, "load_git_scope_context")
    def test_strict_scope_git_backed_drift(self, mock_lgsc, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        sp = tmp_path / "status" / "TASK-001.status.json"
        status = json.loads(sp.read_text(encoding="utf-8"))
        status["state"] = "coding"
        sp.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        mock_lgsc.return_value = (
            tmp_path,
            {"src/main.py", "src/extra.py", "artifacts/tasks/TASK-001.task.md"},
            {"artifacts/tasks/TASK-001.task.md"},
            [],
        )
        result = gsv.validate_all(tmp_path, "TASK-001", strict_scope=True)
        assert any("git-backed scope check" in e and "src/extra.py" in e for e in result.errors)


# ── Phase 6: commit-range / github-pr scope drift (lines 722-786) ──


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

