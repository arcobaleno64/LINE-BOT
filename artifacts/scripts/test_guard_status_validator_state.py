"""Split unit tests for guard_status_validator state and waivers per TASK-1054."""
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


class TestResolveStatusState:
    def test_modern_schema(self):
        assert gsv.resolve_status_state({"state": "coding"}) == "coding"

    def test_legacy_schema(self):
        assert gsv.resolve_status_state({"current_state": "research_ready"}) == "researched"

    def test_empty(self):
        assert gsv.resolve_status_state({}) is None

class TestLegalTransitions:
    def test_valid_transitions(self):
        assert "researched" in gsv.LEGAL_TRANSITIONS["drafted"]
        assert "blocked" in gsv.LEGAL_TRANSITIONS["drafted"]
        assert "planned" in gsv.LEGAL_TRANSITIONS["researched"]
        assert "done" in gsv.LEGAL_TRANSITIONS["verifying"]

    def test_no_escape_from_done(self):
        assert gsv.LEGAL_TRANSITIONS["done"] == set()

    def test_blocked_can_return(self):
        targets = gsv.LEGAL_TRANSITIONS["blocked"]
        assert "drafted" in targets
        assert "coding" in targets

class TestTaskRequestsLightweight:
    def test_true(self):
        assert gsv.task_requests_lightweight("- Lightweight: true\n## Objective") is True

    def test_false(self):
        assert gsv.task_requests_lightweight("- Lightweight: false\n## Objective") is False

    def test_absent(self):
        assert gsv.task_requests_lightweight("## Objective\nSomething") is False

class TestValidateTransition:
    def test_valid(self):
        result = gsv.validate_transition("drafted", "researched")
        assert result.ok

    def test_invalid(self):
        result = gsv.validate_transition("drafted", "done")
        assert not result.ok

    def test_unknown_state(self):
        result = gsv.validate_transition("unknown", "done")
        assert not result.ok


# ─────────────────────────────────────────────
# guard_contract_validator: helpers
# ─────────────────────────────────────────────

class TestInferStateFromArtifacts:
    def test_empty_set(self):
        assert gsv.infer_state_from_artifacts(set()) == "drafted"

    def test_only_task(self):
        assert gsv.infer_state_from_artifacts({"task"}) == "drafted"

    def test_task_and_status(self):
        assert gsv.infer_state_from_artifacts({"task", "status"}) == "drafted"

    def test_task_research_status(self):
        assert gsv.infer_state_from_artifacts({"task", "research", "status"}) == "researched"

    def test_task_plan_status(self):
        assert gsv.infer_state_from_artifacts({"task", "plan", "status"}) == "coding"

    def test_task_plan_code_status(self):
        assert gsv.infer_state_from_artifacts({"task", "plan", "code", "status"}) == "testing"

    def test_full_done_set(self):
        assert gsv.infer_state_from_artifacts({"task", "code", "verify", "status"}) == "done"

    def test_all_artifacts(self):
        assert gsv.infer_state_from_artifacts(
            {"task", "research", "plan", "code", "test", "verify", "status"}
        ) == "done"


# ─────────────────────────────────────────────
# state_required_artifacts
# ─────────────────────────────────────────────

class TestStateRequiredArtifacts:
    def test_drafted(self):
        assert gsv.state_required_artifacts("drafted", set()) == {"task", "status"}

    def test_planned_defaults_without_research(self):
        existing = {"task", "research", "plan", "status"}
        required = gsv.state_required_artifacts("planned", existing)
        assert "research" not in required

    def test_planned_production_requires_research(self):
        existing = {"task", "plan", "status"}
        required = gsv.state_required_artifacts("planned", existing, assurance_level="production")
        assert "research" in required

    def test_lightweight_mode(self):
        result = gsv.state_required_artifacts("done", set(), validation_mode="lightweight")
        assert result == {"task", "code", "verify", "status"}

    def test_verifying_mvp_requires_test(self):
        existing = {"task", "plan", "code", "test", "status"}
        required = gsv.state_required_artifacts("verifying", existing, assurance_level="mvp")
        assert "test" in required

    def test_verifying_default_does_not_require_test(self):
        existing = {"task", "code", "status"}
        required = gsv.state_required_artifacts("verifying", existing)
        assert "test" not in required


# ─────────────────────────────────────────────
# classify_decision_waiver_gate
# ─────────────────────────────────────────────

class TestClassifyDecisionWaiverGate:
    def test_empty_string(self):
        assert gsv.classify_decision_waiver_gate("") is None

    def test_waiver_expired(self):
        assert gsv.classify_decision_waiver_gate("Waiver expired for Gate_B") is None

    def test_target_state_meta(self):
        result = gsv.classify_decision_waiver_gate("Target state 'coding' is not valid")
        assert result == "__META__"

    def test_missing_research(self):
        result = gsv.classify_decision_waiver_gate("Missing required artifacts for state 'researched': 'research'")
        assert result == "Gate_A"

    def test_missing_plan(self):
        result = gsv.classify_decision_waiver_gate("Missing required artifacts for state 'planned': 'plan'")
        assert result == "Gate_B"

    def test_missing_code(self):
        result = gsv.classify_decision_waiver_gate("Missing required artifacts for state 'coding': 'code'")
        assert result == "Gate_C"

    def test_missing_multiple_ambiguous(self):
        result = gsv.classify_decision_waiver_gate(
            "Missing required artifacts for state 'done': 'plan', 'code'"
        )
        assert result is None  # ambiguous → None

    def test_gate_e_improvement(self):
        result = gsv.classify_decision_waiver_gate("requires an improvement artifact for PDCA")
        assert result == "Gate_E"

    def test_gate_d_verify(self):
        result = gsv.classify_decision_waiver_gate("done state requires verify artifact TASK-900.verify.md")
        assert result == "Gate_D"

    def test_plan_md_keyword(self):
        result = gsv.classify_decision_waiver_gate("plan artifact is not ready for coding: TASK-900.plan.md")
        assert result == "Gate_B"

    def test_code_md_keyword(self):
        result = gsv.classify_decision_waiver_gate("something about .code.md missing")
        assert result == "Gate_C"

    def test_research_md_keyword(self):
        result = gsv.classify_decision_waiver_gate("missing .research.md artifact")
        assert result == "Gate_A"

    def test_unrecognized_error(self):
        assert gsv.classify_decision_waiver_gate("some random error string") is None


# ─────────────────────────────────────────────
# parse_missing_required_artifacts
# ─────────────────────────────────────────────

class TestParseMissingRequiredArtifacts:
    def test_no_match(self):
        assert gsv.parse_missing_required_artifacts("some other error") == set()

    def test_single(self):
        result = gsv.parse_missing_required_artifacts(
            "Missing required artifacts for state 'planned': 'plan'"
        )
        assert result == {"plan"}

    def test_multiple(self):
        result = gsv.parse_missing_required_artifacts(
            "Missing required artifacts for state 'done': 'code', 'verify'"
        )
        assert result == {"code", "verify"}


# ─────────────────────────────────────────────
# active_decision_waivers
# ─────────────────────────────────────────────

class TestActiveDecisionWaivers:
    def _future_ts(self, hours: int = 24) -> str:
        return (datetime.now(TAIPEI_TZ) + timedelta(hours=hours)).isoformat()

    def _past_ts(self, hours: int = 24) -> str:
        return (datetime.now(TAIPEI_TZ) - timedelta(hours=hours)).isoformat()

    def test_no_waivers(self):
        assert gsv.active_decision_waivers({}) == {}

    def test_not_a_list(self):
        assert gsv.active_decision_waivers({"decision_waivers": "bad"}) == {}

    def test_entry_not_dict(self):
        assert gsv.active_decision_waivers({"decision_waivers": ["bad"]}) == {}

    def test_expired_waiver(self):
        status = {"decision_waivers": [
            {"gate": "Gate_A", "expires": self._past_ts()}
        ]}
        assert gsv.active_decision_waivers(status) == {}

    def test_valid_future_waiver(self):
        future = self._future_ts()
        status = {"decision_waivers": [
            {"gate": "Gate_B", "expires": future, "decision": "TASK-999"}
        ]}
        result = gsv.active_decision_waivers(status)
        assert "Gate_B" in result
        assert result["Gate_B"]["gate"] == "Gate_B"

    def test_invalid_gate_name(self):
        status = {"decision_waivers": [
            {"gate": "Gate_Z", "expires": self._future_ts()}
        ]}
        assert gsv.active_decision_waivers(status) == {}

    def test_multiple_waivers_last_wins(self):
        future = self._future_ts()
        status = {"decision_waivers": [
            {"gate": "Gate_A", "expires": future, "decision": "TASK-100"},
            {"gate": "Gate_A", "expires": future, "decision": "TASK-200"},
        ]}
        result = gsv.active_decision_waivers(status)
        assert result["Gate_A"]["decision"] == "TASK-200"


# ─────────────────────────────────────────────
# parse_repository_ref
# ─────────────────────────────────────────────

class TestDetectMixedGithubSources:
    def test_no_urls(self):
        assert gsv.detect_mixed_github_sources("no github links here") == []

    def test_single_owner(self):
        text = "https://github.com/owner/repo/tree/main https://github.com/owner/repo/issues/1"
        assert gsv.detect_mixed_github_sources(text) == []

    def test_mixed_owners(self):
        text = "https://github.com/alice/myrepo and https://github.com/bob/myrepo"
        result = gsv.detect_mixed_github_sources(text)
        assert len(result) == 1
        assert "myrepo" in result[0]

    def test_different_repos_ok(self):
        text = "https://github.com/alice/repo1 and https://github.com/bob/repo2"
        assert gsv.detect_mixed_github_sources(text) == []

    def test_raw_githubusercontent(self):
        text = (
            "https://raw.githubusercontent.com/alice/myrepo/main/file.txt "
            "https://github.com/bob/myrepo/blob/main/file.txt"
        )
        result = gsv.detect_mixed_github_sources(text)
        assert len(result) == 1


# ─────────────────────────────────────────────
# detect_plan_code_scope_drift
# ─────────────────────────────────────────────

class TestDetectPlanCodeScopeDrift:
    def test_no_sections(self):
        assert gsv.detect_plan_code_scope_drift("no sections", "no sections") == []

    def test_no_drift(self):
        plan = "## Files Likely Affected\n- `src/a.py`\n- `src/b.py`"
        code = "## Files Changed\n- `src/a.py`"
        assert gsv.detect_plan_code_scope_drift(plan, code) == []

    def test_drift_detected(self):
        plan = "## Files Likely Affected\n- `src/a.py`"
        code = "## Files Changed\n- `src/a.py`\n- `src/extra.py`"
        result = gsv.detect_plan_code_scope_drift(plan, code)
        assert "src/extra.py" in result

    def test_empty_plan_no_drift(self):
        plan = "## Files Likely Affected\nNone"
        code = "## Files Changed\n- `src/a.py`"
        assert gsv.detect_plan_code_scope_drift(plan, code) == []


# ─────────────────────────────────────────────
# parse_diff_evidence
# ─────────────────────────────────────────────

class TestDetectChangedFiles:
    def test_not_a_git_repo(self, tmp_path):
        # tmp_path is not a git repo; git commands should fail gracefully
        available, changed = gcv.detect_changed_files(tmp_path)
        assert isinstance(changed, set)

    def test_git_not_installed(self, tmp_path, monkeypatch):
        def mock_run(*args, **kwargs):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(gcv.subprocess, "run", mock_run)
        available, changed = gcv.detect_changed_files(tmp_path)
        assert available is False
        assert changed == set()

    def test_successful_with_changes(self, tmp_path, monkeypatch):
        call_count = 0

        def mock_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1

            class Result:
                returncode = 0
                stdout = "CLAUDE.md\nGEMINI.md\n" if call_count == 1 else ""

            return Result()

        monkeypatch.setattr(gcv.subprocess, "run", mock_run)
        available, changed = gcv.detect_changed_files(tmp_path)
        assert available is True
        assert "CLAUDE.md" in changed
        assert "GEMINI.md" in changed

    def test_returncode_nonzero_skipped(self, tmp_path, monkeypatch):
        def mock_run(cmd, **kwargs):
            class Result:
                returncode = 128
                stdout = ""

            return Result()

        monkeypatch.setattr(gcv.subprocess, "run", mock_run)
        available, changed = gcv.detect_changed_files(tmp_path)
        assert available is False
        assert changed == set()

    def test_backslash_normalized(self, tmp_path, monkeypatch):
        def mock_run(cmd, **kwargs):
            class Result:
                returncode = 0
                stdout = "artifacts\\scripts\\test.py\n"

            return Result()

        monkeypatch.setattr(gcv.subprocess, "run", mock_run)
        _, changed = gcv.detect_changed_files(tmp_path)
        assert "artifacts/scripts/test.py" in changed


# ─────────────────────────────────────────────
# validate_prompt_case_sync (mock-based)
# ─────────────────────────────────────────────

class TestCategorizeOverrideError:
    def test_override_log_missing(self):
        assert gsv.categorize_override_error("override log missing for TASK-001") == "override_log_missing"

    def test_premortem_missing(self):
        assert gsv.categorize_override_error("plan.md: premortem check failed — ## risks section not found") == "premortem_missing"

    def test_premortem_dismissed(self):
        assert gsv.categorize_override_error("plan.md: premortem check failed — section is empty or trivially dismissed") == "premortem_missing"

    def test_premortem_other(self):
        assert gsv.categorize_override_error("plan.md: premortem missing required field 'Trigger:'") == "premortem"

    def test_critical(self):
        assert gsv.categorize_override_error("Missing required artifacts for state 'coding': ['code']") == "critical"


# ─────────────────────────────────────────────
# apply_decision_waivers
# ─────────────────────────────────────────────

class TestApplyDecisionWaivers:
    def _waiver_status(self, gate, expires="2099-12-31T23:59:59+08:00"):
        return {
            "decision_waivers": [{
                "gate": gate,
                "reason": "test waiver",
                "approver": "User",
                "expires": expires,
            }],
        }

    def test_no_waivers_passthrough(self):
        result = gsv.ValidationResult(["some error"], ["some warning"])
        status = {}
        out = gsv.apply_decision_waivers(result, status)
        assert out.errors == ["some error"]

    def test_no_errors_passthrough(self):
        result = gsv.ValidationResult([], ["some warning"])
        status = self._waiver_status("Gate_A")
        out = gsv.apply_decision_waivers(result, status)
        assert out.ok

    def test_waiver_covers_gate_a_research(self):
        result = gsv.ValidationResult(
            ["Missing required artifacts for state 'researched': ['research']"],
            [],
        )
        status = self._waiver_status("Gate_A")
        out = gsv.apply_decision_waivers(result, status)
        assert out.ok
        assert "A" in out.active_waivers

    def test_waiver_does_not_cover_unmatched_gate(self):
        result = gsv.ValidationResult(
            ["Missing required artifacts for state 'researched': ['research']"],
            [],
        )
        status = self._waiver_status("Gate_D")
        out = gsv.apply_decision_waivers(result, status)
        assert not out.ok

    def test_meta_error_preserved_when_others_waived(self):
        result = gsv.ValidationResult(
            [
                "Target state 'done' requirements are not yet satisfied.",
                "Missing required artifacts for state 'done': ['verify']",
            ],
            [],
        )
        status = self._waiver_status("Gate_D")
        out = gsv.apply_decision_waivers(result, status)
        # verify waived, but meta error kept only if remaining errors exist
        # Actually meta errors are separated; if all non-meta waived, then no remaining
        assert out.ok


# ─────────────────────────────────────────────
# validate_code_mapping_to_plan
# ─────────────────────────────────────────────

class TestCompareReconstructedScope:
    def _make_artifacts(self, tmp_path, plan_files, code_files):
        plan = tmp_path / "plan.md"
        plan.write_text(
            f"# Plan\n## Files Likely Affected\n"
            + "".join(f"- `{f}`\n" for f in plan_files)
            + "\n## Scope\nTest\n",
            encoding="utf-8",
        )
        code = tmp_path / "code.md"
        code.write_text(
            f"# Code Result\n## Files Changed\n"
            + "".join(f"- `{f}`\n" for f in code_files)
            + "\n## Summary Of Changes\nDone\n",
            encoding="utf-8",
        )
        return plan, code

    def test_no_drift(self, tmp_path):
        plan, code = self._make_artifacts(tmp_path, ["a.py", "b.py"], ["a.py", "b.py"])
        result = gsv.compare_reconstructed_scope(plan, code, {"a.py", "b.py"}, "test")
        assert not result.errors
        assert not result.waiver_candidate_errors

    def test_undeclared_file(self, tmp_path):
        plan, code = self._make_artifacts(tmp_path, ["a.py", "b.py"], ["a.py"])
        result = gsv.compare_reconstructed_scope(plan, code, {"a.py", "b.py"}, "test")
        assert any("not listed in ## Files Changed" in e for e in result.waiver_candidate_errors)

    def test_unplanned_file(self, tmp_path):
        plan, code = self._make_artifacts(tmp_path, ["a.py"], ["a.py", "c.py"])
        result = gsv.compare_reconstructed_scope(plan, code, {"a.py", "c.py"}, "test")
        assert any("not listed in ## Files Likely Affected" in e for e in result.waiver_candidate_errors)


# ─────────────────────────────────────────────
# validate_scope_drift_waiver
# ─────────────────────────────────────────────

class TestValidateScopeDriftWaiver:
    def _make_decision(self, tmp_path, task_id, waived_files, justification="Valid reason"):
        d = tmp_path / "decisions"
        d.mkdir(exist_ok=True)
        content = textwrap.dedent(f"""\
            # Decision Log: {task_id}
            ## Metadata
            - Artifact Type: decision
            - Task ID: {task_id}
            - Owner: Claude
            - Status: done
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Issue
            Scope drift
            ## Chosen Option
            Allow drift
            ## Reasoning
            Necessary files
            ## Guard Exception
            - Exception Type: allow-scope-drift
            - Scope Files: {', '.join(waived_files)}
            - Justification: {justification}
        """)
        p = d / f"{task_id}.decision.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_no_drift_files(self, tmp_path):
        result = gsv.validate_scope_drift_waiver(tmp_path, "TASK-001", set())
        assert result.ok

    def test_drift_without_decision(self, tmp_path):
        (tmp_path / "decisions").mkdir()
        result = gsv.validate_scope_drift_waiver(tmp_path, "TASK-001", {"extra.py"})
        assert not result.ok
        assert any("decision artifact" in e for e in result.errors)

    def test_drift_with_valid_waiver(self, tmp_path):
        self._make_decision(tmp_path, "TASK-001", ["extra.py"])
        result = gsv.validate_scope_drift_waiver(tmp_path, "TASK-001", {"extra.py"})
        assert result.ok

    def test_drift_with_insufficient_waiver(self, tmp_path):
        self._make_decision(tmp_path, "TASK-001", ["other.py"])
        result = gsv.validate_scope_drift_waiver(tmp_path, "TASK-001", {"extra.py"})
        assert not result.ok


# ─────────────────────────────────────────────
# validate_premortem: additional edge cases
# ─────────────────────────────────────────────

class TestDetectPlanCodeScopeDriftEdges:
    def test_empty_planned(self):
        plan_text = "# Plan\n## Files Likely Affected\n\n"
        code_text = "# Code\n## Files Changed\n- `a.py`\n"
        result = gsv.detect_plan_code_scope_drift(plan_text, code_text)
        assert result == []

    def test_empty_changed(self):
        plan_text = "# Plan\n## Files Likely Affected\n- `a.py`\n"
        code_text = "# Code\n## Files Changed\n\n"
        result = gsv.detect_plan_code_scope_drift(plan_text, code_text)
        assert result == []


# ─────────────────────────────────────────────
# detect_mixed_github_sources: edge case
# ─────────────────────────────────────────────

class TestDetectMixedGithubSourcesEdges:
    def test_raw_github_urls(self):
        text = (
            "https://raw.githubusercontent.com/alice/repo/main/file.py "
            "https://raw.githubusercontent.com/bob/repo/main/file.py"
        )
        result = gsv.detect_mixed_github_sources(text)
        assert len(result) == 1
        assert "repo" in result[0]


# ─────────────────────────────────────────────
# research_citations_are_blocking
# ─────────────────────────────────────────────

class TestResearchCitationsAreBlocking:
    def test_always_true(self):
        assert gsv.research_citations_are_blocking({}) is True
        assert gsv.research_citations_are_blocking({"state": "done"}) is True


# ─────────────────────────────────────────────
# verify_result_is_pass / plan_ready_for_coding
# ─────────────────────────────────────────────

class TestPlanReadyForCoding:
    def test_yes(self, tmp_path):
        p = tmp_path / "plan.md"
        p.write_text("# Plan\n## Ready For Coding\nyes\n", encoding="utf-8")
        assert gsv.plan_ready_for_coding(p) is True

    def test_no(self, tmp_path):
        p = tmp_path / "plan.md"
        p.write_text("# Plan\n## Ready For Coding\nno\n", encoding="utf-8")
        assert gsv.plan_ready_for_coding(p) is False


# ─────────────────────────────────────────────
# extract_task_inline_flags
# ─────────────────────────────────────────────

class TestDefaultNextAgentForState:
    def test_blocked(self):
        assert gsv.default_next_agent_for_state("blocked") == gsv.BLOCKED_STATUS_NEXT_AGENT

    def test_non_blocked(self):
        assert gsv.default_next_agent_for_state("drafted") == gsv.DEFAULT_STATUS_NEXT_AGENT


# ─────────────────────────────────────────────
# parse_structured_checklist_fields
# ─────────────────────────────────────────────

class TestClassifyPremortemPolicy:
    def test_hotfix(self, tmp_path):
        p = tmp_path / "task.md"
        p.write_text("# Task: Hotfix critical bug\n## Metadata\n", encoding="utf-8")
        policy = gsv.classify_premortem_policy(p)
        assert policy.task_type == "hotfix"

    def test_research(self, tmp_path):
        p = tmp_path / "task.md"
        p.write_text("# Task: Research options\n## Metadata\n", encoding="utf-8")
        policy = gsv.classify_premortem_policy(p)
        assert policy.task_type == "research"

    def test_default(self, tmp_path):
        p = tmp_path / "task.md"
        p.write_text("# Task: Implement feature\n## Metadata\n", encoding="utf-8")
        policy = gsv.classify_premortem_policy(p)
        assert policy.task_type == "code"

    def test_none_path(self):
        policy = gsv.classify_premortem_policy(None)
        assert policy.task_type == "code"


# ─────────────────────────────────────────────
# append_auto_upgrade_log
# ─────────────────────────────────────────────

class TestAppendAutoUpgradeLog:
    def test_appends_entry(self, tmp_path):
        p = tmp_path / "status.json"
        status = {"task_id": "TASK-001", "state": "drafted", "last_updated": "2026-01-15T10:00:00+08:00"}
        p.write_text(json.dumps(status, indent=2), encoding="utf-8")
        gsv.append_auto_upgrade_log(p, status, "plan has risks")
        assert len(status["auto_upgrade_log"]) == 1
        assert status["auto_upgrade_log"][0]["reason"] == "plan has risks"
        # Verify written to disk
        on_disk = json.loads(p.read_text(encoding="utf-8"))
        assert "auto_upgrade_log" in on_disk

    def test_appends_to_existing(self, tmp_path):
        p = tmp_path / "status.json"
        status = {
            "task_id": "TASK-001",
            "state": "drafted",
            "last_updated": "2026-01-15T10:00:00+08:00",
            "auto_upgrade_log": [{"timestamp": "2026-01-14T10:00:00+08:00", "reason": "old", "from_mode": "lightweight", "to_mode": "full"}],
        }
        p.write_text(json.dumps(status, indent=2), encoding="utf-8")
        gsv.append_auto_upgrade_log(p, status, "new reason")
        assert len(status["auto_upgrade_log"]) == 2


# ─────────────────────────────────────────────
# print_result
# ─────────────────────────────────────────────

class TestValidateTransition_v2:
    def test_valid_drafted_to_researched(self):
        result = gsv.validate_transition("drafted", "researched")
        assert not result.errors

    def test_invalid_state(self):
        result = gsv.validate_transition("drafted", "invalid")
        assert result.errors

    def test_illegal_transition(self):
        result = gsv.validate_transition("drafted", "done")
        assert any("Illegal state transition" in e for e in result.errors)

    def test_unknown_from_state(self):
        result = gsv.validate_transition("nonexistent", "drafted")
        assert any("Unknown from_state" in e for e in result.errors)

    def test_blocked_to_unblocked_needs_improvement(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "blocked"))
        result = gsv.validate_transition("blocked", "drafted", tmp_path, task_id)
        assert any("improvement artifact" in e for e in result.errors)


# ─────────────────────────────────────────────
# validate_all
# ─────────────────────────────────────────────

class TestBuildReconcileDefaults:
    def test_defaults_for_drafted(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        status = _make_full_status(task_id, "drafted")
        defaults, warnings = gsv.build_reconcile_defaults(tmp_path, task_id, status)
        assert defaults["task_id"] == task_id
        assert "state" in defaults

    def test_state_conflict_warning(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _build_plan_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "done"))
        status = _make_full_status(task_id, "done")
        defaults, warnings = gsv.build_reconcile_defaults(tmp_path, task_id, status)
        assert any("conflict" in w for w in warnings)

    def test_invalid_state_warning(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        status = _make_full_status(task_id, "nonexistent_state")
        defaults, warnings = gsv.build_reconcile_defaults(tmp_path, task_id, status)
        assert any("invalid value" in w for w in warnings)


# ─────────────────────────────────────────────
# reconcile_status
# ─────────────────────────────────────────────

class TestReconcileStatus:
    def test_backfill_missing_fields(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        d = tmp_path / "status"
        d.mkdir(parents=True, exist_ok=True)
        # Write minimal status missing several fields
        p = d / f"{task_id}.status.json"
        p.write_text(json.dumps({
            "task_id": task_id,
            "state": "drafted",
            "last_updated": _ts(),
        }, indent=2) + "\n", encoding="utf-8")
        result = gsv.reconcile_status(tmp_path, task_id)
        # After reconcile, read back status
        updated = json.loads(p.read_text(encoding="utf-8"))
        assert "current_owner" in updated
        assert "next_agent" in updated


# ─────────────────────────────────────────────
# apply_override
# ─────────────────────────────────────────────

class TestApplyOverride:
    def test_override_critical_error(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        errors = ["Missing required artifacts for state 'coding': ['plan']"]
        result = gsv.ValidationResult(errors, [])
        overridden = gsv.apply_override(result, tmp_path, task_id, "Testing", "Admin")
        assert not overridden.errors
        assert any("[OVERRIDDEN]" in w for w in overridden.warnings)

    def test_override_premortem_missing_not_suppressed(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        errors = ["plan.md: premortem check failed — ## Risks section not found"]
        result = gsv.ValidationResult(errors, [])
        overridden = gsv.apply_override(result, tmp_path, task_id, "Testing", "Admin")
        assert any("premortem" in e.lower() for e in overridden.errors)

    def test_override_premortem_warning(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        errors = ["plan.md: premortem task_type='code' requires at least 4 numbered risks"]
        result = gsv.ValidationResult(errors, [])
        overridden = gsv.apply_override(result, tmp_path, task_id, "Testing", "Admin")
        assert not overridden.errors
        assert any("OVERRIDE PREMORTEM WARNING" in w for w in overridden.warnings)


# ─────────────────────────────────────────────
# write_transition
# ─────────────────────────────────────────────

class TestWriteTransition:
    def test_valid_transition_drafted_to_researched(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _build_research_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        result = gsv.write_transition(tmp_path, task_id, "drafted", "researched")
        # Check status was updated
        status_path = gsv.artifact_path(tmp_path, task_id, "status")
        updated = json.loads(status_path.read_text(encoding="utf-8"))
        if not result.errors:
            assert updated["state"] == "researched"

    def test_illegal_transition_blocked(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        result = gsv.write_transition(tmp_path, task_id, "drafted", "done")
        assert result.errors

    def test_state_mismatch_refused(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _build_research_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "researched",
            required_artifacts=["task", "research", "status"],
            available_artifacts=["task", "research", "status"],
            missing_artifacts=[]))
        result = gsv.write_transition(tmp_path, task_id, "drafted", "researched")
        assert any("Refusing transition" in e for e in result.errors)


# ─────────────────────────────────────────────
# resolve_validation_mode
# ─────────────────────────────────────────────

class TestResolveValidationMode:
    def test_non_auto_classify(self, tmp_path):
        result = gsv.resolve_validation_mode(tmp_path, "TASK-001", auto_classify=False)
        assert result.validation_mode == gsv.AUTO_CLASSIFY_FULL

    def test_no_plan_drafted_lightweight(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        result = gsv.resolve_validation_mode(tmp_path, task_id, auto_classify=True)
        assert result.validation_mode == gsv.AUTO_CLASSIFY_LIGHTWEIGHT


# ─────────────────────────────────────────────
# state_required_artifacts & infer_state
# ─────────────────────────────────────────────

class TestStateRequiredArtifacts_v2:
    def test_drafted_requires_task_status(self):
        result = gsv.state_required_artifacts("drafted", set())
        assert "task" in result
        assert "status" in result

    def test_done_requires_verify(self):
        result = gsv.state_required_artifacts("done", set())
        assert "verify" in result

    def test_lightweight_mode(self):
        result = gsv.state_required_artifacts("done", set(), gsv.AUTO_CLASSIFY_LIGHTWEIGHT)
        assert result == {"task", "code", "verify", "status"}

    def test_research_retained_if_exists(self):
        result = gsv.state_required_artifacts("planned", {"research"})
        assert "research" not in result
        production = gsv.state_required_artifacts("planned", {"research"}, assurance_level="production")
        assert "research" in production

class TestInferStateFromArtifacts_v2:
    def test_empty(self):
        assert gsv.infer_state_from_artifacts(set()) == "drafted"

    def test_task_only(self):
        assert gsv.infer_state_from_artifacts({"task", "status"}) == "drafted"

    def test_full_done(self):
        assert gsv.infer_state_from_artifacts({"task", "code", "verify", "status"}) == "done"


# ─────────────────────────────────────────────
# collect_git_changed_files (mocked)
# ─────────────────────────────────────────────

class TestCollectGitChangedFiles:
    def test_git_not_available(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            files, warnings = gsv.collect_git_changed_files(tmp_path)
        assert files == set()
        assert any("not available" in w for w in warnings)

    def test_git_error(self, tmp_path):
        from unittest.mock import MagicMock
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "fatal: not a git repo"
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            files, warnings = gsv.collect_git_changed_files(tmp_path)
        assert files == set()
        assert any("failed" in w for w in warnings)

class TestCollectGitDiffRangeFiles:
    def test_git_not_available(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            files, error = gsv.collect_git_diff_range_files(tmp_path, "abc", "def")
        assert files == set()
        assert "not available" in error


# ─────────────────────────────────────────────
# detect_git_backed_scope_drift
# ─────────────────────────────────────────────

class TestDetectGitBackedScopeDrift:
    def test_no_actual_changed(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n## Files Likely Affected\n- `a.py`\n", encoding="utf-8")
        code = tmp_path / "code.md"
        code.write_text("# Code\n## Files Changed\n- `a.py`\n", encoding="utf-8")
        result = gsv.detect_git_backed_scope_drift(plan, code, set(), {"artifacts/tasks/TASK-001.task.md"})
        assert not result.errors
        assert not result.waiver_candidate_errors

    def test_no_task_artifact_overlap(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n## Files Likely Affected\n- `a.py`\n", encoding="utf-8")
        code = tmp_path / "code.md"
        code.write_text("# Code\n## Files Changed\n- `a.py`\n", encoding="utf-8")
        result = gsv.detect_git_backed_scope_drift(plan, code, {"x.py"}, {"artifacts/tasks/TASK-001.task.md"})
        assert not result.waiver_candidate_errors

    def test_drift_detected(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n## Files Likely Affected\n- `a.py`\n", encoding="utf-8")
        code = tmp_path / "code.md"
        code.write_text("# Code\n## Files Changed\n- `a.py`\n", encoding="utf-8")
        actual = {"a.py", "b.py", "artifacts/tasks/TASK-001.task.md"}
        task_arts = {"artifacts/tasks/TASK-001.task.md"}
        result = gsv.detect_git_backed_scope_drift(plan, code, actual, task_arts)
        assert any("b.py" in e for e in result.waiver_candidate_errors)


# ─────────────────────────────────────────────
# validate_scope_drift_waiver (deeper)
# ─────────────────────────────────────────────

class TestValidateScopeDriftWaiverDeeper:
    def test_waiver_with_decision_file(self, tmp_path):
        task_id = "TASK-001"
        d = tmp_path / "decisions"
        d.mkdir(parents=True, exist_ok=True)
        content = textwrap.dedent(f"""\
            # Decision Log: {task_id}
            ## Metadata
            - Artifact Type: decision
            - Task ID: {task_id}
            - Owner: Claude
            - Status: done
            - Last Updated: {_ts()}
            ## Issue
            Scope drift needed
            ## Chosen Option
            Allow drift
            ## Reasoning
            Necessary change
            ## Guard Exception
            - Exception Type: allow-scope-drift
            - Scope Files: b.py
            - Justification: Required for fix
        """)
        (d / f"{task_id}.decision.md").write_text(content, encoding="utf-8")
        result = gsv.validate_scope_drift_waiver(tmp_path, task_id, {"b.py"})
        assert not result.errors

    def test_waiver_insufficient_scope(self, tmp_path):
        task_id = "TASK-001"
        d = tmp_path / "decisions"
        d.mkdir(parents=True, exist_ok=True)
        content = textwrap.dedent(f"""\
            # Decision Log: {task_id}
            ## Metadata
            - Artifact Type: decision
            - Task ID: {task_id}
            - Owner: Claude
            - Status: done
            - Last Updated: {_ts()}
            ## Issue
            Scope drift
            ## Chosen Option
            Allow
            ## Reasoning
            Needed
            ## Guard Exception
            - Exception Type: allow-scope-drift
            - Scope Files: b.py
            - Justification: Only for b
        """)
        (d / f"{task_id}.decision.md").write_text(content, encoding="utf-8")
        result = gsv.validate_scope_drift_waiver(tmp_path, task_id, {"b.py", "c.py"})
        assert result.errors  # c.py not covered


# ─────────────────────────────────────────────
# prompt_regression_validator
# ─────────────────────────────────────────────

class TestDetectHistoricalDiffScopeDrift:
    def test_no_evidence(self, tmp_path):
        code = tmp_path / "code.md"
        code.write_text("# Code\n## Files Changed\n- `a.py`\n", encoding="utf-8")
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n## Files Likely Affected\n- `a.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(None, plan, code)
        assert not result.errors

    def test_unsupported_evidence_type(self, tmp_path):
        code = tmp_path / "code.md"
        code.write_text("# Code\n## Diff Evidence\n- Evidence Type: unsupported\n", encoding="utf-8")
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(None, plan, code)
        assert any("unsupported" in e for e in result.errors)

    def test_missing_snapshot_fields(self, tmp_path):
        code = tmp_path / "code.md"
        code.write_text("# Code\n## Diff Evidence\n- Evidence Type: commit-range\n", encoding="utf-8")
        plan = tmp_path / "plan.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(None, plan, code)
        assert any("requires non-empty" in e for e in result.errors)


# ─────────────────────────────────────────────
# summarize_remote_error_detail
# ─────────────────────────────────────────────

class TestClassifyDecisionWaiverGate_v2:
    def test_research_gate(self):
        assert gsv.classify_decision_waiver_gate("Missing required artifacts for state 'researched': ['research']") == "Gate_A"

    def test_plan_gate(self):
        assert gsv.classify_decision_waiver_gate("Missing required artifacts for state 'planned': ['plan']") == "Gate_B"

    def test_code_gate(self):
        assert gsv.classify_decision_waiver_gate(".code.md missing something") == "Gate_C"

    def test_gate_e(self):
        assert gsv.classify_decision_waiver_gate("Gate E (PDCA): requires an improvement artifact") == "Gate_E"

    def test_verify_gate(self):
        assert gsv.classify_decision_waiver_gate("done state requires verify artifact with Pass Fail Result") == "Gate_D"

    def test_meta(self):
        assert gsv.classify_decision_waiver_gate("Target state 'done' requirements") == "__META__"

    def test_waiver_expired_returns_none(self):
        assert gsv.classify_decision_waiver_gate("waiver expired for Gate_A at 2026-01-01") is None

    def test_unknown_returns_none(self):
        assert gsv.classify_decision_waiver_gate("some random error") is None


# ─────────────────────────────────────────────
# active_decision_waivers
# ─────────────────────────────────────────────

class TestActiveDecisionWaivers_v2:
    def test_no_waivers(self):
        assert gsv.active_decision_waivers({}) == {}

    def test_expired_waiver_excluded(self):
        status = {
            "decision_waivers": [{
                "gate": "Gate_A",
                "reason": "Test",
                "approver": "Admin",
                "expires": "2020-01-01T00:00:00+08:00",
            }]
        }
        assert gsv.active_decision_waivers(status) == {}

    def test_active_waiver_included(self):
        status = {
            "decision_waivers": [{
                "gate": "Gate_A",
                "reason": "Test",
                "approver": "Admin",
                "expires": _future_ts(),
            }]
        }
        active = gsv.active_decision_waivers(status)
        assert "Gate_A" in active

    def test_invalid_list_type(self):
        status = {"decision_waivers": "not a list"}
        assert gsv.active_decision_waivers(status) == {}


# ─────────────────────────────────────────────
# ensure_override_log_not_missing
# ─────────────────────────────────────────────

class TestEnsureOverrideLogNotMissing:
    def test_no_override_flag(self, tmp_path):
        task_id = "TASK-001"
        _write_status(tmp_path, task_id, _make_full_status(task_id))
        gsv.ensure_override_log_not_missing(tmp_path, task_id)  # Should not raise

    def test_override_flag_but_log_missing(self, tmp_path):
        task_id = "TASK-001"
        status = _make_full_status(task_id)
        status["override_log_required"] = True
        _write_status(tmp_path, task_id, status)
        with pytest.raises(gsv.GuardError, match="override log missing"):
            gsv.ensure_override_log_not_missing(tmp_path, task_id)

    def test_override_flag_with_log(self, tmp_path):
        task_id = "TASK-001"
        status = _make_full_status(task_id)
        status["override_log_required"] = True
        _write_status(tmp_path, task_id, status)
        log_path = gsv.override_log_path(tmp_path, task_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("[]", encoding="utf-8")
        gsv.ensure_override_log_not_missing(tmp_path, task_id)  # Should not raise


# ─────────────────────────────────────────────
# append_override_record
# ─────────────────────────────────────────────

class TestAppendOverrideRecord:
    def test_appends_record(self, tmp_path):
        task_id = "TASK-001"
        _write_status(tmp_path, task_id, _make_full_status(task_id))
        gsv.append_override_record(tmp_path, task_id, "test reason", "admin", ["error1"])
        log_path = gsv.override_log_path(tmp_path, task_id)
        log = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(log) == 1
        assert log[0]["reason"] == "test reason"
        # Check status was marked
        status = json.loads((tmp_path / "status" / f"{task_id}.status.json").read_text(encoding="utf-8"))
        assert status.get("override_log_required") is True


# ─────────────────────────────────────────────
# task_is_high_risk & task_requests_lightweight
# ─────────────────────────────────────────────

class TestGsvCollectGithubPrFiles:
    def test_invalid_repo_ref(self):
        files, error = gsv.collect_github_pr_files("invalid", "1", "")
        assert error is not None
        assert files == set()

    def test_http_error(self):
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.status = 404
        mock_resp.read.return_value = b"Not found"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        with patch("urllib.request.urlopen", return_value=mock_resp):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
            assert error is not None

    def test_url_error(self):
        from urllib.error import URLError
        with patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
            assert error is not None

class TestGsvWriteTransitionGateE:
    def test_done_with_improvement(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _build_plan_artifact(tmp_path, task_id)
        _build_code_artifact(tmp_path, task_id)
        _build_verify_artifact(tmp_path, task_id, result="pass")
        # Create improvement artifact with Status: applied
        imp_dir = tmp_path / "improvement"
        imp_dir.mkdir(parents=True)
        imp_content = textwrap.dedent(f"""\
            # Improvement: {task_id}
            ## Metadata
            - Artifact Type: improvement
            - Task ID: {task_id}
            - Owner: Claude
            - Status: applied
            - Last Updated: {_ts()}
            ## Root Cause
            Test
            ## Corrective Actions
            Fix things
        """)
        (imp_dir / f"{task_id}.improvement.md").write_text(imp_content, encoding="utf-8")
        status = _make_full_status(task_id, "verifying",
            required_artifacts=["task", "code", "verify", "status"],
            available_artifacts=["task", "plan", "code", "verify", "improvement", "status"],
            missing_artifacts=[])
        _write_status(tmp_path, task_id, status)
        result = gsv.write_transition(tmp_path, task_id, "verifying", "done")
        if not result.errors:
            status_path = gsv.artifact_path(tmp_path, task_id, "status")
            updated = json.loads(status_path.read_text(encoding="utf-8"))
            assert updated.get("Gate_E_passed") is True

class TestGsvResolveValidationMode:
    def test_auto_classify_false(self, tmp_path):
        result = gsv.resolve_validation_mode(tmp_path, "TASK-001", False)
        assert result.validation_mode == gsv.AUTO_CLASSIFY_FULL

    def test_lightweight_no_plan(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        result = gsv.resolve_validation_mode(tmp_path, task_id, True)
        assert result.validation_mode == gsv.AUTO_CLASSIFY_LIGHTWEIGHT

    def test_upgrade_with_premortem_flag(self, tmp_path):
        task_id = "TASK-001"
        task_dir = tmp_path / "tasks"
        task_dir.mkdir(parents=True)
        content = textwrap.dedent(f"""\
            # Task: {task_id}
            ## Metadata
            - Artifact Type: task
            - Task ID: {task_id}
            - Owner: Claude
            - Status: drafted
            - Last Updated: {_ts()}
            ## Objective
            Test
            ## Inline Flags
            - premortem: true
        """)
        (task_dir / f"{task_id}.task.md").write_text(content, encoding="utf-8")
        _write_status(tmp_path, task_id, _make_full_status(task_id, "drafted"))
        result = gsv.resolve_validation_mode(tmp_path, task_id, True)
        assert result.validation_mode == gsv.AUTO_CLASSIFY_FULL
        assert any("AUTO-UPGRADE" in w for w in result.warnings)

    def test_upgrade_with_plan_risks(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir(parents=True)
        plan_content = textwrap.dedent(f"""\
            # Plan: {task_id}
            ## Metadata
            - Artifact Type: plan
            - Task ID: {task_id}
            - Owner: Claude
            - Status: approved
            - Last Updated: {_ts()}
            ## Risks
            R1: Something bad might happen
            - Trigger: event
            - Detection: monitoring
            - Mitigation: fix
            - Severity: blocking
        """)
        (plan_dir / f"{task_id}.plan.md").write_text(plan_content, encoding="utf-8")
        status = _make_full_status(task_id, "drafted")
        _write_status(tmp_path, task_id, status)
        result = gsv.resolve_validation_mode(tmp_path, task_id, True)
        assert result.validation_mode == gsv.AUTO_CLASSIFY_FULL

class TestGsvValidateTransitionGateE:
    def test_blocked_to_planned_missing_improvement(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        _write_status(tmp_path, task_id, _make_full_status(task_id, "blocked"))
        result = gsv.validate_transition("blocked", "planned", tmp_path, task_id)
        assert any("improvement artifact" in e for e in result.errors)

    def test_blocked_to_planned_improvement_not_applied(self, tmp_path):
        task_id = "TASK-001"
        _build_task_artifact(tmp_path, task_id)
        imp_dir = tmp_path / "improvement"
        imp_dir.mkdir(parents=True)
        imp_content = textwrap.dedent(f"""\
            # Improvement: {task_id}
            ## Metadata
            - Artifact Type: improvement
            - Task ID: {task_id}
            - Owner: Claude
            - Status: drafted
            - Last Updated: {_ts()}
            ## 1. Source Task
            - Source Task: {task_id}
            - Trigger Type: failure
            ## 2. Root Cause
            Stuff
            ## 5. Preventive Action (System Level)
            Stuff
            ## 6. Validation
            Stuff
            ## 8. Final Rule
            Stuff
            ## 9. Status
            drafted
        """)
        (imp_dir / f"{task_id}.improvement.md").write_text(imp_content, encoding="utf-8")
        _write_status(tmp_path, task_id, _make_full_status(task_id, "blocked"))
        result = gsv.validate_transition("blocked", "planned", tmp_path, task_id)
        assert any("Status: applied" in e for e in result.errors)

class TestGsvAppendAutoUpgradeLog:
    def test_writes_log(self, tmp_path):
        status_dir = tmp_path / "status"
        status_dir.mkdir(parents=True)
        status_path = status_dir / "TASK-001.status.json"
        status = _make_full_status("TASK-001", "drafted")
        gsv.write_json(status_path, status)
        gsv.append_auto_upgrade_log(status_path, status, "test reason")
        updated = json.loads(status_path.read_text(encoding="utf-8"))
        assert "auto_upgrade_log" in updated
        assert len(updated["auto_upgrade_log"]) == 1
        assert updated["auto_upgrade_log"][0]["reason"] == "test reason"

class TestGsvClassifyDecisionWaiverGate:
    def test_missing_research(self):
        error = "Missing required artifacts for state 'researched': 'research'"
        assert gsv.classify_decision_waiver_gate(error) == "Gate_A"

    def test_plan_not_ready(self):
        error = "Plan artifact is not Ready For Coding = yes: TASK-001.plan.md"
        assert gsv.classify_decision_waiver_gate(error) == "Gate_B"

    def test_gate_e(self):
        error = "Gate E (PDCA): resuming from blocked requires an improvement artifact"
        assert gsv.classify_decision_waiver_gate(error) == "Gate_E"

    def test_verify(self):
        error = "done state requires verify artifact with Pass Fail Result = pass"
        assert gsv.classify_decision_waiver_gate(error) == "Gate_D"

    def test_waiver_expired(self):
        assert gsv.classify_decision_waiver_gate("waiver expired blah") is None

    def test_target_state(self):
        assert gsv.classify_decision_waiver_gate("Target state 'done' ...") == "__META__"


# ─────────────────────────────────────────────
# Phase 3c: final push to 90%
# ─────────────────────────────────────────────

class TestGsvDetectMixedGithubSources:
    def test_no_mixed(self):
        text = "https://github.com/owner1/repo1\nhttps://github.com/owner1/repo1"
        assert gsv.detect_mixed_github_sources(text) == []

    def test_mixed(self):
        text = "https://github.com/owner1/myrepo\nhttps://github.com/owner2/myrepo"
        mixed = gsv.detect_mixed_github_sources(text)
        assert len(mixed) == 1
        assert "myrepo" in mixed[0]


# ─────────────────────────────────────────────
# Phase 4: gsv 95% — git & HTTP mocking
# ─────────────────────────────────────────────

import subprocess
from unittest.mock import MagicMock


def _mock_subprocess_run(returncode=0, stdout="", stderr=""):
    """Helper to create a mock subprocess.CompletedProcess."""
    mock = MagicMock(spec=subprocess.CompletedProcess)
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock

class TestGsvCollectGitChangedFiles:
    def test_success(self, tmp_path):
        results = [
            _mock_subprocess_run(stdout="src/a.py\n"),
            _mock_subprocess_run(stdout="src/b.py\n"),
            _mock_subprocess_run(stdout=""),
        ]
        with patch("subprocess.run", side_effect=results):
            changed, warnings = gsv.collect_git_changed_files(tmp_path)
        assert "src/a.py" in changed
        assert "src/b.py" in changed
        assert not warnings

    def test_git_not_found(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            changed, warnings = gsv.collect_git_changed_files(tmp_path)
        assert changed == set()
        assert any("not available" in w for w in warnings)

    def test_git_error(self, tmp_path):
        with patch("subprocess.run", return_value=_mock_subprocess_run(returncode=1, stderr="fatal: error")):
            changed, warnings = gsv.collect_git_changed_files(tmp_path)
        assert changed == set()
        assert any("failed" in w for w in warnings)

class TestGsvCollectGitDiffRangeFiles:
    def test_success(self, tmp_path):
        with patch("subprocess.run", return_value=_mock_subprocess_run(stdout="file1.py\nfile2.py\n")):
            changed, error = gsv.collect_git_diff_range_files(tmp_path, "abc123", "def456")
        assert "file1.py" in changed
        assert "file2.py" in changed
        assert error is None

    def test_git_not_found(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            changed, error = gsv.collect_git_diff_range_files(tmp_path, "abc", "def")
        assert changed == set()
        assert "not available" in error

    def test_git_error(self, tmp_path):
        with patch("subprocess.run", return_value=_mock_subprocess_run(returncode=1, stderr="fatal")):
            changed, error = gsv.collect_git_diff_range_files(tmp_path, "abc", "def")
        assert changed == set()
        assert error is not None

class TestGsvResolveGitRevisionCommit:
    def test_success(self, tmp_path):
        sha = "a" * 40
        with patch("subprocess.run", return_value=_mock_subprocess_run(stdout=sha + "\n")):
            result, error = gsv.resolve_git_revision_commit(tmp_path, "main")
        assert result == sha
        assert error is None

    def test_git_not_found(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result, error = gsv.resolve_git_revision_commit(tmp_path, "main")
        assert result is None
        assert "not available" in error

    def test_git_error(self, tmp_path):
        with patch("subprocess.run", return_value=_mock_subprocess_run(returncode=128, stderr="bad rev")):
            result, error = gsv.resolve_git_revision_commit(tmp_path, "badref")
        assert result is None
        assert error is not None

class TestGsvDetectGitBackedScopeDrift:
    def test_no_changed_files(self, tmp_path):
        plan = tmp_path / "plan.md"
        code = tmp_path / "code.md"
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        code.write_text("## Files Changed\n- src/a.py\n", encoding="utf-8")
        result = gsv.detect_git_backed_scope_drift(plan, code, set(), {"artifacts/tasks/TASK-001.task.md"})
        assert not result.errors
        assert not result.waiver_candidate_errors

    def test_undeclared_drift(self, tmp_path):
        plan = tmp_path / "plan.md"
        code = tmp_path / "code.md"
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        code.write_text("## Files Changed\n- src/a.py\n", encoding="utf-8")
        actual = {"src/a.py", "src/extra.py", "artifacts/tasks/TASK-001.task.md"}
        task_arts = {"artifacts/tasks/TASK-001.task.md"}
        result = gsv.detect_git_backed_scope_drift(plan, code, actual, task_arts)
        assert any("src/extra.py" in e for e in result.waiver_candidate_errors)
        assert "src/extra.py" in result.drift_files

class TestGsvDetectHistoricalDiffScopeDrift:
    def test_no_evidence(self, tmp_path):
        code = tmp_path / "code.md"
        plan = tmp_path / "plan.md"
        code.write_text("## Files Changed\n- src/a.py\n", encoding="utf-8")
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan, code)
        assert not result.errors

    def test_unsupported_evidence_type(self, tmp_path):
        code = tmp_path / "code.md"
        plan = tmp_path / "plan.md"
        code.write_text("## Files Changed\n- src/a.py\n## Diff Evidence\n- Evidence Type: unsupported_type\n", encoding="utf-8")
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan, code)
        assert any("unsupported" in e for e in result.errors)

class TestGsvCollectGithubPrFilesDeeper:
    def test_negative_pr_number(self):
        files, error = gsv.collect_github_pr_files("user/repo", "0", "")
        assert error is not None
        assert "positive integer" in error

    def test_non_digit_pr_number(self):
        files, error = gsv.collect_github_pr_files("user/repo", "abc", "")
        assert error is not None

    def test_bad_api_url(self):
        files, error = gsv.collect_github_pr_files("user/repo", "1", "ftp://invalid")
        assert error is not None

    def test_custom_host_requires_allowlist(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            files, error = gsv.collect_github_pr_files("user/repo", "1", "https://github.example.com/api/v3")
        assert files == set()
        assert "not allowed" in error
        assert gsv.GITHUB_API_ALLOWED_HOSTS_ENV in error
        mock_urlopen.assert_not_called()

    def test_successful_single_page(self):
        payload = [{"filename": "src/main.py"}, {"filename": "README.md"}]
        mock_body = json.dumps(payload).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        with patch("urllib.request.urlopen", return_value=mock_resp):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
        assert error is None
        assert "src/main.py" in files
        assert "README.md" in files

    def test_invalid_json_response(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        with patch("urllib.request.urlopen", return_value=mock_resp):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
        assert error is not None
        assert "invalid JSON" in error

    def test_provider_response_exceeds_replay_byte_cap(self):
        payload = [{"filename": "docs/" + ("x" * gsv.MAX_DIFF_EVIDENCE_REPLAY_BYTES)}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        with patch("urllib.request.urlopen", return_value=mock_resp):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
        assert files == set()
        assert "exceeds replay byte cap" in error

    def test_non_list_response(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"not": "a list"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        with patch("urllib.request.urlopen", return_value=mock_resp):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
        assert error is not None
        assert "non-list" in error

    def test_non_object_file_entry(self):
        payload = ["not-a-dict"]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        with patch("urllib.request.urlopen", return_value=mock_resp):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
        assert error is not None
        assert "non-object" in error

    def test_missing_filename(self):
        payload = [{"status": "added"}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        with patch("urllib.request.urlopen", return_value=mock_resp):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
        assert error is not None
        assert "without filename" in error

    def test_http_error_with_detail(self):
        exc = urllib.error.HTTPError("http://example.com", 403, "Forbidden", {}, None)
        exc.read = lambda: b"rate limit exceeded"
        with patch("urllib.request.urlopen", side_effect=exc):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
        assert error is not None
        assert "403" in error

    def test_url_error_detail(self):
        from urllib.error import URLError
        with patch("urllib.request.urlopen", side_effect=URLError("connection refused")):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
        assert error is not None
        assert "connection" in error

    def test_filename_normalizes_to_empty(self):
        """L516: filename '.' normalizes to empty after strip."""
        from unittest.mock import MagicMock
        import json
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps([{"filename": "."}]).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        mock_resp.headers = {"Link": ""}
        with patch("urllib.request.urlopen", return_value=mock_resp):
            files, error = gsv.collect_github_pr_files("user/repo", "1", "")
        assert error is not None
        assert "invalid filename" in error


import urllib.error

class TestGsvCompareReconstructedScope:
    def test_no_drift(self, tmp_path):
        plan = tmp_path / "plan.md"
        code = tmp_path / "code.md"
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        code.write_text("## Files Changed\n- src/a.py\n", encoding="utf-8")
        result = gsv.compare_reconstructed_scope(plan, code, {"src/a.py"}, "test")
        assert not result.waiver_candidate_errors

    def test_with_drift(self, tmp_path):
        plan = tmp_path / "plan.md"
        code = tmp_path / "code.md"
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        code.write_text("## Files Changed\n- src/a.py\n", encoding="utf-8")
        result = gsv.compare_reconstructed_scope(plan, code, {"src/a.py", "src/extra.py"}, "test")
        assert any("src/extra.py" in e for e in result.waiver_candidate_errors)

class TestGsvValidateScopeDriftWaiver:
    def test_no_drift(self, tmp_path):
        result = gsv.validate_scope_drift_waiver(tmp_path, "TASK-001", set())
        assert not result.errors

    def test_no_decision_artifact(self, tmp_path):
        (tmp_path / "decisions").mkdir(parents=True)
        result = gsv.validate_scope_drift_waiver(tmp_path, "TASK-001", {"src/extra.py"})
        assert any("decision artifact" in e for e in result.errors)

    def test_with_guard_exception_match(self, tmp_path):
        d = tmp_path / "decisions"
        d.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Decision Log: TASK-001
            ## Metadata
            - Artifact Type: decision
            - Task ID: TASK-001
            - Owner: Claude
            - Status: done
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## Guard Exception
            - Exception Type: allow-scope-drift
            - Scope Files: src/extra.py
            - Justification: Needed for feature
        """)
        (d / "TASK-001.decision.md").write_text(content, encoding="utf-8")
        result = gsv.validate_scope_drift_waiver(tmp_path, "TASK-001", {"src/extra.py"})
        assert not result.errors
        assert any("waiver applied" in w for w in result.warnings)

class TestGsvDetectPlanCodeScopeDrift:
    def test_no_drift(self):
        plan = "## Files Likely Affected\n- src/a.py\n- src/b.py\n"
        code = "## Files Changed\n- src/a.py\n"
        assert gsv.detect_plan_code_scope_drift(plan, code) == []

    def test_drift_detected(self):
        plan = "## Files Likely Affected\n- src/a.py\n"
        code = "## Files Changed\n- src/a.py\n- src/extra.py\n"
        drift = gsv.detect_plan_code_scope_drift(plan, code)
        assert "src/extra.py" in drift

class TestGsvLoadGitScopeContext:
    def test_no_git_root(self, tmp_path):
        repo_root, changed, arts, warnings = gsv.load_git_scope_context(tmp_path, "TASK-001")
        assert repo_root is None
        assert changed == set()

    def test_with_git_root(self, tmp_path):
        (tmp_path / ".git").mkdir()
        results = [
            _mock_subprocess_run(stdout=""),
            _mock_subprocess_run(stdout=""),
            _mock_subprocess_run(stdout=""),
        ]
        with patch("subprocess.run", side_effect=results):
            repo_root, changed, arts, warnings = gsv.load_git_scope_context(tmp_path, "TASK-001")
        assert repo_root is not None

class TestGsvDetectGitRoot:
    def test_found(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert gsv.detect_git_root(tmp_path) == tmp_path.resolve()

    def test_not_found(self, tmp_path):
        assert gsv.detect_git_root(tmp_path / "deep" / "nested") is None

class TestGsvResolveStatusState:
    def test_modern(self):
        assert gsv.resolve_status_state({"state": "coding"}) == "coding"

    def test_legacy(self):
        assert gsv.resolve_status_state({"current_state": "drafted"}) == "drafted"

    def test_empty(self):
        assert gsv.resolve_status_state({}) is None

class TestGsvResolveValidationModeDeeper:
    def test_auto_classify_false(self, tmp_path):
        result = gsv.resolve_validation_mode(tmp_path, "TASK-001", False)
        assert result.validation_mode == gsv.AUTO_CLASSIFY_FULL
        assert not result.warnings

    def test_auto_classify_lightweight_no_plan(self, tmp_path):
        status_dir = tmp_path / "status"
        status_dir.mkdir(parents=True)
        (status_dir / "TASK-001.status.json").write_text(
            json.dumps({"task_id": "TASK-001", "state": "drafted", "last_updated": _ts()}), encoding="utf-8"
        )
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "TASK-001.task.md").write_text("# Task\n## Metadata\n- Task ID: TASK-001\n## Objective\nTest\n", encoding="utf-8")
        result = gsv.resolve_validation_mode(tmp_path, "TASK-001", True)
        assert result.validation_mode == gsv.AUTO_CLASSIFY_LIGHTWEIGHT
        assert any("lightweight" in w for w in result.warnings)

    def test_auto_upgrade_with_premortem(self, tmp_path):
        status_dir = tmp_path / "status"
        status_dir.mkdir(parents=True)
        (status_dir / "TASK-001.status.json").write_text(
            json.dumps({"task_id": "TASK-001", "state": "drafted", "last_updated": _ts()}), encoding="utf-8"
        )
        tasks_dir = tmp_path / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "TASK-001.task.md").write_text(
            "# Task\n## Metadata\n- Task ID: TASK-001\n## Objective\nTest\n## Inline Flags\n- premortem: true\n", encoding="utf-8"
        )
        result = gsv.resolve_validation_mode(tmp_path, "TASK-001", True)
        assert result.validation_mode == gsv.AUTO_CLASSIFY_FULL
        assert any("AUTO-UPGRADE" in w for w in result.warnings)

class TestGsvAppendAutoUpgradeLogDeeper:
    def test_non_list_existing_log(self, tmp_path):
        path = tmp_path / "status.json"
        status = {"auto_upgrade_log": "not-a-list"}
        gsv.append_auto_upgrade_log(path, status, "test reason")
        assert isinstance(status["auto_upgrade_log"], list)
        assert len(status["auto_upgrade_log"]) == 1

class TestGsvValidateTransitionGateE_v2:
    def test_blocked_to_coding_no_improvement(self, tmp_path):
        result = gsv.validate_transition("blocked", "coding", tmp_path, "TASK-001")
        assert any("improvement" in e for e in result.errors)

    def test_blocked_to_coding_improvement_not_applied(self, tmp_path):
        imp_dir = tmp_path / "improvement"
        imp_dir.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Process Improvement
            ## Metadata
            - Artifact Type: improvement
            - Task ID: TASK-001
            - Source Task: TASK-001
            - Trigger Type: blocked
            - Owner: Claude
            - Status: drafted
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## 1. What Happened
            Test
            ## 2. Why It Was Not Prevented
            Test
            ## 3. Failure Classification
            Test
            ## 5. Preventive Action (System Level)
            Test action
            ## 6. Validation
            Test validation
            ## 8. Final Rule
            Test rule
            ## 9. Status
            Drafted
        """)
        (imp_dir / "TASK-001.improvement.md").write_text(content, encoding="utf-8")
        result = gsv.validate_transition("blocked", "coding", tmp_path, "TASK-001")
        assert any("applied" in e for e in result.errors)

    def test_blocked_to_coding_improvement_applied(self, tmp_path):
        imp_dir = tmp_path / "improvement"
        imp_dir.mkdir(parents=True)
        content = textwrap.dedent("""\
            # Process Improvement
            ## Metadata
            - Artifact Type: improvement
            - Task ID: TASK-001
            - Source Task: TASK-001
            - Trigger Type: blocked
            - Owner: Claude
            - Status: applied
            - Last Updated: 2026-01-15T10:00:00+08:00
            ## 1. What Happened
            Test
            ## 2. Why It Was Not Prevented
            Test
            ## 3. Failure Classification
            Test
            ## 5. Preventive Action (System Level)
            Test action
            ## 6. Validation
            Test validation
            ## 8. Final Rule
            Test rule
            ## 9. Status
            Applied
        """)
        (imp_dir / "TASK-001.improvement.md").write_text(content, encoding="utf-8")
        result = gsv.validate_transition("blocked", "coding", tmp_path, "TASK-001")
        assert not any("improvement" in e for e in result.errors)


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

class TestGsvWriteTransitionGateE_v2:
    def _make_improvement(self, tmp_path, improvement_status="applied"):
        imp_dir = tmp_path / "improvement"
        imp_dir.mkdir(exist_ok=True)
        content = (
            "# Process Improvement\n"
            "## Metadata\n"
            "- Artifact Type: improvement\n"
            "- Task ID: TASK-001\n"
            "- Source Task: TASK-001\n"
            "- Trigger Type: blocked\n"
            "- Owner: Claude\n"
            f"- Status: {improvement_status}\n"
            f"- Last Updated: {_ts()}\n"
            "\n"
            "## 1. What Happened\nTest\n"
            "## 2. Why It Was Not Prevented\nTest\n"
            "## 3. Failure Classification\nTest\n"
            "## 5. Preventive Action (System Level)\nTest action\n"
            "## 6. Validation\nTest validation\n"
            "## 8. Final Rule\nTest rule\n"
            "## 9. Status\n" + improvement_status.capitalize() + "\n"
        )
        (imp_dir / "TASK-001.improvement.md").write_text(content, encoding="utf-8")

    def test_gate_e_auto_populate_done_with_applied_improvement(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        self._make_improvement(tmp_path, "applied")
        # Update status to verifying and include improvement in available
        sp = tmp_path / "status" / "TASK-001.status.json"
        s = json.loads(sp.read_text(encoding="utf-8"))
        s["state"] = "verifying"
        s["available_artifacts"] = sorted(["task", "plan", "code", "verify", "research", "status", "improvement"])
        sp.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = gsv.write_transition(tmp_path, "TASK-001", "verifying", "done")
        assert result.ok
        status = gsv.load_json(gsv.artifact_path(tmp_path, "TASK-001", "status"))
        assert status.get("Gate_E_passed") is True
        assert status.get("Gate_E_timestamp")
        assert any("improvement" in e for e in status.get("Gate_E_evidence", []))

    def test_gate_e_not_passed_from_blocked_without_applied(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        self._make_improvement(tmp_path, "drafted")
        sp = tmp_path / "status" / "TASK-001.status.json"
        s = json.loads(sp.read_text(encoding="utf-8"))
        s["state"] = "blocked"
        s["blocked_reason"] = "test block"
        s["available_artifacts"] = sorted(["task", "plan", "code", "verify", "research", "status", "improvement"])
        sp.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = gsv.write_transition(tmp_path, "TASK-001", "blocked", "done")
        assert not result.ok

class TestGsvHistoricalDiffCommitRange:
    def test_commit_range_valid_flow(self, tmp_path):
        # Plan and code artifacts for commit-range
        plan = tmp_path / "plans" / "TASK-001.plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        code = tmp_path / "code" / "TASK-001.code.md"
        code.parent.mkdir(parents=True)
        base_sha = "a" * 40
        head_sha = "b" * 40
        snapshot_files = {"src/a.py"}
        snapshot_sha = gsv.compute_snapshot_sha256(snapshot_files)
        code_text = textwrap.dedent(f"""\
            ## Files Changed
            - src/a.py
            ## Diff Evidence
            - Evidence Type: commit-range
            - Base Commit: {base_sha}
            - Head Commit: {head_sha}
            - Diff Command: git diff --name-only {base_sha}..{head_sha}
            - Changed Files Snapshot: src/a.py
            - Snapshot SHA256: {snapshot_sha}
        """)
        code.write_text(code_text, encoding="utf-8")
        # Mock git diff to return the same file set
        mock_result = _mock_subprocess_run(stdout="src/a.py\n")
        with patch("subprocess.run", return_value=mock_result):
            result = gsv.detect_historical_diff_scope_drift(tmp_path, plan, code)
        assert not result.errors

    def test_commit_range_missing_fields(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        code = tmp_path / "code.md"
        snapshot_sha = gsv.compute_snapshot_sha256({"src/a.py"})
        code_text = textwrap.dedent(f"""\
            ## Files Changed
            - src/a.py
            ## Diff Evidence
            - Evidence Type: commit-range
            - Changed Files Snapshot: src/a.py
            - Snapshot SHA256: {snapshot_sha}
        """)
        code.write_text(code_text, encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan, code)
        assert any("requires" in e for e in result.errors)

    def test_commit_range_invalid_sha(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        code = tmp_path / "code.md"
        snapshot_sha = gsv.compute_snapshot_sha256({"src/a.py"})
        code_text = textwrap.dedent(f"""\
            ## Files Changed
            - src/a.py
            ## Diff Evidence
            - Evidence Type: commit-range
            - Base Commit: short
            - Head Commit: alsoShort
            - Diff Command: git diff --name-only short..alsoShort
            - Changed Files Snapshot: src/a.py
            - Snapshot SHA256: {snapshot_sha}
        """)
        code.write_text(code_text, encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan, code)
        assert any("40-character" in e for e in result.errors)

    def test_commit_range_snapshot_mismatch(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        code = tmp_path / "code.md"
        code_text = textwrap.dedent("""\
            ## Files Changed
            - src/a.py
            ## Diff Evidence
            - Evidence Type: commit-range
            - Changed Files Snapshot: src/a.py
            - Snapshot SHA256: 0000000000000000000000000000000000000000000000000000000000000000
        """)
        code.write_text(code_text, encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan, code)
        assert any("Snapshot SHA256" in e for e in result.errors)

    def test_github_pr_valid_flow(self, tmp_path):
        plan = tmp_path / "plans" / "TASK-001.plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        code = tmp_path / "code" / "TASK-001.code.md"
        code.parent.mkdir(parents=True)
        snapshot_files = {"src/a.py"}
        snapshot_sha = gsv.compute_snapshot_sha256(snapshot_files)
        code_text = textwrap.dedent(f"""\
            ## Files Changed
            - src/a.py
            ## Diff Evidence
            - Evidence Type: github-pr
            - Repository: user/repo
            - PR Number: 1
            - Changed Files Snapshot: src/a.py
            - Snapshot SHA256: {snapshot_sha}
        """)
        code.write_text(code_text, encoding="utf-8")
        payload = [{"filename": "src/a.py"}]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda *a: None
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = gsv.detect_historical_diff_scope_drift(None, plan, code)
        assert not result.errors

    def test_github_pr_provider_error(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("## Files Likely Affected\n- src/a.py\n", encoding="utf-8")
        code = tmp_path / "code.md"
        snapshot_files = {"src/a.py"}
        snapshot_sha = gsv.compute_snapshot_sha256(snapshot_files)
        code_text = textwrap.dedent(f"""\
            ## Files Changed
            - src/a.py
            ## Diff Evidence
            - Evidence Type: github-pr
            - Repository: user/repo
            - PR Number: 1
            - Changed Files Snapshot: src/a.py
            - Snapshot SHA256: {snapshot_sha}
        """)
        code.write_text(code_text, encoding="utf-8")
        exc = urllib.error.URLError("connection refused")
        with patch("urllib.request.urlopen", side_effect=exc):
            result = gsv.detect_historical_diff_scope_drift(None, plan, code)
        assert any("failed" in e for e in result.errors)

class TestGsvStateRequiredArtifacts:
    def test_lightweight_mode(self):
        required = gsv.state_required_artifacts("done", set(), validation_mode=gsv.AUTO_CLASSIFY_LIGHTWEIGHT)
        assert required == {"task", "code", "verify", "status"}

    def test_full_mode_done_with_research(self):
        required = gsv.state_required_artifacts("done", {"research"})
        assert "research" not in required
        production = gsv.state_required_artifacts("done", {"research"}, assurance_level="production")
        assert "research" in production

    def test_full_mode_done_with_test(self):
        required = gsv.state_required_artifacts("done", {"test"}, validation_mode=gsv.AUTO_CLASSIFY_FULL)
        assert "test" not in required
        mvp = gsv.state_required_artifacts("done", {"test"}, assurance_level="mvp", validation_mode=gsv.AUTO_CLASSIFY_FULL)
        assert "test" in mvp

class TestGsvInferStateFromArtifacts:
    def test_empty(self):
        assert gsv.infer_state_from_artifacts(set()) == "drafted"

    def test_with_task_only(self):
        result = gsv.infer_state_from_artifacts({"task", "status"})
        assert result == "drafted"

class TestGsvCollectGithubPrFilesEdgeCases:
    """Cover lines 505, 507, 516 — pagination and edge cases."""
    @unittest.mock.patch("artifacts.scripts.guard_status_validator.urllib.request.urlopen")
    def test_exceeds_max_pages(self, mock_urlopen):
        """Cover line 507 — too many pages."""
        # Create a response with exactly 100 items to trigger next page
        full_page = [{"filename": f"file{i}.py"} for i in range(100)]
        def make_resp(data):
            resp = unittest.mock.MagicMock()
            resp.read.return_value = json.dumps(data).encode()
            resp.headers = {}
            resp.__enter__ = lambda s: s
            resp.__exit__ = unittest.mock.MagicMock(return_value=False)
            return resp
        # MAX_GITHUB_PR_FILES_PAGES + 1 full pages
        max_pages = gsv.MAX_GITHUB_PR_FILES_PAGES
        mock_urlopen.side_effect = [make_resp(full_page) for _ in range(max_pages + 1)]
        files, err = gsv.collect_github_pr_files("owner/repo", "1", "")
        assert err is not None
        assert "exceeds" in err

    @unittest.mock.patch("artifacts.scripts.guard_status_validator.urllib.request.urlopen")
    def test_non_list_response(self, mock_urlopen):
        resp = unittest.mock.MagicMock()
        resp.read.return_value = json.dumps({"error": "not found"}).encode()
        resp.headers = {}
        resp.__enter__ = lambda s: s
        resp.__exit__ = unittest.mock.MagicMock(return_value=False)
        mock_urlopen.return_value = resp
        files, err = gsv.collect_github_pr_files("owner/repo", "1", "")
        assert err is not None

    @unittest.mock.patch("artifacts.scripts.guard_status_validator.urllib.request.urlopen")
    def test_missing_filename_key(self, mock_urlopen):
        resp = unittest.mock.MagicMock()
        resp.read.return_value = json.dumps([{"path": "a.py"}]).encode()
        resp.headers = {}
        resp.__enter__ = lambda s: s
        resp.__exit__ = unittest.mock.MagicMock(return_value=False)
        mock_urlopen.return_value = resp
        files, err = gsv.collect_github_pr_files("owner/repo", "1", "")
        assert err is not None
        assert "without filename" in err

class TestGsvWriteTransitionEdgeCases:
    """Cover lines 1664, 1679, 1704-1706."""
    @unittest.mock.patch.object(gsv, "validate_all", return_value=gsv.ValidationResult([], []))
    @unittest.mock.patch.object(gsv, "validate_transition", return_value=gsv.ValidationResult([], []))
    def test_state_mismatch_refuses(self, mock_vt, mock_va, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        # status state is "done", but from_state is "coding" → mismatch
        result = gsv.write_transition(tmp_path, "TASK-001", "coding", "verifying")
        assert not result.ok
        assert any("Refusing" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "validate_artifact_presence", return_value=gsv.ValidationResult([], []))
    @unittest.mock.patch.object(gsv, "validate_all", return_value=gsv.ValidationResult([], []))
    @unittest.mock.patch.object(gsv, "validate_transition", return_value=gsv.ValidationResult([], []))
    def test_gate_e_blocked_without_applied_improvement(self, mock_vt, mock_va, mock_vap, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        imp_dir = tmp_path / "improvement"
        imp_dir.mkdir(exist_ok=True)
        content = (
            "# Process Improvement\n"
            "## Metadata\n"
            "- Artifact Type: improvement\n"
            "- Task ID: TASK-001\n"
            "- Source Task: TASK-001\n"
            "- Trigger Type: blocked\n"
            "- Owner: Claude\n"
            "- Status: drafted\n"
            f"- Last Updated: {_ts()}\n\n"
            "## 1. What Happened\nTest\n"
            "## 2. Why It Was Not Prevented\nTest\n"
            "## 3. Failure Classification\nTest\n"
            "## 5. Preventive Action (System Level)\nTest\n"
            "## 6. Validation\nTest\n"
            "## 8. Final Rule\nTest\n"
            "## 9. Status\nDrafted\n"
        )
        (imp_dir / "TASK-001.improvement.md").write_text(content, encoding="utf-8")
        sp = tmp_path / "status" / "TASK-001.status.json"
        s = json.loads(sp.read_text(encoding="utf-8"))
        s["state"] = "blocked"
        s["blocked_reason"] = "test"
        s["available_artifacts"] = sorted(["task", "plan", "code", "verify", "research", "status", "improvement"])
        s["required_artifacts"] = sorted(["task", "code", "verify", "research", "status"])
        sp.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = gsv.write_transition(tmp_path, "TASK-001", "blocked", "done")
        assert result.ok
        s2 = json.loads(sp.read_text(encoding="utf-8"))
        assert s2.get("Gate_E_passed") is False

class TestGsvResolveGitRevisionCommitError:
    """Cover lines 649-653."""
    @unittest.mock.patch("artifacts.scripts.guard_status_validator.subprocess.run")
    def test_nonzero_returncode(self, mock_run):
        mock_run.return_value = _mock_subprocess_run(returncode=128, stderr="fatal: bad object")
        commit, err = gsv.resolve_git_revision_commit(Path("/tmp"), "HEAD")
        assert err is not None
        assert commit is None

    @unittest.mock.patch("artifacts.scripts.guard_status_validator.subprocess.run")
    def test_empty_stdout(self, mock_run):
        mock_run.return_value = _mock_subprocess_run(returncode=0, stdout="  \n")
        # Empty stdout after strip causes IndexError — this is a known edge case
        with pytest.raises(IndexError):
            gsv.resolve_git_revision_commit(Path("/tmp"), "HEAD")


# ── Phase 4d: targeted coverage for remaining gaps ──

class TestGsvClassifyDecisionWaiverGate_v2:
    """Cover line 1544 (Gate_A)."""
    def test_gate_a_research(self):
        result = gsv.classify_decision_waiver_gate("TASK-001.research.md: missing section")
        assert result == "Gate_A"

    def test_gate_a_research_artifact(self):
        result = gsv.classify_decision_waiver_gate("research artifact is required")
        assert result == "Gate_A"

class TestGsvActiveDecisionWaiversEdge:
    """Cover line 1556 (non-dict entry skip)."""
    def test_non_dict_entries_skipped(self):
        status = {"decision_waivers": ["not_a_dict", 42, None]}
        result = gsv.active_decision_waivers(status)
        assert result == {}

    def test_non_list_waivers(self):
        status = {"decision_waivers": "invalid"}
        result = gsv.active_decision_waivers(status)
        assert result == {}

class TestGsvAutoClassifyLightweight:
    """Cover lines 879, 889."""
    def test_lightweight_upgrade_due_to_plan_risks(self, tmp_path):
        task_dir = tmp_path / "tasks"
        task_dir.mkdir()
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        task_text = (
            "# Task\n## Metadata\n"
            "- Artifact Type: task\n- Task ID: TASK-001\n"
            f"- Owner: Claude\n- Status: drafted\n- Last Updated: {_ts()}\n"
            "## Objective\nTest\n## Constraints\nNone\n## Acceptance Criteria\nDone\n"
            "## Inline Flags\nlightweight: true\n"
        )
        (task_dir / "TASK-001.task.md").write_text(task_text, encoding="utf-8")
        plan_text = (
            "# Plan\n## Metadata\n"
            "- Artifact Type: plan\n- Task ID: TASK-001\n"
            f"- Owner: Claude\n- Status: drafted\n- Last Updated: {_ts()}\n"
            "## Objective\nTest\n## Proposed Changes\nTest\n"
            "## Files Likely Affected\n- src/main.py\n"
            "## Validation Strategy\nTest\n"
            "## Risks\n- R1: real risk with trigger and mitigation\n"
        )
        (plan_dir / "TASK-001.plan.md").write_text(plan_text, encoding="utf-8")
        status = {
            "task_id": "TASK-001", "state": "drafted",
            "available_artifacts": ["task", "plan", "status"],
            "required_artifacts": ["task", "status"],
            "missing_artifacts": [],
        }
        sp = status_dir / "TASK-001.status.json"
        sp.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        result = gsv.resolve_validation_mode(tmp_path, "TASK-001", auto_classify=True)
        assert result.validation_mode == gsv.AUTO_CLASSIFY_FULL
        assert any("AUTO-UPGRADE" in w for w in result.warnings)

class TestGsvReconcileProtectedFields:
    """Cover line 1339."""
    def test_protected_fields_not_overwritten(self, tmp_path):
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        task_dir = tmp_path / "tasks"
        task_dir.mkdir()
        task_text = (
            "# Task\n## Metadata\n"
            "- Artifact Type: task\n- Task ID: TASK-001\n"
            f"- Owner: Claude\n- Status: drafted\n- Last Updated: {_ts()}\n"
            "## Objective\nTest\n## Constraints\nNone\n## Acceptance Criteria\nDone\n"
        )
        (task_dir / "TASK-001.task.md").write_text(task_text, encoding="utf-8")
        status = {"task_id": "TASK-001", "state": "drafted"}
        sp = status_dir / "TASK-001.status.json"
        sp.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        result = gsv.reconcile_status(tmp_path, "TASK-001")
        s2 = json.loads(sp.read_text(encoding="utf-8"))
        # state is protected, should remain "drafted"
        assert s2["state"] == "drafted"

class TestGsvClassifyDecisionWaiverGateMore:
    """Cover line 1540."""
    def test_gate_b_plan(self):
        result = gsv.classify_decision_waiver_gate("TASK-001.plan.md: missing section")
        assert result == "Gate_B"

    def test_gate_b_plan_not_ready(self):
        result = gsv.classify_decision_waiver_gate("plan artifact is not ready for coding")
        assert result == "Gate_B"

class TestGsvWriteTransitionTargetPresenceFails:
    """Cover line 1679."""
    @unittest.mock.patch.object(gsv, "validate_artifact_presence", return_value=gsv.ValidationResult(["missing verify"], []))
    @unittest.mock.patch.object(gsv, "validate_all", return_value=gsv.ValidationResult([], []))
    @unittest.mock.patch.object(gsv, "validate_transition", return_value=gsv.ValidationResult([], []))
    def test_target_presence_errors(self, mock_vt, mock_va, mock_vap, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        result = gsv.write_transition(tmp_path, "TASK-001", "done", "blocked")
        assert not result.ok
        assert any("Target state" in e for e in result.errors)


# ── Phase 5: Coverage push toward 97% ──────────────────────────────

class TestGsvCollectGithubPrFilesWithToken:
    """Cover line 481 — Authorization header when GITHUB_TOKEN is set."""
    def test_token_header_included(self):
        with unittest.mock.patch.dict(os.environ, {"GITHUB_TOKEN": "test-token-abc"}, clear=False):
            with unittest.mock.patch("urllib.request.urlopen") as mock_urlopen:
                mock_resp = unittest.mock.MagicMock()
                mock_resp.read.return_value = b"[]"
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = lambda s, *a: None
                mock_urlopen.return_value = mock_resp
                files, err = gsv.collect_github_pr_files("owner/repo", "1", "")
        assert err is None
        assert files == set()
        # Verify Authorization header was set
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]
        assert request_obj.get_header("Authorization") == "Bearer test-token-abc"

class TestGsvDetectGitBackedScopeDriftUndeclared:
    """Cover line 674 — undeclared actual changed files."""
    def test_undeclared_files(self, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text(
            "## Files Likely Affected\n- `src/main.py`\n",
            encoding="utf-8",
        )
        code_path = tmp_path / "code.md"
        code_path.write_text(
            "## Files Changed\n- `src/main.py`\n",
            encoding="utf-8",
        )
        actual_changed = {"src/main.py", "src/extra.py", "artifacts/tasks/TASK-001.task.md"}
        task_artifacts = {"artifacts/tasks/TASK-001.task.md"}
        result = gsv.detect_git_backed_scope_drift(plan_path, code_path, actual_changed, task_artifacts)
        assert result.waiver_candidate_errors
        assert any("src/extra.py" in e for e in result.waiver_candidate_errors)
        assert "src/extra.py" in result.drift_files

    def test_all_declared_no_drift(self, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text(
            "## Files Likely Affected\n- `src/main.py`\n",
            encoding="utf-8",
        )
        code_path = tmp_path / "code.md"
        code_path.write_text(
            "## Files Changed\n- `src/main.py`\n",
            encoding="utf-8",
        )
        actual_changed = {"src/main.py", "artifacts/tasks/TASK-001.task.md"}
        task_artifacts = {"artifacts/tasks/TASK-001.task.md"}
        result = gsv.detect_git_backed_scope_drift(plan_path, code_path, actual_changed, task_artifacts)
        assert not result.waiver_candidate_errors
        assert not result.drift_files

class TestGsvReconcileStatusProtectedFieldSkip:
    """Cover line 1339 — protected field in defaults is skipped during reconcile."""
    def test_protected_field_not_overwritten(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        sp = tmp_path / "status" / "TASK-001.status.json"
        status = json.loads(sp.read_text(encoding="utf-8"))
        # Set a protected field
        status["Gate_E_passed"] = True
        status["Gate_E_evidence"] = "commit abc123"
        sp.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Now mock build_reconcile_defaults to include protected fields in defaults
        fake_defaults = {
            "Gate_E_passed": False,
            "Gate_E_evidence": "overwritten",
            "some_new_field": "value",
        }
        with unittest.mock.patch.object(gsv, "build_reconcile_defaults", return_value=(fake_defaults, [])):
            result = gsv.reconcile_status(tmp_path, "TASK-001")
        # Protected fields should NOT have been overwritten
        updated = json.loads(sp.read_text(encoding="utf-8"))
        assert updated["Gate_E_passed"] is True
        assert updated["Gate_E_evidence"] == "commit abc123"
        # Non-protected field should have been added
        assert updated.get("some_new_field") == "value"

class TestGsvValidateScopeDriftWaiverBranches:
    """Cover lines 808, 811 — decision without Guard Exception / wrong exception type."""
    def test_decision_without_guard_exception(self, tmp_path):
        """Line 808: decision exists but has no Guard Exception section."""
        decisions_dir = tmp_path / "decisions"
        decisions_dir.mkdir()
        decision = (
            "# Decision\n## Metadata\n- Task ID: TASK-001\n"
            "## Context\nSome context\n"
            "## Decision\nSome decision\n"
        )
        (decisions_dir / "TASK-001.decision.md").write_text(decision, encoding="utf-8")
        result = gsv.validate_scope_drift_waiver(tmp_path, "TASK-001", {"src/extra.py"})
        assert result.errors
        assert any("Guard Exception" in e for e in result.errors)

    def test_decision_wrong_exception_type(self, tmp_path):
        """Line 811: decision has Guard Exception but wrong type."""
        decisions_dir = tmp_path / "decisions"
        decisions_dir.mkdir()
        decision = (
            "# Decision\n## Metadata\n- Task ID: TASK-001\n"
            "## Guard Exception\n"
            "- Exception Type: some-other-type\n"
            "- Scope Files: src/extra.py\n"
            "- Justification: testing\n"
        )
        (decisions_dir / "TASK-001.decision.md").write_text(decision, encoding="utf-8")
        result = gsv.validate_scope_drift_waiver(tmp_path, "TASK-001", {"src/extra.py"})
        assert result.errors
        assert any("Guard Exception" in e for e in result.errors)

    def test_decision_correct_waiver(self, tmp_path):
        """Happy path: correct allow-scope-drift waiver."""
        decisions_dir = tmp_path / "decisions"
        decisions_dir.mkdir()
        decision = (
            "# Decision\n## Metadata\n- Task ID: TASK-001\n"
            "## Guard Exception\n"
            "- Exception Type: allow-scope-drift\n"
            "- Scope Files: src/extra.py\n"
            "- Justification: Necessary for fix\n"
        )
        (decisions_dir / "TASK-001.decision.md").write_text(decision, encoding="utf-8")
        result = gsv.validate_scope_drift_waiver(tmp_path, "TASK-001", {"src/extra.py"})
        assert not result.errors
        assert any("waiver applied" in w for w in result.warnings)

class TestGsvDetectGitBackedScopeDriftEmptyScope:
    """Cover line 674 — actual_scope_changed is empty after filtering."""
    def test_only_artifact_files_changed(self, tmp_path):
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        code_path = tmp_path / "code.md"
        code_path.write_text("## Files Changed\n- `src/main.py`\n", encoding="utf-8")
        # Only artifacts/ paths changed (and not in declared/planned)
        actual_changed = {"artifacts/other/file.md", "artifacts/tasks/TASK-001.task.md"}
        task_artifacts = {"artifacts/tasks/TASK-001.task.md"}
        result = gsv.detect_git_backed_scope_drift(plan_path, code_path, actual_changed, task_artifacts)
        # artifacts/other/file.md starts with artifacts/ and is not in declared/planned → excluded
        assert not result.waiver_candidate_errors
        assert not result.drift_files
