"""Split unit tests for prompt_regression_validator per TASK-1054."""
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


class TestPromptNormalizeText:
    def test_lowercase_and_collapse(self):
        result = prv.normalize_text("Hello   WORLD\n\n")
        assert result == "hello world "

    def test_crlf(self):
        result = prv.normalize_text("a\r\nb")
        assert "\r" not in result

class TestContainsAny:
    def test_found(self):
        assert prv.contains_any("the quick brown fox", ["Quick", "Slow"]) is True

    def test_not_found(self):
        assert prv.contains_any("the quick brown fox", ["Lazy", "Sleepy"]) is False

class TestCheckNearTerms:
    def test_near(self):
        text = "the quick brown fox jumps"
        assert prv.check_near_terms(text, ["quick", "fox"], 20) is True

    def test_far(self):
        text = "quick " + "x" * 300 + " fox"
        assert prv.check_near_terms(text, ["quick", "fox"], 20) is False

    def test_missing_term(self):
        assert prv.check_near_terms("hello world", ["hello", "missing"], 100) is False

class TestEvaluateCase:
    def test_must_contain_all_pass(self, tmp_path):
        (tmp_path / "test.md").write_text("artifact workflow gate guard", encoding="utf-8")
        case = {
            "id": "TC-1",
            "title": "test",
            "assertions": [
                {"file": "test.md", "must_contain_all": ["artifact", "workflow"]}
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert result.passed

    def test_must_contain_all_fail(self, tmp_path):
        (tmp_path / "test.md").write_text("only artifact here", encoding="utf-8")
        case = {
            "id": "TC-2",
            "title": "test",
            "assertions": [
                {"file": "test.md", "must_contain_all": ["artifact", "missing_term"]}
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_must_not_contain_any(self, tmp_path):
        (tmp_path / "test.md").write_text("clean content", encoding="utf-8")
        case = {
            "id": "TC-3",
            "title": "test",
            "assertions": [
                {"file": "test.md", "must_not_contain_any": ["forbidden"]}
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert result.passed

    def test_must_not_contain_any_fail(self, tmp_path):
        (tmp_path / "test.md").write_text("this has forbidden content", encoding="utf-8")
        case = {
            "id": "TC-4",
            "title": "test",
            "assertions": [
                {"file": "test.md", "must_not_contain_any": ["forbidden"]}
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed


# ─────────────────────────────────────────────
# build_decision_registry
# ─────────────────────────────────────────────

class TestEvaluateCaseEdges:
    def test_near_assertion_pass(self, tmp_path):
        (tmp_path / "test.md").write_text("artifact workflow guard", encoding="utf-8")
        case = {
            "id": "TC-NEAR-1",
            "title": "near test",
            "assertions": [
                {"file": "test.md", "near": [{"terms": ["artifact", "workflow"], "max_chars": 50}]}
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert result.passed

    def test_near_assertion_fail(self, tmp_path):
        content = "artifact " + ("x " * 200) + "workflow"
        (tmp_path / "test.md").write_text(content, encoding="utf-8")
        case = {
            "id": "TC-NEAR-2",
            "title": "near test",
            "assertions": [
                {"file": "test.md", "near": [{"terms": ["artifact", "workflow"], "max_chars": 10}]}
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_missing_file(self, tmp_path):
        case = {
            "id": "TC-MISS",
            "title": "missing file",
            "assertions": [
                {"file": "nonexistent.md", "must_contain_all": ["anything"]}
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_all_of_any_assertion(self, tmp_path):
        (tmp_path / "test.md").write_text("alpha beta gamma", encoding="utf-8")
        case = {
            "id": "TC-AOA",
            "title": "all_of_any test",
            "assertions": [
                {"file": "test.md", "all_of_any": [
                    ["alpha", "missing"],
                    ["alpha", "beta"],
                ]}
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert result.passed


# ─────────────────────────────────────────────
# validate_scorecard_deltas: additional edges
# ─────────────────────────────────────────────

class TestCollapseWhitespace:
    def test_basic(self):
        assert bdr.collapse_whitespace("a   b\n\nc") == "a b c"

    def test_empty(self):
        assert bdr.collapse_whitespace("") == ""

class TestNormalizeRefs:
    def test_multiple(self):
        result = bdr.normalize_refs(["TASK-900", "artifacts/plans/TASK-901.plan.md"], "plans")
        assert len(result) == 2
        assert "artifacts/plans/TASK-900.plan.md" in result
        assert "artifacts/plans/TASK-901.plan.md" in result

    def test_empty(self):
        assert bdr.normalize_refs([], "plans") == []


# ─────────────────────────────────────────────
# aggregate_red_team_scorecard: edge cases
# ─────────────────────────────────────────────

class TestParseReportEdges:
    def test_empty_table(self):
        markdown = "| Case | Phase | Expected | Outcome | Exit | Evidence | Notes |\n|---|---|---|---|---:|---|---|\n"
        rows = ars.parse_report(markdown)
        assert rows == []

    def test_no_table(self):
        assert ars.parse_report("just text") == []

    def test_case_fail_exit_nonzero(self):
        markdown = textwrap.dedent("""\
            | Case | Phase | Expected | Outcome | Exit | Evidence | Notes |
            |---|---|---|---|---:|---|---|
            | `RT-001` | static | pass | pass | 0 | ok | None |
        """)
        rows = ars.parse_report(markdown)
        assert rows[0].case_passed is True  # expected=pass, outcome=pass

    def test_auto_score_boundary(self):
        from aggregate_red_team_scorecard import CaseRow
        # Expected=pass and outcome=pass → also pass (score 2)
        row = CaseRow("RT-001", "static", "pass", "pass", "0", "[OK]", "")
        assert ars.auto_score(row) == 2
        # Expected=pass but outcome=fail → fail (score 0)
        row_fail = CaseRow("RT-001", "static", "pass", "fail", "1", "[FAIL]", "")
        assert ars.auto_score(row_fail) == 0


# ═════════════════════════════════════════════
# FIXTURE-BASED TESTS FOR guard_status_validator
# ═════════════════════════════════════════════


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


# ─────────────────────────────────────────────
# load_json / load_text / write_json
# ─────────────────────────────────────────────

class TestPrvEvaluateCase:
    def test_no_assertions(self):
        case = {"id": "TC-01", "title": "Test", "assertions": []}
        result = prv.evaluate_case(case, Path("."), {})
        assert not result.passed

    def test_must_contain_all_found(self, tmp_path):
        (tmp_path / "test.md").write_text("hello world foo bar", encoding="utf-8")
        case = {
            "id": "TC-01",
            "title": "Test",
            "assertions": [{"file": "test.md", "must_contain_all": ["hello", "foo"]}],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert result.passed

    def test_must_contain_all_missing(self, tmp_path):
        (tmp_path / "test.md").write_text("hello world", encoding="utf-8")
        case = {
            "id": "TC-01",
            "title": "Test",
            "assertions": [{"file": "test.md", "must_contain_all": ["hello", "missing"]}],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_must_not_contain_any(self, tmp_path):
        (tmp_path / "test.md").write_text("hello world secret", encoding="utf-8")
        case = {
            "id": "TC-01",
            "title": "Test",
            "assertions": [{"file": "test.md", "must_not_contain_any": ["secret"]}],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_all_of_any(self, tmp_path):
        (tmp_path / "test.md").write_text("the quick brown fox", encoding="utf-8")
        case = {
            "id": "TC-01",
            "title": "Test",
            "assertions": [
                {"file": "test.md", "all_of_any": [["quick", "slow"], ["cat", "fox"]]}
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert result.passed

    def test_all_of_any_missing(self, tmp_path):
        (tmp_path / "test.md").write_text("the quick brown fox", encoding="utf-8")
        case = {
            "id": "TC-01",
            "title": "Test",
            "assertions": [
                {"file": "test.md", "all_of_any": [["missing1", "missing2"]]}
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_near_terms(self, tmp_path):
        (tmp_path / "test.md").write_text("the quick brown fox jumps", encoding="utf-8")
        case = {
            "id": "TC-01",
            "title": "Test",
            "assertions": [
                {
                    "file": "test.md",
                    "near": [{"terms": ["quick", "fox"], "max_chars": 50}],
                }
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert result.passed

    def test_near_terms_too_far(self, tmp_path):
        content = "quick " + "x" * 300 + " fox"
        (tmp_path / "test.md").write_text(content, encoding="utf-8")
        case = {
            "id": "TC-01",
            "title": "Test",
            "assertions": [
                {
                    "file": "test.md",
                    "near": [{"terms": ["quick", "fox"], "max_chars": 50}],
                }
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_missing_file(self, tmp_path):
        case = {
            "id": "TC-01",
            "title": "Test",
            "assertions": [{"file": "nonexistent.md", "must_contain_all": ["x"]}],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed
        assert any("Target file missing" in f.message for f in result.failures)

    def test_file_caching(self, tmp_path):
        (tmp_path / "test.md").write_text("cached content", encoding="utf-8")
        cache = {}
        case = {
            "id": "TC-01",
            "title": "Test",
            "assertions": [
                {"file": "test.md", "must_contain_all": ["cached"]},
                {"file": "test.md", "must_contain_all": ["content"]},
            ],
        }
        result = prv.evaluate_case(case, tmp_path, cache)
        assert result.passed
        assert "test.md" in cache

class TestPrvRenderReport:
    def test_all_pass(self):
        results = [prv.CaseResult("TC-01", "Test", True, [])]
        report = prv.render_report(results)
        assert "pass" in report
        assert "None" in report  # No failure details

    def test_with_failures(self):
        failure = prv.AssertionFailure("test.md", "missing term: foo", "check foo")
        results = [prv.CaseResult("TC-01", "Test", False, [failure])]
        report = prv.render_report(results)
        assert "fail" in report
        assert "missing term: foo" in report
        assert "check foo" in report

class TestPrvLoadCases:
    def test_valid(self, tmp_path):
        p = tmp_path / "cases.json"
        p.write_text('[{"id": "TC-01"}]', encoding="utf-8")
        assert len(prv.load_cases(p)) == 1

    def test_missing(self, tmp_path):
        with pytest.raises(RuntimeError, match="not found"):
            prv.load_cases(tmp_path / "missing.json")

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{invalid}", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Invalid JSON"):
            prv.load_cases(p)

    def test_not_list(self, tmp_path):
        p = tmp_path / "obj.json"
        p.write_text('{"key": "value"}', encoding="utf-8")
        with pytest.raises(RuntimeError, match="must be a list"):
            prv.load_cases(p)


# ─────────────────────────────────────────────
# aggregate_red_team_scorecard
# ─────────────────────────────────────────────

class TestPrvAssertionEdgeCases:
    def test_missing_file_field(self, tmp_path):
        case = {"id": "TC-01", "title": "T", "assertions": [{"must_contain_all": ["x"]}]}
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed
        assert any("missing file" in f.message for f in result.failures)

    def test_all_of_any_invalid_type(self, tmp_path):
        (tmp_path / "t.md").write_text("content", encoding="utf-8")
        case = {"id": "TC-01", "title": "T", "assertions": [{"file": "t.md", "all_of_any": "bad"}]}
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_all_of_any_empty_group(self, tmp_path):
        (tmp_path / "t.md").write_text("content", encoding="utf-8")
        case = {"id": "TC-01", "title": "T", "assertions": [{"file": "t.md", "all_of_any": [[]]}]}
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_must_contain_all_invalid_type(self, tmp_path):
        (tmp_path / "t.md").write_text("content", encoding="utf-8")
        case = {"id": "TC-01", "title": "T", "assertions": [{"file": "t.md", "must_contain_all": "bad"}]}
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_must_not_contain_any_invalid_type(self, tmp_path):
        (tmp_path / "t.md").write_text("content", encoding="utf-8")
        case = {"id": "TC-01", "title": "T", "assertions": [{"file": "t.md", "must_not_contain_any": "bad"}]}
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_near_invalid_type(self, tmp_path):
        (tmp_path / "t.md").write_text("content", encoding="utf-8")
        case = {"id": "TC-01", "title": "T", "assertions": [{"file": "t.md", "near": "bad"}]}
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

    def test_near_too_few_terms(self, tmp_path):
        (tmp_path / "t.md").write_text("content", encoding="utf-8")
        case = {
            "id": "TC-01", "title": "T",
            "assertions": [{"file": "t.md", "near": [{"terms": ["one"], "max_chars": 50}]}],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert not result.passed

class TestPrvRenderReportDeeper:
    def test_multiple_results(self):
        r1 = prv.CaseResult("TC-01", "Pass", True, [])
        failure = prv.AssertionFailure("a.md", "missing X", "check X")
        r2 = prv.CaseResult("TC-02", "Fail", False, [failure])
        report = prv.render_report([r1, r2])
        assert "TC-01" in report
        assert "TC-02" in report
        assert "missing X" in report
        assert "## Failure Details" in report


class TestPrvModeGating:
    """TASK-1073: source-only cases (e.g. PR-009) are skipped in downstream terminal repos."""

    def test_detect_repo_mode_source(self, tmp_path):
        (tmp_path / ".council-forge-source-repo").write_text("x", encoding="utf-8")
        assert prv.detect_repo_mode(tmp_path) == "source"

    def test_detect_repo_mode_downstream(self, tmp_path):
        assert prv.detect_repo_mode(tmp_path) == "downstream"

    def test_case_applies_default_all(self):
        assert prv.case_applies({"id": "X"}, "downstream") is True
        assert prv.case_applies({"id": "X"}, "source") is True

    def test_case_applies_source_only(self):
        case = {"id": "PR-009", "applies_to": "source"}
        assert prv.case_applies(case, "source") is True
        assert prv.case_applies(case, "downstream") is False

    def test_main_skips_source_only_case_in_downstream(self, tmp_path, capsys):
        cases = [{
            "id": "S-ONLY", "applies_to": "source", "title": "src",
            "assertions": [{"file": "template/CLAUDE.md", "must_contain_all": ["x"]}],
        }]
        cases_path = tmp_path / "artifacts" / "scripts" / "drills" / "cases.json"
        cases_path.parent.mkdir(parents=True, exist_ok=True)
        cases_path.write_text(json.dumps(cases), encoding="utf-8")
        # downstream (no sentinel): the source-only case is skipped, so the missing
        # template/ target does not fail the run.
        code = prv.main(["--root", str(tmp_path), "--cases", "artifacts/scripts/drills/cases.json"])
        assert code == 0
        assert "skip" in capsys.readouterr().out

    def test_is_brownfield(self, tmp_path):
        assert prv.is_brownfield(tmp_path) is False
        (tmp_path / ".council-forge-brownfield").write_text("x", encoding="utf-8")
        assert prv.is_brownfield(tmp_path) is True

    def test_brownfield_skips_project_owned_assertions(self, tmp_path):
        # TASK-1074: a brownfield downstream owns its README.md / CLAUDE.md, so council-forge
        # assertions on those are skipped (content guaranteed via EXACT_SYNC docs instead).
        (tmp_path / ".council-forge-brownfield").write_text("x", encoding="utf-8")
        case = {
            "id": "X", "title": "t",
            "assertions": [
                {"file": "README.md", "must_contain_all": ["a-council-forge-only-phrase"]},
                {"file": "CLAUDE.md", "must_contain_all": ["another-cf-only-phrase"]},
            ],
        }
        result = prv.evaluate_case(case, tmp_path, {})
        assert result.passed  # both project-owned assertions skipped


# ─────────────────────────────────────────────
# guard_status_validator — deeper coverage
# ─────────────────────────────────────────────

