"""Split unit tests for guard_status_validator core helpers per TASK-1054."""
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


class TestNormalizePathToken:
    def test_basic(self):
        assert gsv.normalize_path_token("  `src/main.py`  ") == "src/main.py"

    def test_strip_backticks_and_quotes(self):
        assert gsv.normalize_path_token('"docs/readme.md"') == "docs/readme.md"

    def test_windows_drive_letter(self):
        assert gsv.normalize_path_token("C:/Users/file.txt") == "/Users/file.txt"

    def test_dot_slash_prefix(self):
        # normalize_path_token strips "." but keeps leading "/" — callers handle that
        result = gsv.normalize_path_token("./artifacts/tasks/TASK-001.task.md")
        assert "artifacts/tasks/TASK-001.task.md" in result

    def test_backslash_to_forward(self):
        assert gsv.normalize_path_token("artifacts\\scripts\\guard.py") == "artifacts/scripts/guard.py"

    def test_diff_prefix_a_b(self):
        assert gsv.normalize_path_token("a/src/lib.py") == "src/lib.py"
        assert gsv.normalize_path_token("b/src/lib.py") == "src/lib.py"

class TestParseKeyValueSection:
    def test_basic(self):
        text = "- Name: Alice\n- Role: Developer\n"
        result = gsv.parse_key_value_section(text)
        assert result["name"] == "Alice"
        assert result["role"] == "Developer"

    def test_empty(self):
        assert gsv.parse_key_value_section("") == {}

    def test_non_matching_lines_ignored(self):
        text = "Some random text\n- Key: Value\n"
        result = gsv.parse_key_value_section(text)
        assert result == {"key": "Value"}

class TestParseListItems:
    def test_bullet_list(self):
        items = gsv.parse_list_items("- Item one\n- Item two\n- Item three")
        assert items == ["Item one", "Item two", "Item three"]

    def test_numbered_list(self):
        items = gsv.parse_list_items("1. First\n2. Second")
        assert items == ["First", "Second"]

    def test_none_entry_excluded(self):
        items = gsv.parse_list_items("- None\n- Real item")
        assert items == ["Real item"]

    def test_multiline_items(self):
        text = "- First line\n  continuation\n- Second item"
        items = gsv.parse_list_items(text)
        assert len(items) == 2
        assert "continuation" in items[0]

class TestExtractSection:
    def test_basic(self):
        text = "## Alpha\nContent A\n## Beta\nContent B\n"
        assert gsv.extract_section(text, "Alpha") == "Content A"
        assert gsv.extract_section(text, "Beta") == "Content B"

    def test_missing_section(self):
        assert gsv.extract_section("## Foo\nbar", "Missing") == ""

    def test_last_section(self):
        text = "## Only\nContent here"
        assert gsv.extract_section(text, "Only") == "Content here"

class TestExtractFileTokens:
    def test_inline_code(self):
        text = "- Modified `src/main.py` for feature\n- Updated `docs/readme.md`"
        tokens = gsv.extract_file_tokens(text)
        assert "src/main.py" in tokens
        assert "docs/readme.md" in tokens

    def test_plain_path(self):
        text = "- artifacts/scripts/guard.py was changed"
        tokens = gsv.extract_file_tokens(text)
        assert "artifacts/scripts/guard.py" in tokens

class TestComputeSnapshotSha256:
    def test_deterministic(self):
        files = {"c.py", "a.py", "b.py"}
        h1 = gsv.compute_snapshot_sha256(files)
        h2 = gsv.compute_snapshot_sha256(files)
        assert h1 == h2
        assert len(h1) == 64

    def test_order_independent(self):
        assert gsv.compute_snapshot_sha256({"a", "b"}) == gsv.compute_snapshot_sha256({"b", "a"})

class TestValidateTaskId:
    def test_valid(self):
        assert gsv.validate_task_id("TASK-001") == []
        assert gsv.validate_task_id("TASK-9999") == []
        assert gsv.validate_task_id("TASK-LITE-001") == []

    def test_invalid(self):
        assert len(gsv.validate_task_id("INVALID")) > 0
        assert len(gsv.validate_task_id("task-001")) > 0
        assert len(gsv.validate_task_id("")) > 0

class TestValidateTaipeiTimestamp:
    def test_valid(self):
        assert gsv.validate_taipei_timestamp("2026-04-16T12:00:00+08:00", "test") == []

    def test_invalid_timezone(self):
        errors = gsv.validate_taipei_timestamp("2026-04-16T12:00:00Z", "test")
        assert len(errors) > 0

    def test_invalid_format(self):
        errors = gsv.validate_taipei_timestamp("2026/04/16", "test")
        assert len(errors) > 0

class TestNormalizeText:
    def test_whitespace_collapse(self):
        result = gcv.normalize_text("a   b\t\tc")
        assert result == "a b c"

    def test_placeholder_replacement(self):
        result = gcv.normalize_text("Project: {{PROJECT_NAME}} in {{REPO_NAME}}")
        assert "__PROJECT__" in result
        assert "__REPO__" in result

    def test_crlf_normalize(self):
        result = gcv.normalize_text("line1\r\nline2")
        assert "\r" not in result

class TestParseSections:
    def test_basic(self):
        text = "## Issue\nSomething broken\n## Chosen Option\nOption A"
        sections = bdr.parse_sections(text)
        assert "issue" in sections
        assert "chosen option" in sections
        assert "Something broken" in sections["issue"]

    def test_empty(self):
        assert bdr.parse_sections("no sections here") == {}

class TestFirstParagraph:
    def test_basic(self):
        assert bdr.first_paragraph("First para.\n\nSecond para.") == "First para."

    def test_empty(self):
        assert bdr.first_paragraph("") == ""
        assert bdr.first_paragraph(None) == ""

class TestCleanRefToken:
    def test_backtick(self):
        assert bdr.clean_ref_token("`TASK-900.plan.md`") == "TASK-900.plan.md"

    def test_bullet(self):
        assert bdr.clean_ref_token("- TASK-901") == "TASK-901"

class TestNormalizeRef:
    def test_task_id_to_plan(self):
        result = bdr.normalize_ref("TASK-900", "plans")
        assert result == "artifacts/plans/TASK-900.plan.md"

    def test_task_id_to_research(self):
        result = bdr.normalize_ref("TASK-900", "research")
        assert result == "artifacts/research/TASK-900.research.md"

    def test_already_full_path(self):
        result = bdr.normalize_ref("artifacts/plans/TASK-900.plan.md", "plans")
        assert result == "artifacts/plans/TASK-900.plan.md"

class TestExtractTaskId:
    def test_valid(self):
        assert bdr.extract_task_id(Path("TASK-900.decision.md")) == "TASK-900"

    def test_invalid(self):
        with pytest.raises(ValueError):
            bdr.extract_task_id(Path("random.md"))


# ─────────────────────────────────────────────
# aggregate_red_team_scorecard
# ─────────────────────────────────────────────

class TestParseReport:
    def test_parse_rows(self):
        markdown = textwrap.dedent("""\
            | Case | Phase | Expected | Outcome | Exit | Evidence | Notes |
            |---|---|---|---|---:|---|---|
            | `RT-001` | static | fail | pass | 0 | `[OK]` | None |
            | `RT-002` | static | fail | fail | 1 | `[FAIL]` | issue |
        """)
        rows = ars.parse_report(markdown)
        assert len(rows) == 2
        assert rows[0].case == "RT-001"
        assert rows[0].case_passed is True
        assert rows[1].case_passed is False

    def test_ignores_malformed_row(self):
        markdown = textwrap.dedent("""\
            | only | three | columns |
            | `RT-001` | static | pass | pass | 0 | ok | None |
        """)
        rows = ars.parse_report(markdown)
        assert len(rows) == 1
        assert rows[0].case == "RT-001"

    def test_parse_new_schema_rows(self):
        markdown = textwrap.dedent("""\
            | Case | Phase | Expected | Outcome | Expected Exit | Actual Exit | Evidence | Notes |
            |---|---|---|---|---:|---:|---|---|
            | `RT-028` | static | fail | pass | 1 | 1 | `exceeds replay byte cap` | None |
        """)
        rows = ars.parse_report(markdown)
        assert len(rows) == 1
        assert rows[0].expected_exit_code == "1"
        assert rows[0].actual_exit_code == "1"

    def test_auto_score(self):
        from aggregate_red_team_scorecard import CaseRow

        pass_row = CaseRow("RT-001", "static", "fail", "pass", "0", "[OK]", "")
        fail_row = CaseRow("RT-002", "static", "fail", "fail", "1", "[FAIL]", "")
        assert ars.auto_score(pass_row) == 2
        assert ars.auto_score(fail_row) == 0


# ─────────────────────────────────────────────
# validate_scorecard_deltas
# ─────────────────────────────────────────────

class TestParseCsvFileTokens:
    def test_empty_string(self):
        assert gsv.parse_csv_file_tokens("") == set()

    def test_none_value(self):
        assert gsv.parse_csv_file_tokens("None") == set()
        assert gsv.parse_csv_file_tokens("NONE") == set()
        assert gsv.parse_csv_file_tokens("  none  ") == set()

    def test_single_token(self):
        result = gsv.parse_csv_file_tokens("src/main.py")
        assert "src/main.py" in result

    def test_multiple_with_whitespace(self):
        result = gsv.parse_csv_file_tokens(" src/a.py , docs/b.md , lib/c.js ")
        assert len(result) == 3
        assert "src/a.py" in result
        assert "docs/b.md" in result

    def test_backtick_wrapped(self):
        result = gsv.parse_csv_file_tokens("`src/a.py`, `docs/b.md`")
        assert "src/a.py" in result
        assert "docs/b.md" in result

    def test_backslash_paths(self):
        result = gsv.parse_csv_file_tokens("src\\main.py")
        assert "src/main.py" in result


# ─────────────────────────────────────────────
# infer_state_from_artifacts
# ─────────────────────────────────────────────

class TestParseRepositoryRef:
    def test_valid(self):
        owner, repo, err = gsv.parse_repository_ref("octocat/hello-world")
        assert owner == "octocat"
        assert repo == "hello-world"
        assert err is None

    def test_missing_repo(self):
        _, _, err = gsv.parse_repository_ref("onlyowner")
        assert err is not None

    def test_empty(self):
        _, _, err = gsv.parse_repository_ref("")
        assert err is not None

    def test_three_segments(self):
        _, _, err = gsv.parse_repository_ref("a/b/c")
        assert err is not None

    def test_dot_segment(self):
        _, _, err = gsv.parse_repository_ref("./repo")
        assert err is not None

    def test_whitespace(self):
        owner, repo, err = gsv.parse_repository_ref("  owner / repo  ")
        assert owner == "owner"
        assert repo == "repo"
        assert err is None


# ─────────────────────────────────────────────
# normalize_api_base_url
# ─────────────────────────────────────────────

class TestNormalizeApiBaseUrl:
    def test_default_empty(self):
        url, err = gsv.normalize_api_base_url("")
        assert url == "https://api.github.com"
        assert err is None

    def test_trailing_slash(self):
        url, err = gsv.normalize_api_base_url("https://api.github.com/")
        assert url == "https://api.github.com"
        assert err is None

    def test_custom_url(self, monkeypatch):
        monkeypatch.setenv(gsv.GITHUB_API_ALLOWED_HOSTS_ENV, "github.example.com")
        url, err = gsv.normalize_api_base_url("https://github.example.com/api/v3")
        assert url == "https://github.example.com/api/v3"
        assert err is None

    def test_invalid_scheme(self):
        _, err = gsv.normalize_api_base_url("ftp://example.com")
        assert err is not None

    def test_no_scheme(self):
        _, err = gsv.normalize_api_base_url("just-a-string")
        assert err is not None


# ─────────────────────────────────────────────
# detect_mixed_github_sources
# ─────────────────────────────────────────────

class TestParseDiffEvidence:
    def test_missing(self):
        assert gsv.parse_diff_evidence("## Other Section\ncontent") is None

    def test_none_value(self):
        assert gsv.parse_diff_evidence("## Diff Evidence\nNone") is None

    def test_valid(self):
        text = "## Diff Evidence\n- Type: commit-range\n- Base Commit: abc123\n"
        result = gsv.parse_diff_evidence(text)
        assert result is not None
        assert result["type"] == "commit-range"
        assert result["base commit"] == "abc123"


# ─────────────────────────────────────────────
# summarize_remote_error_detail
# ─────────────────────────────────────────────

class TestSummarizeRemoteErrorDetail:
    def test_with_body(self):
        result = gsv.summarize_remote_error_detail(b"Not found", "fallback")
        assert result == "Not found"

    def test_empty_body(self):
        result = gsv.summarize_remote_error_detail(b"", "fallback msg")
        assert result == "fallback msg"

    def test_truncation(self):
        long_body = b"x" * 500
        result = gsv.summarize_remote_error_detail(long_body, "fallback")
        assert len(result) == 203  # 200 + "..."
        assert result.endswith("...")


# ─────────────────────────────────────────────
# parse_taipei_datetime
# ─────────────────────────────────────────────

class TestParseTaipeiDatetime:
    def test_valid(self):
        result = gsv.parse_taipei_datetime("2026-01-15T10:30:00+08:00")
        assert result is not None
        assert result.utcoffset() == timedelta(hours=8)

    def test_invalid_format(self):
        assert gsv.parse_taipei_datetime("not a date") is None

    def test_utc_rejected(self):
        assert gsv.parse_taipei_datetime("2026-01-15T10:30:00Z") is None

    def test_empty(self):
        assert gsv.parse_taipei_datetime("") is None

    def test_whitespace_trimmed(self):
        result = gsv.parse_taipei_datetime("  2026-01-15T10:30:00+08:00  ")
        assert result is not None


# ─────────────────────────────────────────────
# evaluate_case: additional edge cases
# ─────────────────────────────────────────────

class TestLoadJson:
    def test_valid(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text('{"key": "value"}', encoding="utf-8")
        assert gsv.load_json(p) == {"key": "value"}

    def test_missing_file(self, tmp_path):
        with pytest.raises(gsv.GuardError, match="Missing JSON"):
            gsv.load_json(tmp_path / "nope.json")

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{invalid}", encoding="utf-8")
        with pytest.raises(gsv.GuardError, match="Invalid JSON"):
            gsv.load_json(p)

    def test_too_large(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text('{"key": "' + ('x' * gsv.MAX_ARTIFACT_FILE_BYTES) + '"}', encoding="utf-8")
        with pytest.raises(gsv.GuardError, match="JSON file too large"):
            gsv.load_json(p)

class TestLoadText:
    def test_valid(self, tmp_path):
        p = tmp_path / "file.md"
        p.write_text("hello world", encoding="utf-8")
        assert gsv.load_text(p) == "hello world"

    def test_missing(self, tmp_path):
        with pytest.raises(gsv.GuardError, match="Missing text"):
            gsv.load_text(tmp_path / "nope.md")

    def test_too_large(self, tmp_path):
        p = tmp_path / "file.md"
        p.write_text('x' * (gsv.MAX_ARTIFACT_FILE_BYTES + 1), encoding="utf-8")
        with pytest.raises(gsv.GuardError, match="Text file too large"):
            gsv.load_text(p)

    def test_invalid_utf8(self, tmp_path):
        p = tmp_path / "bad.md"
        p.write_bytes(b"\xff")
        with pytest.raises(gsv.GuardError, match="Invalid UTF-8"):
            gsv.load_text(p)

class TestWriteJson:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "out.json"
        payload = {"task_id": "TASK-999", "state": "done"}
        gsv.write_json(p, payload)
        assert json.loads(p.read_text(encoding="utf-8")) == payload

    def test_unicode(self, tmp_path):
        p = tmp_path / "unicode.json"
        gsv.write_json(p, {"msg": "中文"})
        assert "中文" in p.read_text(encoding="utf-8")


# ─────────────────────────────────────────────
# load_override_log
# ─────────────────────────────────────────────

class TestLoadOverrideLog:
    def test_missing_file(self, tmp_path):
        assert gsv.load_override_log(tmp_path / "missing.json") == []

    def test_valid(self, tmp_path):
        p = tmp_path / "log.json"
        p.write_text('[{"action": "override"}]', encoding="utf-8")
        result = gsv.load_override_log(p)
        assert len(result) == 1

    def test_not_array(self, tmp_path):
        p = tmp_path / "log.json"
        p.write_text('{"not": "array"}', encoding="utf-8")
        with pytest.raises(gsv.GuardError, match="expected a JSON array"):
            gsv.load_override_log(p)

    def test_entry_not_dict(self, tmp_path):
        p = tmp_path / "log.json"
        p.write_text('["string_entry"]', encoding="utf-8")
        with pytest.raises(gsv.GuardError, match="must be an object"):
            gsv.load_override_log(p)

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "log.json"
        p.write_text("not json", encoding="utf-8")
        with pytest.raises(gsv.GuardError, match="Invalid JSON"):
            gsv.load_override_log(p)

    def test_too_large(self, tmp_path):
        p = tmp_path / "log.json"
        p.write_text("[" + (" " * gsv.MAX_ARTIFACT_FILE_BYTES) + "]", encoding="utf-8")
        with pytest.raises(gsv.GuardError, match="Override log too large"):
            gsv.load_override_log(p)

class TestReadBoundedFile:
    def test_missing_optional_returns_none(self, tmp_path):
        assert gsv.read_bounded_file(tmp_path / "missing.json", missing_label=None, too_large_label="Too large") is None

    def test_oserror_is_wrapped(self, tmp_path, monkeypatch):
        target = tmp_path / "value.json"
        target.write_text("{}", encoding="utf-8")

        def boom(*args, **kwargs):
            raise OSError("boom")

        monkeypatch.setattr(Path, "open", boom)
        with pytest.raises(gsv.GuardError, match="Unable to read"):
            gsv.read_bounded_file(target, missing_label="JSON file", too_large_label="Too large")


# ─────────────────────────────────────────────
# find_artifact_paths / artifact_path
# ─────────────────────────────────────────────

class TestFindArtifactPaths:
    def test_existing(self, tmp_path):
        _make_artifact_tree(tmp_path, "TASK-100", ["task"])
        paths = gsv.find_artifact_paths(tmp_path, "TASK-100", "task")
        assert len(paths) == 1
        assert "TASK-100.task.md" in paths[0].name

    def test_missing(self, tmp_path):
        (tmp_path / "tasks").mkdir()
        assert gsv.find_artifact_paths(tmp_path, "TASK-100", "task") == []

    def test_improvement_glob(self, tmp_path):
        d = tmp_path / "improvement"
        d.mkdir()
        (d / "TASK-100.improvement.md").write_text("# imp1", encoding="utf-8")
        (d / "TASK-100.v2.improvement.md").write_text("# imp2", encoding="utf-8")
        paths = gsv.find_artifact_paths(tmp_path, "TASK-100", "improvement")
        assert len(paths) == 2

class TestArtifactPath:
    def test_valid(self, tmp_path):
        p = gsv.artifact_path(tmp_path, "TASK-001", "task")
        assert p == tmp_path / "tasks" / "TASK-001.task.md"

    def test_unknown_type(self, tmp_path):
        with pytest.raises(gsv.GuardError, match="Unknown artifact type"):
            gsv.artifact_path(tmp_path, "TASK-001", "unknown")


# ─────────────────────────────────────────────
# compute_existing_artifacts
# ─────────────────────────────────────────────

class TestComputeExistingArtifacts:
    def test_empty(self, tmp_path):
        for d in gsv.ARTIFACT_DIRS.values():
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        assert gsv.compute_existing_artifacts(tmp_path, "TASK-001") == set()

    def test_some_present(self, tmp_path):
        _make_artifact_tree(tmp_path, "TASK-001", ["task", "research", "status"])
        # ensure remaining dirs exist
        for d in gsv.ARTIFACT_DIRS.values():
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        result = gsv.compute_existing_artifacts(tmp_path, "TASK-001")
        assert "task" in result
        assert "research" in result
        assert "status" in result
        assert "code" not in result


# ─────────────────────────────────────────────
# resolve_workspace_relative_path
# ─────────────────────────────────────────────

class TestResolveWorkspaceRelativePath:
    def test_valid(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
        normalized, resolved, err = gsv.resolve_workspace_relative_path(tmp_path, "src/main.py")
        assert err is None
        assert "src/main.py" in normalized

    def test_empty_path(self, tmp_path):
        _, _, err = gsv.resolve_workspace_relative_path(tmp_path, "")
        assert err is not None
        assert "empty" in err

    def test_path_escape_dotdot(self, tmp_path):
        _, _, err = gsv.resolve_workspace_relative_path(tmp_path, "../etc/passwd")
        assert err is not None
        assert "within repository root" in err

    def test_absolute_path(self, tmp_path):
        _, _, err = gsv.resolve_workspace_relative_path(tmp_path, "/etc/passwd")
        assert err is not None


# ─────────────────────────────────────────────
# status_uses_legacy_schema
# ─────────────────────────────────────────────

class TestStatusUsesLegacySchema:
    def test_modern(self):
        assert gsv.status_uses_legacy_schema({"state": "done"}) is False

    def test_legacy(self):
        assert gsv.status_uses_legacy_schema({"current_state": "done"}) is True

    def test_both_fields(self):
        # "state" present → not legacy
        assert gsv.status_uses_legacy_schema({"state": "done", "current_state": "done"}) is False

    def test_neither(self):
        assert gsv.status_uses_legacy_schema({}) is False


# ─────────────────────────────────────────────
# extract_task_title
# ─────────────────────────────────────────────

class TestExtractTaskTitle:
    def test_valid(self, tmp_path):
        p = tmp_path / "task.md"
        p.write_text("# Task: Implement Feature X\n## Metadata\n", encoding="utf-8")
        assert gsv.extract_task_title(p) == "Implement Feature X"

    def test_no_title(self, tmp_path):
        p = tmp_path / "task.md"
        p.write_text("## Random\nContent", encoding="utf-8")
        assert gsv.extract_task_title(p) == ""

    def test_none_path(self):
        assert gsv.extract_task_title(None) == ""

    def test_missing_file(self, tmp_path):
        assert gsv.extract_task_title(tmp_path / "nope.md") == ""


# ─────────────────────────────────────────────
# task_is_high_risk
# ─────────────────────────────────────────────

class TestTaskIsHighRisk:
    def test_security_keyword(self, tmp_path):
        p = tmp_path / "task.md"
        p.write_text("# Task: Security audit\n", encoding="utf-8")
        assert gsv.task_is_high_risk(p, "") is True

    def test_upstream_keyword_in_plan(self, tmp_path):
        p = tmp_path / "task.md"
        p.write_text("# Task: Normal task\n", encoding="utf-8")
        assert gsv.task_is_high_risk(p, "upstream pr integration") is True

    def test_no_risk(self, tmp_path):
        p = tmp_path / "task.md"
        p.write_text("# Task: Simple refactor\n", encoding="utf-8")
        assert gsv.task_is_high_risk(p, "simple plan") is False

    def test_none_path(self):
        assert gsv.task_is_high_risk(None, "security concern") is True

    def test_none_path_no_risk(self):
        assert gsv.task_is_high_risk(None, "normal plan") is False


# ─────────────────────────────────────────────
# validate_research_citations
# ─────────────────────────────────────────────

class TestExtractTaskInlineFlags:
    def test_basic(self):
        text = "- lightweight: true\n- premortem: required\n"
        flags = gsv.extract_task_inline_flags(text)
        assert flags["lightweight"] == "true"
        assert flags["premortem"] == "required"

    def test_empty(self):
        assert gsv.extract_task_inline_flags("no flags here") == {}


# ─────────────────────────────────────────────
# default_next_agent_for_state
# ─────────────────────────────────────────────

class TestPrintResult:
    def test_ok(self, capsys):
        gsv.print_result(gsv.ValidationResult([], []))
        captured = capsys.readouterr()
        assert "[OK]" in captured.out

    def test_error(self, capsys):
        gsv.print_result(gsv.ValidationResult(["err"], ["warn"]))
        captured = capsys.readouterr()
        assert "[ERROR]" in captured.out
        assert "[WARN]" in captured.out
        assert "[FAIL]" in captured.out

    def test_override_active(self, capsys):
        gsv.print_result(gsv.ValidationResult([], []), override_active=True)
        captured = capsys.readouterr()
        assert "[OVERRIDE ACTIVE]" in captured.out

    def test_waivers_shown(self, capsys):
        gsv.print_result(gsv.ValidationResult([], [], active_waivers=["A", "B"]))
        captured = capsys.readouterr()
        assert "[WAIVER ACTIVE gate=A]" in captured.out


# ─────────────────────────────────────────────
# Phase 2: High-impact coverage expansion
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# load_archive_snapshot
# ─────────────────────────────────────────────

class TestSummarizeRemoteErrorDetail_v2:
    def test_with_body(self):
        result = gsv.summarize_remote_error_detail(b"error message", "fallback")
        assert "error message" in result

    def test_empty_body(self):
        result = gsv.summarize_remote_error_detail(b"", "fallback")
        assert result == "fallback"

    def test_long_body_truncated(self):
        body = b"x" * 300
        result = gsv.summarize_remote_error_detail(body, "fallback")
        assert result.endswith("...")
        assert len(result) <= 204


# ─────────────────────────────────────────────
# compute_snapshot_sha256 & parse_csv_file_tokens
# ─────────────────────────────────────────────

class TestComputeSnapshotSha256_v2:
    def test_deterministic(self):
        files = {"a.py", "b.py"}
        h1 = gsv.compute_snapshot_sha256(files)
        h2 = gsv.compute_snapshot_sha256(files)
        assert h1 == h2
        assert len(h1) == 64

class TestParseCsvFileTokens_v2:
    def test_comma_separated(self):
        result = gsv.parse_csv_file_tokens("a.py, b.py, c.py")
        assert result == {"a.py", "b.py", "c.py"}

    def test_empty(self):
        result = gsv.parse_csv_file_tokens("")
        assert result == set()


# ─────────────────────────────────────────────
# parse_repository_ref & normalize_api_base_url
# ─────────────────────────────────────────────

class TestParseRepositoryRef_v2:
    def test_valid(self):
        owner, repo, err = gsv.parse_repository_ref("user/repo")
        assert owner == "user"
        assert repo == "repo"
        assert err is None

    def test_invalid(self):
        owner, repo, err = gsv.parse_repository_ref("invalid")
        assert err is not None

class TestNormalizeApiBaseUrl_v2:
    def test_default(self):
        url, err = gsv.normalize_api_base_url("")
        assert url == "https://api.github.com"
        assert err is None

    def test_custom_requires_allowlist(self):
        url, err = gsv.normalize_api_base_url("https://custom.api.com/")
        assert url is None
        assert "not allowed" in err
        assert gsv.GITHUB_API_ALLOWED_HOSTS_ENV in err

    def test_custom_allowlisted(self):
        with patch.dict(os.environ, {gsv.GITHUB_API_ALLOWED_HOSTS_ENV: "custom.api.com"}, clear=False):
            url, err = gsv.normalize_api_base_url("https://custom.api.com/")
        assert url == "https://custom.api.com"
        assert err is None

    def test_missing_hostname(self):
        url, err = gsv.normalize_api_base_url("https://:443")
        assert url is None
        assert "must include a hostname" in err


# ─────────────────────────────────────────────
# resolve_workspace_relative_path
# ─────────────────────────────────────────────

class TestResolveWorkspaceRelativePath_v2:
    def test_valid(self, tmp_path):
        (tmp_path / "file.txt").write_text("content", encoding="utf-8")
        rel, path, err = gsv.resolve_workspace_relative_path(tmp_path, "file.txt")
        assert err is None
        assert path.exists()

    def test_traversal_blocked(self, tmp_path):
        rel, path, err = gsv.resolve_workspace_relative_path(tmp_path, "../../../etc/passwd")
        assert err is not None


# ─────────────────────────────────────────────
# classify_decision_waiver_gate
# ─────────────────────────────────────────────

class TestTaskIsHighRisk_v2:
    def test_security_keyword(self, tmp_path):
        task = tmp_path / "task.md"
        task.write_text("# Task: Security Fix\nFix security vulnerability\n", encoding="utf-8")
        assert gsv.task_is_high_risk(task, "")

    def test_no_risk(self, tmp_path):
        task = tmp_path / "task.md"
        task.write_text("# Task: Update docs\nMinor update\n", encoding="utf-8")
        assert not gsv.task_is_high_risk(task, "")

    def test_plan_text_risk(self):
        assert gsv.task_is_high_risk(None, "This involves upstream PR changes")

class TestExtractTaskTitle_v2:
    def test_valid(self, tmp_path):
        p = tmp_path / "task.md"
        p.write_text("# Task: My Title\nContent\n", encoding="utf-8")
        assert gsv.extract_task_title(p) == "My Title"

    def test_no_match(self, tmp_path):
        p = tmp_path / "task.md"
        p.write_text("# Not a task\n", encoding="utf-8")
        assert gsv.extract_task_title(p) == ""

    def test_none_path(self):
        assert gsv.extract_task_title(None) == ""


# ═════════════════════════════════════════════
# Phase 3: 90%+ coverage expansion
# ═════════════════════════════════════════════


# ─────────────────────────────────────────────
# build_decision_registry — extract_decision_type
# ─────────────────────────────────────────────

class TestGsvParseTaipeiDatetime:
    def test_valid(self):
        result = gsv.parse_taipei_datetime("2026-01-15T10:00:00+08:00")
        assert result is not None

    def test_invalid_format(self):
        assert gsv.parse_taipei_datetime("not-a-date") is None

    def test_value_error_branch(self):
        # Matches the pattern but fails fromisoformat
        assert gsv.parse_taipei_datetime("9999-99-99T00:00:00+08:00") is None

class TestGsvNormalizePathToken:
    def test_drive_letter(self):
        assert gsv.normalize_path_token("C:/Users/test") == "/Users/test"

    def test_dot_slash(self):
        # normalize_path_token strips "./" → value becomes "/src/main.py" after strip
        result = gsv.normalize_path_token("./src/main.py")
        assert "src/main.py" in result

    def test_git_diff_prefix(self):
        assert gsv.normalize_path_token("a/src/main.py") == "src/main.py"
        assert gsv.normalize_path_token("b/src/main.py") == "src/main.py"

    def test_backtick_strip(self):
        assert gsv.normalize_path_token("`src/main.py`") == "src/main.py"

class TestGsvResolveWorkspaceRelativePath:
    def test_empty(self, tmp_path):
        _, _, error = gsv.resolve_workspace_relative_path(tmp_path, "")
        assert error is not None

    def test_traversal(self, tmp_path):
        _, _, error = gsv.resolve_workspace_relative_path(tmp_path, "../outside")
        assert error is not None

    def test_valid(self, tmp_path):
        (tmp_path / "test.txt").write_text("x", encoding="utf-8")
        rel, resolved, error = gsv.resolve_workspace_relative_path(tmp_path, "test.txt")
        assert error is None
        assert rel == "test.txt"

    def test_absolute_path(self, tmp_path):
        _, _, error = gsv.resolve_workspace_relative_path(tmp_path, "/etc/passwd")
        assert error is not None

class TestGsvParseRepositoryRef:
    def test_valid(self):
        owner, repo, error = gsv.parse_repository_ref("owner/repo")
        assert owner == "owner"
        assert repo == "repo"
        assert error is None

    def test_invalid(self):
        _, _, error = gsv.parse_repository_ref("no-slash")
        assert error is not None

    def test_dotdot(self):
        _, _, error = gsv.parse_repository_ref("../foo")
        assert error is not None

class TestGsvNormalizeApiBaseUrl:
    def test_default(self):
        url, error = gsv.normalize_api_base_url("")
        assert url == "https://api.github.com"
        assert error is None

    def test_custom(self, monkeypatch):
        monkeypatch.setenv(gsv.GITHUB_API_ALLOWED_HOSTS_ENV, "github.example.com")
        url, error = gsv.normalize_api_base_url("https://github.example.com/api/v3/")
        assert url == "https://github.example.com/api/v3"
        assert error is None

    def test_invalid(self):
        _, error = gsv.normalize_api_base_url("ftp://invalid")
        assert error is not None

class TestGsvStatusUsesLegacySchema:
    def test_legacy(self):
        assert gsv.status_uses_legacy_schema({"current_state": "drafted"})

    def test_modern(self):
        assert not gsv.status_uses_legacy_schema({"state": "drafted"})

class TestGsvSummarizeRemoteErrorDetail:
    def test_with_body(self):
        result = gsv.summarize_remote_error_detail(b"error details here", "fallback")
        assert "error details" in result

    def test_empty_body(self):
        result = gsv.summarize_remote_error_detail(b"", "fallback")
        assert result == "fallback"

    def test_long_body_truncated(self):
        result = gsv.summarize_remote_error_detail(b"x" * 300, "fallback")
        assert len(result) <= 210
        assert result.endswith("...")

class TestGsvParseDiffEvidence:
    def test_none(self):
        assert gsv.parse_diff_evidence("no diff evidence section") is None

    def test_with_evidence(self):
        text = "## Diff Evidence\n- Evidence Type: commit-range\n- Base Commit: abc\n"
        result = gsv.parse_diff_evidence(text)
        assert result is not None
        assert result.get("evidence type") == "commit-range"

class TestGsvNormalizePathTokenDriveLetter:
    def test_drive_letter_stripped(self):
        assert gsv.normalize_path_token("C:/src/main.py") == "/src/main.py"

    def test_lowercase_drive_letter(self):
        assert gsv.normalize_path_token("d:/foo/bar.py") == "/foo/bar.py"

    def test_backslash_drive_letter(self):
        assert gsv.normalize_path_token("C:\\src\\main.py") == "/src/main.py"

class TestGsvPrintResult:
    def test_ok_result(self, capsys):
        result = gsv.ValidationResult([], [])
        gsv.print_result(result)
        captured = capsys.readouterr()
        assert "[OK]" in captured.out

    def test_error_result(self, capsys):
        result = gsv.ValidationResult(["some error"], ["some warning"])
        gsv.print_result(result)
        captured = capsys.readouterr()
        assert "[ERROR]" in captured.out
        assert "[FAIL]" in captured.out
        assert "[WARN]" in captured.out

    def test_override_active(self, capsys):
        result = gsv.ValidationResult([], [])
        gsv.print_result(result, override_active=True)
        captured = capsys.readouterr()
        assert "[OVERRIDE ACTIVE]" in captured.out

class TestGsvMainFunction:
    def test_basic_validate(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        exit_code = gsv.main(["--task-id", "TASK-001", "--artifacts-root", str(tmp_path)])
        assert exit_code == 0

    def test_write_transition(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        sp = tmp_path / "status" / "TASK-001.status.json"
        s = json.loads(sp.read_text(encoding="utf-8"))
        s["state"] = "verifying"
        sp.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        exit_code = gsv.main([
            "--task-id", "TASK-001",
            "--artifacts-root", str(tmp_path),
            "--write-transition", "verifying", "done",
            "--allow-scope-drift",
        ])
        assert exit_code == 0

    def test_strict_and_allow_conflict(self, tmp_path):
        exit_code = gsv.main([
            "--task-id", "TASK-001",
            "--artifacts-root", str(tmp_path),
            "--strict-scope", "--allow-scope-drift",
        ])
        assert exit_code == 2

    def test_override_without_approver(self, tmp_path):
        exit_code = gsv.main([
            "--task-id", "TASK-001",
            "--artifacts-root", str(tmp_path),
            "--override", "reason",
        ])
        assert exit_code == 2

    def test_reconcile_mode(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        exit_code = gsv.main(["--task-id", "TASK-001", "--artifacts-root", str(tmp_path), "--reconcile"])
        assert exit_code == 0

class TestGsvComputeSnapshotSha256:
    def test_deterministic(self):
        files = {"b.py", "a.py"}
        h1 = gsv.compute_snapshot_sha256(files)
        h2 = gsv.compute_snapshot_sha256(files)
        assert h1 == h2
        assert len(h1) == 64

class TestGsvResolveWorkspaceRelativePath_v2:
    def test_relative_path(self, tmp_path):
        target = tmp_path / "src" / "main.py"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")
        rel, resolved, err = gsv.resolve_workspace_relative_path(tmp_path, "src/main.py")
        assert rel == "src/main.py"
        assert err is None

    def test_empty_path(self, tmp_path):
        rel, resolved, err = gsv.resolve_workspace_relative_path(tmp_path, "")
        assert rel is None
        assert err is not None

    def test_path_traversal(self, tmp_path):
        rel, resolved, err = gsv.resolve_workspace_relative_path(tmp_path, "../escape")
        assert err is not None

class TestGsvParseRepositoryRef_v2:
    def test_valid(self):
        owner, repo, err = gsv.parse_repository_ref("user/myrepo")
        assert owner == "user"
        assert repo == "myrepo"
        assert err is None

    def test_invalid(self):
        owner, repo, err = gsv.parse_repository_ref("invalid-format")
        assert err is not None

class TestGsvNormalizeApiBaseUrl_v2:
    def test_default(self):
        url, err = gsv.normalize_api_base_url("")
        assert url == "https://api.github.com"
        assert err is None

    def test_custom_url_requires_allowlist(self):
        url, err = gsv.normalize_api_base_url("https://github.example.com/api/v3")
        assert url is None
        assert "not allowed" in err

    def test_custom_url_allowlisted(self):
        with patch.dict(os.environ, {gsv.GITHUB_API_ALLOWED_HOSTS_ENV: "github.example.com"}, clear=False):
            url, err = gsv.normalize_api_base_url("https://github.example.com/api/v3")
        assert url == "https://github.example.com/api/v3"
        assert err is None

    def test_invalid_scheme(self):
        url, err = gsv.normalize_api_base_url("ftp://invalid.com")
        assert url is None
        assert err is not None

    def test_trailing_slash_stripped(self):
        url, err = gsv.normalize_api_base_url("https://api.github.com/")
        assert url == "https://api.github.com"

class TestGsvStatusUsesLegacySchema_v2:
    def test_modern(self):
        assert not gsv.status_uses_legacy_schema({"state": "coding"})

    def test_legacy(self):
        assert gsv.status_uses_legacy_schema({"current_state": "drafted"})

    def test_both(self):
        assert not gsv.status_uses_legacy_schema({"state": "coding", "current_state": "drafted"})


# ── Phase 4c: targeted coverage for remaining uncovered lines ──

class TestGsvNormalizePathTokenDiffPrefix:
    """Cover line 305: a/ and b/ prefix stripping."""
    def test_a_prefix(self):
        assert gsv.normalize_path_token("a/src/main.py") == "src/main.py"

    def test_b_prefix(self):
        assert gsv.normalize_path_token("b/src/main.py") == "src/main.py"

    def test_dot_slash_stripped_by_outer_strip(self):
        # The . in ./ is consumed by the special-char strip, so ./ branch is unreachable
        assert gsv.normalize_path_token("./src/main.py") == "/src/main.py"

class TestGsvResolveWorkspaceRelativePathEdgeCases:
    """Cover lines 362-363, 376-377, 380-381, 390."""
    def test_absolute_posix_path_rejected(self, tmp_path):
        rel, resolved, err = gsv.resolve_workspace_relative_path(tmp_path, "/etc/passwd")
        assert err is not None
        assert "repository root" in err

    def test_dotdot_path_rejected(self, tmp_path):
        rel, resolved, err = gsv.resolve_workspace_relative_path(tmp_path, "foo/../../escape")
        assert err is not None

    def test_valid_nested_path(self, tmp_path):
        target = tmp_path / "src" / "lib.py"
        target.parent.mkdir(parents=True)
        target.write_text("x", encoding="utf-8")
        rel, resolved, err = gsv.resolve_workspace_relative_path(tmp_path, "src/lib.py")
        assert rel == "src/lib.py"
        assert resolved is not None
        assert err is None

class TestGsvExtractTaskTitleEdge:
    """Cover line 1261."""
    def test_no_match(self, tmp_path):
        p = tmp_path / "tasks" / "TASK-001.task.md"
        p.parent.mkdir(parents=True)
        p.write_text("Not a task heading\n", encoding="utf-8")
        result = gsv.extract_task_title(p)
        assert result == ""

    def test_none_path(self):
        assert gsv.extract_task_title(None) == ""

class TestGsvMainEntrypoint:
    """Cover lines 1544, 1556."""
    def test_main_validate_mode(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        rc = gsv.main(["--task-id", "TASK-001", "--artifacts-root", str(tmp_path)])
        assert rc == 0

    def test_main_transition_mode(self, tmp_path):
        _setup_valid_done_tree(tmp_path, "TASK-001")
        sp = tmp_path / "status" / "TASK-001.status.json"
        s = json.loads(sp.read_text(encoding="utf-8"))
        s["state"] = "verifying"
        s["available_artifacts"] = sorted(["task", "plan", "code", "verify", "research", "status"])
        s["required_artifacts"] = sorted(["task", "code", "verify", "research", "status"])
        sp.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rc = gsv.main(["--task-id", "TASK-001", "--artifacts-root", str(tmp_path), "--write-transition", "verifying", "done"])
        assert rc == 0

    def test_main_strict_and_allow_conflict(self):
        rc = gsv.main(["--task-id", "TASK-001", "--strict-scope", "--allow-scope-drift"])
        assert rc == 2

    def test_main_override_without_approver(self, tmp_path):
        rc = gsv.main(["--task-id", "TASK-001", "--artifacts-root", str(tmp_path), "--override", "reason"])
        assert rc == 2

class TestGsvResolveWorkspaceOSError:
    """Cover lines 380-381."""
    @unittest.mock.patch("pathlib.Path.resolve", side_effect=OSError("permission denied"))
    def test_os_error(self, mock_resolve):
        _, _, err = gsv.resolve_workspace_relative_path(Path("/repo"), "src/main.py")
        assert err is not None
        assert "permission" in err

class TestGsvTaskArtifactRelativePaths:
    """Cover lines 649-653."""
    def test_collects_artifact_paths(self, tmp_path):
        task_dir = tmp_path / "tasks"
        task_dir.mkdir()
        (task_dir / "TASK-001.task.md").write_text("# Task\n", encoding="utf-8")
        plan_dir = tmp_path / "plans"
        plan_dir.mkdir()
        (plan_dir / "TASK-001.plan.md").write_text("# Plan\n", encoding="utf-8")
        result = gsv.task_artifact_relative_paths(tmp_path, "TASK-001", tmp_path)
        assert "tasks/task-001.task.md" in result or any("task" in p for p in result)

    def test_outside_repo_root(self, tmp_path):
        artifacts_root = tmp_path / "artifacts"
        artifacts_root.mkdir()
        task_dir = artifacts_root / "tasks"
        task_dir.mkdir()
        (task_dir / "TASK-001.task.md").write_text("# Task\n", encoding="utf-8")
        other_root = tmp_path / "other"
        other_root.mkdir()
        result = gsv.task_artifact_relative_paths(artifacts_root, "TASK-001", other_root)
        # paths outside repo_root should be skipped (ValueError branch)
        assert len(result) == 0

class TestGsvParseRepositoryRefDotSegments:
    """Cover line 390 — dot/dotdot owner/repo segments."""
    def test_dot_owner(self):
        _owner, _repo, err = gsv.parse_repository_ref("./myrepo")
        assert err == "Repository owner/repo segments must be concrete names"

    def test_dotdot_repo(self):
        _owner, _repo, err = gsv.parse_repository_ref("owner/..")
        assert err == "Repository owner/repo segments must be concrete names"

    def test_dot_repo(self):
        _owner, _repo, err = gsv.parse_repository_ref("owner/.")
        assert err == "Repository owner/repo segments must be concrete names"

    def test_dotdot_owner(self):
        _owner, _repo, err = gsv.parse_repository_ref("../repo")
        assert err == "Repository owner/repo segments must be concrete names"

class TestGsvResolveWorkspacePathEscape:
    """Cover lines 380-381 — resolved path escapes repository root."""
    def test_path_escape_via_resolve(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        original_resolve = Path.resolve
        call_count = [0]
        def patched_resolve(self_path, strict=False):
            call_count[0] += 1
            if call_count[0] == 2:
                return Path("/outside/repo/dir")
            return original_resolve(self_path, strict=strict) if strict else original_resolve(self_path)
        with unittest.mock.patch.object(Path, "resolve", patched_resolve):
            _rel, _resolved, err = gsv.resolve_workspace_relative_path(repo, "some/path")
        assert err == "path escapes repository root"

class TestGsvPremortemHighRiskWarning:
    """Cover line 1261 — high-risk warning when min_critical=0 and no blocking risks."""
    def test_hotfix_with_security_keyword_no_blocking(self, tmp_path):
        # hotfix policy → min_critical=0, min_risks=1
        task_path = tmp_path / "tasks" / "TASK-001.task.md"
        task_path.parent.mkdir(parents=True)
        task_path.write_text(
            "# Task: hotfix fix security issue\n## Metadata\n- Task ID: TASK-001\n",
            encoding="utf-8",
        )
        plan_path = tmp_path / "plans" / "TASK-001.plan.md"
        plan_path.parent.mkdir(parents=True)
        plan_text = (
            "# Plan\n## Metadata\n- Task ID: TASK-001\n"
            "## Risks\n"
            "R1: Regression risk\n"
            "- Risk: May break other features\n"
            "- Trigger: When deployed\n"
            "- Detection: Monitoring\n"
            "- Mitigation: Rollback\n"
            "- Severity: non-blocking\n"
            "## Ready For Coding\nyes\n"
        )
        plan_path.write_text(plan_text, encoding="utf-8")
        result = gsv.validate_premortem(plan_path, task_path)
        assert any("high-risk signals" in w for w in result.warnings)

class TestGsvHistoricalDriftGithubPrBranch:
    """Cover lines 722-733 — github-pr evidence branch."""

    def test_missing_repository(self, tmp_path):
        """L722-723: Missing repository field."""
        code_path = _make_diff_evidence_code(
            tmp_path, "github-pr", {"src/main.py"},
            {"PR Number": "42"},
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("requires non-empty Repository" in e for e in result.errors)

    def test_missing_pr_number(self, tmp_path):
        """L722-723: Missing PR Number field."""
        code_path = _make_diff_evidence_code(
            tmp_path, "github-pr", {"src/main.py"},
            {"Repository": "owner/repo"},
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("requires non-empty Repository" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "collect_github_pr_files")
    def test_provider_error(self, mock_collect, tmp_path):
        """L724-727: Provider returns error."""
        mock_collect.return_value = (set(), "HTTP 403 forbidden")
        code_path = _make_diff_evidence_code(
            tmp_path, "github-pr", {"src/main.py"},
            {"Repository": "owner/repo", "PR Number": "42"},
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("evidence fetch failed" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "collect_github_pr_files")
    def test_provider_snapshot_mismatch(self, mock_collect, tmp_path):
        """L729-732: Provider files != snapshot."""
        mock_collect.return_value = ({"src/main.py", "src/other.py"}, None)
        code_path = _make_diff_evidence_code(
            tmp_path, "github-pr", {"src/main.py"},
            {"Repository": "owner/repo", "PR Number": "42"},
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("does not match github-pr provider" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "collect_github_pr_files")
    def test_provider_match_happy_path(self, mock_collect, tmp_path):
        """L733: Provider matches → compare_reconstructed_scope."""
        mock_collect.return_value = ({"src/main.py"}, None)
        code_path = _make_diff_evidence_code(
            tmp_path, "github-pr", {"src/main.py"},
            {"Repository": "owner/repo", "PR Number": "42"},
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert not result.errors


_FAKE_BASE = "a" * 40
_FAKE_HEAD = "b" * 40

class TestGsvHistoricalDriftCommitRangeBranch:
    """Cover lines 735-786 — commit-range evidence branch."""

    def _make_commit_range_code(self, tmp_path, snapshot_files, base=_FAKE_BASE, head=_FAKE_HEAD,
                                diff_cmd="git diff --name-only", base_ref="", head_ref="",
                                archive_path="", archive_sha256=""):
        extra = {
            "Base Commit": base,
            "Head Commit": head,
            "Diff Command": diff_cmd,
        }
        if base_ref:
            extra["Base Ref"] = base_ref
        if head_ref:
            extra["Head Ref"] = head_ref
        if archive_path:
            extra["Archive Path"] = archive_path
        if archive_sha256:
            extra["Archive SHA256"] = archive_sha256
        return _make_diff_evidence_code(tmp_path, "commit-range", snapshot_files, extra)

    def test_no_repo_root(self, tmp_path):
        """L735-736: repo_root is None."""
        code_path = self._make_commit_range_code(tmp_path, {"src/main.py"})
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(None, plan_path, code_path)
        assert not result.errors  # silently returns empty

    def test_missing_base_commit(self, tmp_path):
        """L742-746: Missing base commit."""
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, base="", head=_FAKE_HEAD
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("requires non-empty Base Commit" in e for e in result.errors)

    def test_missing_diff_command(self, tmp_path):
        """L742-746: Missing diff command."""
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, diff_cmd=""
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("requires non-empty" in e for e in result.errors)

    def test_invalid_sha_format(self, tmp_path):
        """L747-749: Non-40-char hex SHA."""
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, base="short", head=_FAKE_HEAD
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("40-character git commit SHAs" in e for e in result.errors)

    def test_archive_error(self, tmp_path):
        """L750-753: load_archive_snapshot returns error."""
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"},
            archive_path="missing.txt", archive_sha256="c" * 64,
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("does not exist" in e or "Archive" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "resolve_git_revision_commit")
    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_base_ref_error(self, mock_diff, mock_resolve, tmp_path):
        """L755-757: Base ref resolution error."""
        mock_resolve.return_value = (None, "unknown revision")
        mock_diff.return_value = ({"src/main.py"}, None)
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, base_ref="main"
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("Base Ref" in w and "no longer resolves" in w for w in result.warnings)

    @unittest.mock.patch.object(gsv, "resolve_git_revision_commit")
    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_base_ref_mismatch(self, mock_diff, mock_resolve, tmp_path):
        """L758-761: Base ref resolves to different commit."""
        mock_resolve.return_value = ("c" * 40, None)
        mock_diff.return_value = ({"src/main.py"}, None)
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, base_ref="main"
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("Base Ref" in w and "not pinned" in w for w in result.warnings)

    @unittest.mock.patch.object(gsv, "resolve_git_revision_commit")
    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_head_ref_error(self, mock_diff, mock_resolve, tmp_path):
        """L764-765: Head ref resolution error."""
        # First call (base_ref) → not called (no base_ref)
        # For head_ref only:
        mock_resolve.return_value = (None, "unknown revision")
        mock_diff.return_value = ({"src/main.py"}, None)
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, head_ref="feature"
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("Head Ref" in w and "no longer resolves" in w for w in result.warnings)

    @unittest.mock.patch.object(gsv, "resolve_git_revision_commit")
    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_head_ref_mismatch(self, mock_diff, mock_resolve, tmp_path):
        """L766-769: Head ref resolves to different commit."""
        mock_resolve.return_value = ("d" * 40, None)
        mock_diff.return_value = ({"src/main.py"}, None)
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, head_ref="feature"
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("Head Ref" in w and "not pinned" in w for w in result.warnings)

    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_diff_error_no_archive(self, mock_diff, tmp_path):
        """L773-775: Diff error without archive fallback."""
        mock_diff.return_value = (set(), "fatal: bad revision")
        code_path = self._make_commit_range_code(tmp_path, {"src/main.py"})
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("diff replay failed" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_diff_error_with_archive_fallback(self, mock_diff, tmp_path):
        """L776-780: Diff error with archive fallback."""
        import hashlib
        archive_content = "src/main.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(archive_content.encode("utf-8"))
        archive_sha = hashlib.sha256(archive_content.encode("utf-8")).hexdigest()
        mock_diff.return_value = (set(), "fatal: bad revision")
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"},
            archive_path="archive.txt", archive_sha256=archive_sha,
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        # Should use archive fallback, not error
        assert not result.errors
        assert any("archive fallback" in w for w in result.warnings)

    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_diff_changed_mismatch(self, mock_diff, tmp_path):
        """L781-786: Diff result doesn't match snapshot."""
        mock_diff.return_value = ({"src/main.py", "src/other.py"}, None)
        code_path = self._make_commit_range_code(tmp_path, {"src/main.py"})
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("does not match" in e and "replayed" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_happy_path_no_drift(self, mock_diff, tmp_path):
        """Happy path: diff matches snapshot, files planned → no drift."""
        mock_diff.return_value = ({"src/main.py"}, None)
        code_path = self._make_commit_range_code(tmp_path, {"src/main.py"})
        # code artifact needs ## Files Changed too
        with open(code_path, "a", encoding="utf-8") as f:
            f.write("\n## Files Changed\n- `src/main.py`\n")
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert not result.errors

    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_archive_fallback_mismatch(self, mock_diff, tmp_path):
        """L782: archive fallback mismatch label in error."""
        import hashlib
        archive_content = "src/different.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(archive_content.encode("utf-8"))
        archive_sha = hashlib.sha256(archive_content.encode("utf-8")).hexdigest()
        mock_diff.return_value = (set(), "fatal: bad revision")
        # Snapshot has src/main.py but archive has src/different.py
        # But wait — archive must match snapshot for load_archive_snapshot to succeed
        # So this test is about diff_changed (from archive) != snapshot
        # That can't happen if archive == snapshot (load_archive checks this)
        # The mismatch happens when archive loads OK but diff replayed from archive
        # still doesn't match. Actually the archive_files == snapshot_files check
        # would prevent this case from ever hitting line 782 via archive fallback.
        # Line 782 with archive fallback label can only be reached if archive_files
        # IS the snapshot (passes load_archive) but somehow diff_changed is different.
        # Since in the fallback path diff_changed = archive_files = snapshot_files,
        # the check `diff_changed != snapshot_files` is always False → line 782 unreachable
        # in the archive fallback path. But line 782 IS reachable in the normal diff path
        # (scope_label = "commit-range scope check") via the test_diff_changed_mismatch above.
        pass  # This specific sub-case is unreachable via archive fallback


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

class TestGsvHistoricalDriftGithubPrBranch_v2:
    """Cover lines 722-733 — github-pr evidence branch."""

    def test_missing_repository(self, tmp_path):
        """L722-723: Missing repository field."""
        code_path = _make_diff_evidence_code(
            tmp_path, "github-pr", {"src/main.py"},
            {"PR Number": "42"},
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("requires non-empty Repository" in e for e in result.errors)

    def test_missing_pr_number(self, tmp_path):
        """L722-723: Missing PR Number field."""
        code_path = _make_diff_evidence_code(
            tmp_path, "github-pr", {"src/main.py"},
            {"Repository": "owner/repo"},
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("requires non-empty Repository" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "collect_github_pr_files")
    def test_provider_error(self, mock_collect, tmp_path):
        """L724-727: Provider returns error."""
        mock_collect.return_value = (set(), "HTTP 403 forbidden")
        code_path = _make_diff_evidence_code(
            tmp_path, "github-pr", {"src/main.py"},
            {"Repository": "owner/repo", "PR Number": "42"},
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("evidence fetch failed" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "collect_github_pr_files")
    def test_provider_snapshot_mismatch(self, mock_collect, tmp_path):
        """L729-732: Provider files != snapshot."""
        mock_collect.return_value = ({"src/main.py", "src/other.py"}, None)
        code_path = _make_diff_evidence_code(
            tmp_path, "github-pr", {"src/main.py"},
            {"Repository": "owner/repo", "PR Number": "42"},
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("does not match github-pr provider" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "collect_github_pr_files")
    def test_provider_match_happy_path(self, mock_collect, tmp_path):
        """L733: Provider matches → compare_reconstructed_scope."""
        mock_collect.return_value = ({"src/main.py"}, None)
        code_path = _make_diff_evidence_code(
            tmp_path, "github-pr", {"src/main.py"},
            {"Repository": "owner/repo", "PR Number": "42"},
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert not result.errors


_FAKE_BASE = "a" * 40
_FAKE_HEAD = "b" * 40

class TestGsvHistoricalDriftCommitRangeBranch_v2:
    """Cover lines 735-786 — commit-range evidence branch."""

    def _make_commit_range_code(self, tmp_path, snapshot_files, base=_FAKE_BASE, head=_FAKE_HEAD,
                                diff_cmd="git diff --name-only", base_ref="", head_ref="",
                                archive_path="", archive_sha256=""):
        extra = {
            "Base Commit": base,
            "Head Commit": head,
            "Diff Command": diff_cmd,
        }
        if base_ref:
            extra["Base Ref"] = base_ref
        if head_ref:
            extra["Head Ref"] = head_ref
        if archive_path:
            extra["Archive Path"] = archive_path
        if archive_sha256:
            extra["Archive SHA256"] = archive_sha256
        return _make_diff_evidence_code(tmp_path, "commit-range", snapshot_files, extra)

    def test_no_repo_root(self, tmp_path):
        """L735-736: repo_root is None."""
        code_path = self._make_commit_range_code(tmp_path, {"src/main.py"})
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(None, plan_path, code_path)
        assert not result.errors  # silently returns empty

    def test_missing_base_commit(self, tmp_path):
        """L742-746: Missing base commit."""
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, base="", head=_FAKE_HEAD
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("requires non-empty Base Commit" in e for e in result.errors)

    def test_missing_diff_command(self, tmp_path):
        """L742-746: Missing diff command."""
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, diff_cmd=""
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("requires non-empty" in e for e in result.errors)

    def test_invalid_sha_format(self, tmp_path):
        """L747-749: Non-40-char hex SHA."""
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, base="short", head=_FAKE_HEAD
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("40-character git commit SHAs" in e for e in result.errors)

    def test_archive_error(self, tmp_path):
        """L750-753: load_archive_snapshot returns error."""
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"},
            archive_path="missing.txt", archive_sha256="c" * 64,
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("does not exist" in e or "Archive" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "resolve_git_revision_commit")
    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_base_ref_error(self, mock_diff, mock_resolve, tmp_path):
        """L755-757: Base ref resolution error."""
        mock_resolve.return_value = (None, "unknown revision")
        mock_diff.return_value = ({"src/main.py"}, None)
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, base_ref="main"
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("Base Ref" in w and "no longer resolves" in w for w in result.warnings)

    @unittest.mock.patch.object(gsv, "resolve_git_revision_commit")
    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_base_ref_mismatch(self, mock_diff, mock_resolve, tmp_path):
        """L758-761: Base ref resolves to different commit."""
        mock_resolve.return_value = ("c" * 40, None)
        mock_diff.return_value = ({"src/main.py"}, None)
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, base_ref="main"
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("Base Ref" in w and "not pinned" in w for w in result.warnings)

    @unittest.mock.patch.object(gsv, "resolve_git_revision_commit")
    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_head_ref_error(self, mock_diff, mock_resolve, tmp_path):
        """L764-765: Head ref resolution error."""
        # First call (base_ref) → not called (no base_ref)
        # For head_ref only:
        mock_resolve.return_value = (None, "unknown revision")
        mock_diff.return_value = ({"src/main.py"}, None)
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, head_ref="feature"
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("Head Ref" in w and "no longer resolves" in w for w in result.warnings)

    @unittest.mock.patch.object(gsv, "resolve_git_revision_commit")
    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_head_ref_mismatch(self, mock_diff, mock_resolve, tmp_path):
        """L766-769: Head ref resolves to different commit."""
        mock_resolve.return_value = ("d" * 40, None)
        mock_diff.return_value = ({"src/main.py"}, None)
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"}, head_ref="feature"
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("Head Ref" in w and "not pinned" in w for w in result.warnings)

    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_diff_error_no_archive(self, mock_diff, tmp_path):
        """L773-775: Diff error without archive fallback."""
        mock_diff.return_value = (set(), "fatal: bad revision")
        code_path = self._make_commit_range_code(tmp_path, {"src/main.py"})
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("diff replay failed" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_diff_error_with_archive_fallback(self, mock_diff, tmp_path):
        """L776-780: Diff error with archive fallback."""
        import hashlib
        archive_content = "src/main.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(archive_content.encode("utf-8"))
        archive_sha = hashlib.sha256(archive_content.encode("utf-8")).hexdigest()
        mock_diff.return_value = (set(), "fatal: bad revision")
        code_path = self._make_commit_range_code(
            tmp_path, {"src/main.py"},
            archive_path="archive.txt", archive_sha256=archive_sha,
        )
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        # Should use archive fallback, not error
        assert not result.errors
        assert any("archive fallback" in w for w in result.warnings)

    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_diff_changed_mismatch(self, mock_diff, tmp_path):
        """L781-786: Diff result doesn't match snapshot."""
        mock_diff.return_value = ({"src/main.py", "src/other.py"}, None)
        code_path = self._make_commit_range_code(tmp_path, {"src/main.py"})
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert any("does not match" in e and "replayed" in e for e in result.errors)

    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_happy_path_no_drift(self, mock_diff, tmp_path):
        """Happy path: diff matches snapshot, files planned → no drift."""
        mock_diff.return_value = ({"src/main.py"}, None)
        code_path = self._make_commit_range_code(tmp_path, {"src/main.py"})
        # code artifact needs ## Files Changed too
        with open(code_path, "a", encoding="utf-8") as f:
            f.write("\n## Files Changed\n- `src/main.py`\n")
        plan_path = tmp_path / "plan.md"
        plan_path.write_text("## Files Likely Affected\n- `src/main.py`\n", encoding="utf-8")
        result = gsv.detect_historical_diff_scope_drift(tmp_path, plan_path, code_path)
        assert not result.errors

    @unittest.mock.patch.object(gsv, "collect_git_diff_range_files")
    def test_archive_fallback_mismatch(self, mock_diff, tmp_path):
        """L782: archive fallback mismatch label in error."""
        import hashlib
        archive_content = "src/different.py\n"
        archive = tmp_path / "archive.txt"
        archive.write_bytes(archive_content.encode("utf-8"))
        archive_sha = hashlib.sha256(archive_content.encode("utf-8")).hexdigest()
        mock_diff.return_value = (set(), "fatal: bad revision")
        # Snapshot has src/main.py but archive has src/different.py
        # But wait — archive must match snapshot for load_archive_snapshot to succeed
        # So this test is about diff_changed (from archive) != snapshot
        # That can't happen if archive == snapshot (load_archive checks this)
        # The mismatch happens when archive loads OK but diff replayed from archive
        # still doesn't match. Actually the archive_files == snapshot_files check
        # would prevent this case from ever hitting line 782 via archive fallback.
        # Line 782 with archive fallback label can only be reached if archive_files
        # IS the snapshot (passes load_archive) but somehow diff_changed is different.
        # Since in the fallback path diff_changed = archive_files = snapshot_files,
        # the check `diff_changed != snapshot_files` is always False → line 782 unreachable
        # in the archive fallback path. But line 782 IS reachable in the normal diff path
        # (scope_label = "commit-range scope check") via the test_diff_changed_mismatch above.
        pass  # This specific sub-case is unreachable via archive fallback



# -- Phase 8: parse_args coverage for 4 modules --

class TestGuardStatusValidatorCoverageCatchup:
    def test_extract_single_line_section_empty_body(self):
        # Section with only whitespace content must yield empty string via line 413.
        text = "# T\n## Foo\n   \n \n"
        assert gsv.extract_single_line_section(text, "Foo") == ""

    def test_resolve_task_policy_uses_explicit_args(self):
        policy = gsv.resolve_task_policy(
            task_text="",
            status={},
            assurance_level="mvp",
            project_adapter="web-app",
        )
        assert policy["assurance_level"] == "mvp"
        assert policy["project_adapter"] == "web-app"

    def test_validate_status_schema_invalid_assurance_level(self):
        result = gsv.validate_status_schema(
            {
                "task_id": "TASK-X",
                "state": "drafted",
                "current_owner": "Claude",
                "next_agent": "Claude",
                "required_artifacts": [],
                "available_artifacts": [],
                "missing_artifacts": [],
                "blocked_reason": "",
                "last_updated": "2026-01-15T10:00:00+08:00",
                "assurance_level": "invalid",
                "project_adapter": "generic",
                "open_verification_debts": [],
                "verification_readiness": "poc",
            },
            "TASK-X",
        )
        assert any("assurance_level" in e for e in result.errors)

    def test_validate_status_schema_invalid_project_adapter(self):
        result = gsv.validate_status_schema(
            {
                "task_id": "TASK-X",
                "state": "drafted",
                "current_owner": "Claude",
                "next_agent": "Claude",
                "required_artifacts": [],
                "available_artifacts": [],
                "missing_artifacts": [],
                "blocked_reason": "",
                "last_updated": "2026-01-15T10:00:00+08:00",
                "assurance_level": "poc",
                "project_adapter": "invalid-adapter",
                "open_verification_debts": [],
                "verification_readiness": "poc",
            },
            "TASK-X",
        )
        assert any("project_adapter" in e for e in result.errors)

    def test_validate_status_schema_open_debts_not_list(self):
        result = gsv.validate_status_schema(
            {
                "task_id": "TASK-X",
                "state": "drafted",
                "current_owner": "Claude",
                "next_agent": "Claude",
                "required_artifacts": [],
                "available_artifacts": [],
                "missing_artifacts": [],
                "blocked_reason": "",
                "last_updated": "2026-01-15T10:00:00+08:00",
                "assurance_level": "poc",
                "project_adapter": "generic",
                "open_verification_debts": "not-a-list",
                "verification_readiness": "poc",
            },
            "TASK-X",
        )
        assert any("open_verification_debts" in e for e in result.errors)

    def test_validate_improvement_artifact_invalid_profile(self, tmp_path):
        path = tmp_path / "TASK-X.improvement.md"
        text = (
            "# Improvement: TASK-X\n"
            "## Metadata\n"
            "- Task ID: TASK-X\n"
            "- Source Task: TASK-X\n"
            "- Trigger Type: failure\n"
            "- Improvement Profile: bogus\n"
            "## 5. Preventive Action (System Level)\n"
            "action\n"
            "## 6. Validation\n"
            "v\n"
            "## 8. Final Rule\n"
            "r\n"
            "## 9. Status\n"
            "done\n"
        )
        path.write_text(text, encoding="utf-8")
        result = gsv.validate_improvement_artifact(text, path, "TASK-X")
        assert any("Improvement Profile" in e for e in result.errors)

    def test_validate_decision_artifact_invalid_class_and_gate(self, tmp_path):
        path = tmp_path / "TASK-X.decision.md"
        text = (
            "# Decision Log: TASK-X\n"
            "## Decision Class\n"
            "bogus-class\n"
            "## Affected Gate\n"
            "Gate_X\n"
            "## Expiry\n"
            "2026-01-15T10:00:00\n"
        )
        path.write_text(text, encoding="utf-8")
        result = gsv.validate_decision_artifact(text, path)
        assert any("Decision Class" in e for e in result.errors)
        assert any("Affected Gate" in e for e in result.errors)

    def test_validate_decision_artifact_missing_linked_artifacts_warning(self, tmp_path):
        path = tmp_path / "TASK-X.decision.md"
        text = (
            "# Decision Log: TASK-X\n"
            "## Decision Class\n"
            "risk-acceptance\n"
            "## Affected Gate\n"
            "Gate_D\n"
        )
        path.write_text(text, encoding="utf-8")
        result = gsv.validate_decision_artifact(text, path)
        assert any("Linked Artifacts" in w for w in result.warnings)

    def test_validate_decision_artifact_missing_affected_gate_warning(self, tmp_path):
        path = tmp_path / "TASK-X.decision.md"
        text = (
            "# Decision Log: TASK-X\n"
            "## Decision Class\n"
            "risk-acceptance\n"
            "## Scope\n"
            "Verification governance\n"
            "## Linked Artifacts\n"
            "- `artifacts/tasks/TASK-X.task.md`\n"
        )
        path.write_text(text, encoding="utf-8")
        result = gsv.validate_decision_artifact(text, path)
        assert any("missing ## Affected Gate" in w for w in result.warnings)

    def test_parse_verify_checklist_items_empty_section(self):
        assert gsv.parse_verify_checklist_items("") == []

    def test_validate_verify_checklist_bad_result(self, tmp_path):
        path = tmp_path / "TASK-X.verify.md"
        text = (
            "## Acceptance Criteria Checklist\n"
            "- **criterion**: C\n"
            "- **method**: M\n"
            "- **evidence**: E\n"
            "- **result**: bogus\n"
        )
        path.write_text(text, encoding="utf-8")
        result = gsv.validate_verify_checklist_schema(text, path, "poc", "generic")
        assert any("result must be one of" in e for e in result.errors)

    def test_validate_verify_checklist_unverified_without_decision_ref(self, tmp_path):
        path = tmp_path / "TASK-X.verify.md"
        text = (
            "## Acceptance Criteria Checklist\n"
            "- **criterion**: C\n"
            "- **method**: M\n"
            "- **evidence**: E\n"
            "- **result**: unverified\n"
        )
        path.write_text(text, encoding="utf-8")
        result = gsv.validate_verify_checklist_schema(text, path, "mvp", "generic")
        assert any("decision_ref or reason_code" in e for e in result.errors)

    def test_validate_verify_checklist_bad_reason_code(self, tmp_path):
        path = tmp_path / "TASK-X.verify.md"
        text = (
            "## Acceptance Criteria Checklist\n"
            "- **criterion**: C\n"
            "- **method**: M\n"
            "- **evidence**: E\n"
            "- **result**: verified\n"
            "- **reason_code**: ALIEN_CODE\n"
        )
        path.write_text(text, encoding="utf-8")
        result = gsv.validate_verify_checklist_schema(text, path, "poc", "generic")
        assert any("reason_code must be one of" in e for e in result.errors)

    def test_validate_verify_checklist_invalid_maturity(self, tmp_path):
        path = tmp_path / "TASK-X.verify.md"
        text = (
            "## Verification Summary\n"
            "sum\n"
            "## Acceptance Criteria Checklist\n"
            "- **criterion**: C\n"
            "- **method**: M\n"
            "- **evidence**: E\n"
            "- **result**: verified\n"
            "## Overall Maturity\n"
            "bogus-maturity\n"
            "## Deferred Items\n"
            "None\n"
            "## Pass Fail Result\n"
            "pass\n"
        )
        path.write_text(text, encoding="utf-8")
        result = gsv.validate_verify_checklist_schema(text, path, "poc", "generic")
        assert any("Overall Maturity" in e for e in result.errors)

    def test_validate_verify_checklist_maturity_mismatch(self, tmp_path):
        path = tmp_path / "TASK-X.verify.md"
        text = (
            "## Verification Summary\n"
            "sum\n"
            "## Acceptance Criteria Checklist\n"
            "- **criterion**: C\n"
            "- **method**: M\n"
            "- **evidence**: E\n"
            "- **result**: verified\n"
            "## Overall Maturity\n"
            "mvp\n"
            "## Deferred Items\n"
            "None\n"
            "## Pass Fail Result\n"
            "pass\n"
        )
        path.write_text(text, encoding="utf-8")
        result = gsv.validate_verify_checklist_schema(text, path, "poc", "generic")
        assert any("Overall Maturity mismatch" in w for w in result.warnings)

    def test_validate_markdown_artifact_task_with_invalid_profile(self, tmp_path, monkeypatch):
        task_path = tmp_path / "TASK-X.task.md"
        # Strict mode reads Assurance Level from raw text; write alien value directly so
        # the raw-text check fires. Project Adapter is checked via resolved value, so the
        # monkeypatch on resolve_project_adapter still drives that error path.
        text = (
            "# Task: TASK-X\n"
            "## Metadata\n"
            "- Task ID: TASK-X\n"
            "- Artifact Type: task\n"
            "- Owner: Claude\n"
            "- Status: approved\n"
            "- Last Updated: 2026-01-15T10:00:00+08:00\n"
            "## Assurance Level\n"
            "alien-level\n"
            "## Project Adapter\n"
            "generic\n"
            "## Acceptance Criteria\n"
            "Done\n"
        )
        task_path.write_text(text, encoding="utf-8")
        monkeypatch.setattr(gsv, "resolve_project_adapter", lambda *a, **kw: "alien-adapter")
        result = gsv.validate_markdown_artifact(task_path, "task", "TASK-X")
        assert any("is not a valid assurance level" in e for e in result.errors)
        assert any("invalid Project Adapter" in e for e in result.errors)

    def test_validate_markdown_artifact_plan_missing_verification_obligations(self, tmp_path):
        (tmp_path / "artifacts" / "plans").mkdir(parents=True)
        (tmp_path / "artifacts" / "tasks").mkdir(parents=True)
        (tmp_path / "artifacts" / "status").mkdir(parents=True)
        (tmp_path / "artifacts" / "tasks" / "TASK-X.task.md").write_text(
            (
                "# Task: TASK-X\n"
                "## Metadata\n"
                "- Task ID: TASK-X\n"
                "- Artifact Type: task\n"
                "- Owner: Claude\n"
                "- Status: approved\n"
                "- Last Updated: 2026-01-15T10:00:00+08:00\n"
                "## Assurance Level\n"
                "mvp\n"
                "## Project Adapter\n"
                "generic\n"
            ),
            encoding="utf-8",
        )
        (tmp_path / "artifacts" / "status" / "TASK-X.status.json").write_text(
            json.dumps(
                {
                    "task_id": "TASK-X",
                    "state": "planned",
                    "current_owner": "Claude",
                    "next_agent": "Claude",
                    "required_artifacts": [],
                    "available_artifacts": [],
                    "missing_artifacts": [],
                    "blocked_reason": "",
                    "last_updated": "2026-01-15T10:00:00+08:00",
                    "assurance_level": "mvp",
                    "project_adapter": "generic",
                    "open_verification_debts": [],
                    "verification_readiness": "mvp",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        plan_path = tmp_path / "artifacts" / "plans" / "TASK-X.plan.md"
        plan_text = (
            "# Plan: TASK-X\n"
            "## Metadata\n"
            "- Task ID: TASK-X\n"
            "- Artifact Type: plan\n"
            "- Owner: Claude\n"
            "- Status: ready\n"
            "- Last Updated: 2026-01-15T10:00:00+08:00\n"
            "## Scope\nthing\n"
            "## Files Likely Affected\n- foo\n"
            "## Proposed Changes\nx\n"
            "## Risks\nR1\n- Risk: r\n- Trigger: t\n- Detection: d\n- Mitigation: m\n- Severity: blocking\n"
            "## Validation Strategy\n- cmd\n"
            "## Ready For Coding\nyes\n"
        )
        plan_path.write_text(plan_text, encoding="utf-8")
        result = gsv.validate_markdown_artifact(plan_path, "plan", "TASK-X")
        assert any("Verification Obligations" in e for e in result.errors)

    def test_reconcile_no_missing_fields_prints_ok(self, capsys, tmp_path):
        artifacts_root = tmp_path / "artifacts"
        (artifacts_root / "tasks").mkdir(parents=True)
        (artifacts_root / "status").mkdir(parents=True)
        (artifacts_root / "tasks" / "TASK-X.task.md").write_text(
            (
                "# Task: TASK-X\n"
                "## Metadata\n"
                "- Task ID: TASK-X\n"
                "- Artifact Type: task\n"
                "- Owner: Claude\n"
                "- Status: approved\n"
                "- Last Updated: 2026-01-15T10:00:00+08:00\n"
                "## Assurance Level\n"
                "poc\n"
                "## Project Adapter\n"
                "generic\n"
            ),
            encoding="utf-8",
        )
        status_payload = {
            "task_id": "TASK-X",
            "state": "drafted",
            "current_owner": "Claude",
            "next_agent": "Claude",
            "required_artifacts": ["status", "task"],
            "available_artifacts": ["status", "task"],
            "missing_artifacts": [],
            "blocked_reason": "",
            "last_updated": "2026-01-15T10:00:00+08:00",
            "assurance_level": "poc",
            "project_adapter": "generic",
            "open_verification_debts": [],
            "verification_readiness": "poc",
        }
        status_path = artifacts_root / "status" / "TASK-X.status.json"
        status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        gsv.reconcile_status_file(artifacts_root, "TASK-X", apply=False)
        out = capsys.readouterr().out
        assert "[RECONCILE] No missing fields to add" in out

    def test_reconcile_missing_fields_dry_run_prints_diff(self, capsys, tmp_path):
        artifacts_root = tmp_path / "artifacts"
        (artifacts_root / "tasks").mkdir(parents=True)
        (artifacts_root / "status").mkdir(parents=True)
        (artifacts_root / "tasks" / "TASK-X.task.md").write_text(
            (
                "# Task: TASK-X\n"
                "## Metadata\n"
                "- Task ID: TASK-X\n"
                "- Artifact Type: task\n"
                "- Owner: Claude\n"
                "- Status: approved\n"
                "- Last Updated: 2026-01-15T10:00:00+08:00\n"
                "## Assurance Level\n"
                "poc\n"
                "## Project Adapter\n"
                "generic\n"
            ),
            encoding="utf-8",
        )
        status_payload = {
            "task_id": "TASK-X",
            "state": "drafted",
            "last_updated": "2026-01-15T10:00:00+08:00",
            "assurance_level": "poc",
            "project_adapter": "generic",
        }
        status_path = artifacts_root / "status" / "TASK-X.status.json"
        original = json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n"
        status_path.write_text(original, encoding="utf-8")
        gsv.reconcile_status_file(artifacts_root, "TASK-X", apply=False)
        out = capsys.readouterr().out
        assert "[RECONCILE] Missing status fields detected (dry-run)" in out
        assert "[DIFF] current_owner:" in out
        assert status_path.read_text(encoding="utf-8") == original

    def test_validate_artifact_presence_debts_and_readiness_mismatch(self, tmp_path):
        artifacts_root = tmp_path / "artifacts"
        for sub in ("tasks", "plans", "code", "verify", "status"):
            (artifacts_root / sub).mkdir(parents=True)
        task_path = artifacts_root / "tasks" / "TASK-X.task.md"
        task_path.write_text(
            (
                "# Task: TASK-X\n"
                "## Metadata\n"
                "- Task ID: TASK-X\n"
                "- Artifact Type: task\n"
                "- Owner: Claude\n"
                "- Status: approved\n"
                "- Last Updated: 2026-01-15T10:00:00+08:00\n"
                "## Assurance Level\n"
                "poc\n"
                "## Project Adapter\n"
                "generic\n"
            ),
            encoding="utf-8",
        )
        (artifacts_root / "verify" / "TASK-X.verify.md").write_text(
            (
                "# Verification: TASK-X\n"
                "## Metadata\n"
                "- Task ID: TASK-X\n"
                "- Artifact Type: verify\n"
                "- Owner: Claude\n"
                "- Status: pass\n"
                "- Last Updated: 2026-01-15T10:00:00+08:00\n"
                "## Verification Summary\nsum\n"
                "## Acceptance Criteria Checklist\n"
                "- **criterion**: C\n"
                "- **method**: M\n"
                "- **evidence**: E\n"
                "- **result**: deferred\n"
                "- **reason_code**: MANUAL_CHECK_DEFERRED\n"
                "## Overall Maturity\npoc\n"
                "## Deferred Items\n- deferred: C\n"
                "## Pass Fail Result\nfail\n"
            ),
            encoding="utf-8",
        )
        status_payload = {
            "task_id": "TASK-X",
            "state": "done",
            "current_owner": "Claude",
            "next_agent": "Claude",
            "required_artifacts": ["task", "verify", "status"],
            "available_artifacts": ["task", "verify", "status"],
            "missing_artifacts": [],
            "blocked_reason": "",
            "last_updated": "2026-01-15T10:00:00+08:00",
            "assurance_level": "poc",
            "project_adapter": "generic",
            "open_verification_debts": [],
            "verification_readiness": "production-ready",
        }
        result = gsv.validate_artifact_presence(
            artifacts_root, "TASK-X", "done", status_payload
        )
        joined = "\n".join(result.warnings)
        assert "open_verification_debts mismatch" in joined
        assert "verification_readiness mismatch" in joined

    def test_improvement_profile_reads_declared_value(self):
        assert gsv.improvement_profile("- Improvement Profile: gate-e") == "gate-e"
        assert gsv.improvement_profile("- Improvement Profile: bogus\n- Trigger Type: failure") == "gate-e"
