"""Split unit tests for guard_contract_validator per TASK-1054."""
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


class TestContractSyncFiles:
    def test_requirements_dev_is_exact_sync(self):
        assert "requirements-dev.txt" in gcv.EXACT_SYNC_FILES

class TestDetectRepoMode:
    def test_source_mode_when_sentinel_exists(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        assert gcv.detect_repo_mode(tmp_path) == gcv.SOURCE_REPO_MODE

    def test_downstream_mode_without_sentinel(self, tmp_path):
        assert gcv.detect_repo_mode(tmp_path) == gcv.DOWNSTREAM_REPO_MODE

class TestWorkflowPolicyContract:
    def test_rule_tables_contract_passes(self):
        assert gcv.validate_workflow_policy_contract() == []

class TestRootArtifactStrictness:
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
                - A
                ## Dependencies
                None
                ## Out of Scope
                - None
                ## Assurance Level
                POC
                ## Project Adapter
                generic
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
                ## Decision Class
                risk-acceptance
                ## Affected Gate
                Gate_D
                ## Scope
                Verification governance
                ## Issue
                Issue
                ## Options Considered
                - A
                ## Chosen Option
                A
                ## Reasoning
                Because
                ## Implications
                None
                ## Expiry
                None
                ## Linked Artifacts
                - `artifacts/tasks/TASK-001.task.md`
                ## Follow Up
                None
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
                ## Verification Summary
                Covered
                ## Acceptance Criteria Checklist
                - **criterion**: A
                - **method**: Artifact review
                - **evidence**: `artifacts/tasks/TASK-001.task.md`
                - **result**: verified
                ## Overall Maturity
                poc
                ## Deferred Items
                None
                ## Evidence
                - `artifacts/tasks/TASK-001.task.md`
                ## Evidence Refs
                - `artifacts/tasks/TASK-001.task.md`
                ## Decision Refs
                - `artifacts/decisions/TASK-001.decision.md`
                ## Build Guarantee
                None (no .csproj modified)
                ## Pass Fail Result
                pass
                ## Recommendation
                None
            """),
            encoding="utf-8",
        )
        (tmp_path / "artifacts" / "status" / "TASK-001.status.json").write_text(
            json.dumps(
                {
                    "task_id": "TASK-001",
                    "state": "done",
                    "current_owner": "Claude",
                    "next_agent": "Claude",
                    "required_artifacts": ["task", "code", "verify", "status"],
                    "available_artifacts": ["decision", "status", "task", "verify"],
                    "missing_artifacts": ["code"],
                    "blocked_reason": "",
                    "last_updated": "2026-01-15T10:00:00+08:00",
                    "assurance_level": "poc",
                    "project_adapter": "generic",
                    "open_verification_debts": [],
                    "verification_readiness": "poc",
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    def test_root_artifact_strictness_passes_on_structured_repo(self, tmp_path):
        self._seed_repo(tmp_path)
        assert gcv.validate_root_artifact_strictness(tmp_path) == []

    def test_root_artifact_strictness_flags_legacy_warning(self, tmp_path):
        self._seed_repo(tmp_path)
        status_path = tmp_path / "artifacts" / "status" / "TASK-001.status.json"
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        payload.pop("verification_readiness")
        status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        errors = gcv.validate_root_artifact_strictness(tmp_path)
        assert any("verification_readiness" in error for error in errors)

class TestGcvNormalizeText:
    def test_crlf_to_lf(self):
        assert gcv.normalize_text("line1\r\nline2") == "line1\nline2"

    def test_placeholder_replacement(self):
        result = gcv.normalize_text("{{PROJECT_NAME}} / {{REPO_NAME}} / {{UPSTREAM_ORG}}")
        assert "__PROJECT__" in result
        assert "__REPO__" in result
        assert "__ORG__" in result

    def test_whitespace_collapse(self):
        assert gcv.normalize_text("a   b\tc") == "a b c"

    def test_strip(self):
        assert gcv.normalize_text("  hello  ") == "hello"


# ─────────────────────────────────────────────
# detect_repo_mode / required_phrases_for_mode
# ─────────────────────────────────────────────

class TestGcvRepoMode:
    def test_detect_source_mode_with_sentinel(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        assert gcv.detect_repo_mode(tmp_path) == gcv.SOURCE_REPO_MODE

    def test_detect_downstream_mode_without_sentinel(self, tmp_path):
        assert gcv.detect_repo_mode(tmp_path) == gcv.DOWNSTREAM_REPO_MODE

    def test_required_phrases_for_downstream_excludes_template_only_entries(self):
        phrase_map = gcv.required_phrases_for_mode(gcv.DOWNSTREAM_REPO_MODE)
        assert "template/CLAUDE.md" not in phrase_map
        assert "template/README.md" not in phrase_map
        assert "CLAUDE.md" in phrase_map


# ─────────────────────────────────────────────
# validate_exact_sync
# ─────────────────────────────────────────────

class TestValidateExactSync:
    def _mark_source_repo(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")

    def _setup_sync_pair(self, tmp_path, relative, root_content, template_content=None):
        """Create a root file and its template counterpart."""
        root_file = tmp_path / relative
        root_file.parent.mkdir(parents=True, exist_ok=True)
        root_file.write_text(root_content, encoding="utf-8")
        tmpl_file = tmp_path / "template" / relative
        tmpl_file.parent.mkdir(parents=True, exist_ok=True)
        tmpl_file.write_text(template_content or root_content, encoding="utf-8")

    def test_all_in_sync(self, tmp_path):
        self._mark_source_repo(tmp_path)
        for rel in gcv.EXACT_SYNC_FILES:
            self._setup_sync_pair(tmp_path, rel, f"content of {rel}")
        errors = gcv.validate_exact_sync(tmp_path)
        assert errors == []

    def test_root_missing(self, tmp_path):
        self._mark_source_repo(tmp_path)
        # Create template only, skip root
        for rel in gcv.EXACT_SYNC_FILES:
            tmpl = tmp_path / "template" / rel
            tmpl.parent.mkdir(parents=True, exist_ok=True)
            tmpl.write_text("x", encoding="utf-8")
        errors = gcv.validate_exact_sync(tmp_path)
        assert all("Missing root file" in e for e in errors)

    def test_template_missing(self, tmp_path):
        self._mark_source_repo(tmp_path)
        for rel in gcv.EXACT_SYNC_FILES:
            root_f = tmp_path / rel
            root_f.parent.mkdir(parents=True, exist_ok=True)
            root_f.write_text("x", encoding="utf-8")
        errors = gcv.validate_exact_sync(tmp_path)
        assert all("Missing template file" in e for e in errors)

    def test_drift_detected(self, tmp_path):
        self._mark_source_repo(tmp_path)
        for rel in gcv.EXACT_SYNC_FILES:
            self._setup_sync_pair(tmp_path, rel, f"content of {rel}")
        # Introduce drift in the first file
        first = gcv.EXACT_SYNC_FILES[0]
        (tmp_path / first).write_text("different content", encoding="utf-8")
        errors = gcv.validate_exact_sync(tmp_path)
        assert len(errors) == 1
        assert "Contract drift" in errors[0]

    def test_whitespace_and_placeholder_normalized(self, tmp_path):
        self._mark_source_repo(tmp_path)
        for rel in gcv.EXACT_SYNC_FILES:
            self._setup_sync_pair(
                tmp_path, rel,
                "root  content  {{PROJECT_NAME}}",
                "root content {{PROJECT_NAME}}",
            )
        errors = gcv.validate_exact_sync(tmp_path)
        assert errors == []

    def test_downstream_mode_skips_template_exact_sync(self, tmp_path):
        for rel in gcv.EXACT_SYNC_FILES:
            root_f = tmp_path / rel
            root_f.parent.mkdir(parents=True, exist_ok=True)
            root_f.write_text("x", encoding="utf-8")
        errors = gcv.validate_exact_sync(tmp_path)
        assert errors == []


# ─────────────────────────────────────────────
# validate_required_phrases
# ─────────────────────────────────────────────

class TestValidateRequiredPhrases:
    def test_all_present(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        for rel, phrases in gcv.required_phrases_for_mode(gcv.SOURCE_REPO_MODE).items():
            f = tmp_path / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(" ".join(phrases), encoding="utf-8")
        errors = gcv.validate_required_phrases(tmp_path)
        assert errors == []

    def test_missing_file(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        errors = gcv.validate_required_phrases(tmp_path)
        assert all("Missing required file" in e for e in errors)

    def test_missing_phrase(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        for rel, phrases in gcv.required_phrases_for_mode(gcv.SOURCE_REPO_MODE).items():
            f = tmp_path / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            # Write all phrases except the first one
            f.write_text(" ".join(phrases[1:]), encoding="utf-8")
        errors = gcv.validate_required_phrases(tmp_path)
        assert len(errors) > 0
        assert all("missing required phrase" in e for e in errors)

    def test_downstream_mode_uses_downstream_claude_phrases(self, tmp_path):
        for rel, phrases in gcv.required_phrases_for_mode(gcv.DOWNSTREAM_REPO_MODE).items():
            f = tmp_path / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(" ".join(phrases), encoding="utf-8")
        errors = gcv.validate_required_phrases(tmp_path)
        assert errors == []


# ─────────────────────────────────────────────
# validate_repository_profile
# ─────────────────────────────────────────────

class TestValidateRepositoryProfile:
    def _valid_profile(self):
        return {
            "about": "A" * 100,
            "topics": list(gcv.REQUIRED_TOPICS) + ["extra-topic-1"],
        }

    def _write_profile(self, tmp_path, relative, data):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_valid(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            self._write_profile(tmp_path, rel, self._valid_profile())
        errors = gcv.validate_repository_profile(tmp_path)
        assert errors == []

    def test_missing_file(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        errors = gcv.validate_repository_profile(tmp_path)
        assert all("Missing required repository profile" in e for e in errors)

    def test_invalid_json(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{bad json}", encoding="utf-8")
        errors = gcv.validate_repository_profile(tmp_path)
        assert all("not valid JSON" in e for e in errors)

    def test_about_empty(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        profile = self._valid_profile()
        profile["about"] = ""
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            self._write_profile(tmp_path, rel, profile)
        errors = gcv.validate_repository_profile(tmp_path)
        assert any("non-empty string" in e for e in errors)

    def test_about_too_short(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        profile = self._valid_profile()
        profile["about"] = "Short"
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            self._write_profile(tmp_path, rel, profile)
        errors = gcv.validate_repository_profile(tmp_path)
        assert any("80-200 chars" in e for e in errors)

    def test_about_too_long(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        profile = self._valid_profile()
        profile["about"] = "X" * 201
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            self._write_profile(tmp_path, rel, profile)
        errors = gcv.validate_repository_profile(tmp_path)
        assert any("80-200 chars" in e for e in errors)

    def test_topics_not_list(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        profile = self._valid_profile()
        profile["topics"] = "not-a-list"
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            self._write_profile(tmp_path, rel, profile)
        errors = gcv.validate_repository_profile(tmp_path)
        assert any("must define list" in e for e in errors)

    def test_topics_too_few(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        profile = self._valid_profile()
        profile["topics"] = ["topic-1", "topic-2"]
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            self._write_profile(tmp_path, rel, profile)
        errors = gcv.validate_repository_profile(tmp_path)
        assert any("6-12 items" in e for e in errors)

    def test_topics_too_many(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        profile = self._valid_profile()
        profile["topics"] = [f"topic-{i}" for i in range(13)]
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            self._write_profile(tmp_path, rel, profile)
        errors = gcv.validate_repository_profile(tmp_path)
        assert any("6-12 items" in e for e in errors)

    def test_topics_duplicates(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        profile = self._valid_profile()
        profile["topics"] = list(gcv.REQUIRED_TOPICS) + [list(gcv.REQUIRED_TOPICS)[0]]
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            self._write_profile(tmp_path, rel, profile)
        errors = gcv.validate_repository_profile(tmp_path)
        assert any("duplicates" in e for e in errors)

    def test_topics_invalid_format(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        profile = self._valid_profile()
        profile["topics"] = list(gcv.REQUIRED_TOPICS) + ["UPPER_CASE"]
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            self._write_profile(tmp_path, rel, profile)
        errors = gcv.validate_repository_profile(tmp_path)
        assert any("lowercase-kebab-case" in e for e in errors)

    def test_topics_missing_required(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        profile = self._valid_profile()
        profile["topics"] = [f"custom-topic-{i}" for i in range(7)]
        for rel in gcv.REPOSITORY_PROFILE_FILES:
            self._write_profile(tmp_path, rel, profile)
        errors = gcv.validate_repository_profile(tmp_path)
        assert any("missing required topics" in e for e in errors)

    def test_downstream_mode_only_requires_root_profile(self, tmp_path):
        self._write_profile(tmp_path, ".github/repository-profile.json", self._valid_profile())
        errors = gcv.validate_repository_profile(tmp_path)
        assert errors == []


# ─────────────────────────────────────────────
# extract_h2_headers / parse_h2_sections / validate_readme_structure
# ─────────────────────────────────────────────

class TestExtractH2Headers:
    def test_basic(self):
        assert gcv.extract_h2_headers("## One\ntext\n## Two\n") == ["One", "Two"]

    def test_nested_ignored(self):
        assert gcv.extract_h2_headers("### Three\n## Two\n") == ["Two"]

    def test_no_headers(self):
        assert gcv.extract_h2_headers("plain text") == []

class TestParseH2Sections:
    def test_basic(self):
        sections = gcv.parse_h2_sections("## One\nalpha\n## Two\nbeta\n")
        assert sections == [("One", "alpha"), ("Two", "beta")]

    def test_ignores_h2_inside_code_fence(self):
        text = "## One\n```md\n## Fake\n```\nreal\n## Two\nbeta\n"
        sections = gcv.parse_h2_sections(text)
        assert sections == [("One", "```md\n## Fake\n```\nreal"), ("Two", "beta")]

class TestValidateMarkdownContracts:
    def _build_doc(self, headers, section_content):
        lines = []
        for header in headers:
            lines.append(f"## {header}")
            lines.append(section_content.get(header, f"{header} body"))
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _write_source_repo_docs(self, tmp_path):
        (tmp_path / gcv.SOURCE_REPO_SENTINEL).write_text("source repo", encoding="utf-8")
        docs = {
            "README.md": self._build_doc(
                gcv.README_HEADERS_EN,
                {
                    "Architecture Snapshot": "template/ + .github/ + OBSIDIAN.md + external/",
                    "Getting Started": "source template repo .council-forge-source-repo downstream terminal repo",
                    "Validator Commands": "source mode checks root ↔ template ↔ Obsidian",
                },
            ),
            "README.zh-TW.md": self._build_doc(
                gcv.README_HEADERS_ZH,
                {
                    "架構速覽": "template/ + .github/ + OBSIDIAN.md + external/",
                    "開始使用": "source template repo .council-forge-source-repo downstream terminal repo",
                    "驗證指令": "source mode 檢查 root ↔ template ↔ Obsidian",
                },
            ),
            "template/README.md": self._build_doc(
                gcv.README_HEADERS_EN,
                {
                    "Architecture Snapshot": ".github/ + OBSIDIAN.md + external/",
                    "Getting Started": "downstream terminal repo nested `template/`",
                    "Validator Commands": "downstream mode checks root ↔ Obsidian",
                },
            ),
            "template/README.zh-TW.md": self._build_doc(
                gcv.README_HEADERS_ZH,
                {
                    "架構速覽": ".github/ + OBSIDIAN.md + external/",
                    "開始使用": "downstream terminal repo nested `template/`",
                    "驗證指令": "downstream mode 檢查 root ↔ Obsidian",
                },
            ),
            "OBSIDIAN.md": self._build_doc(
                gcv.OBSIDIAN_HEADERS,
                {
                    "同步範圍": "source template repo template 對應文件 downstream terminal repo",
                    "Workflow 摘要": (
                        "source template repo 的 workflow 規則變更後，必須同步更新 root、`template/` 與 Obsidian 入口，並通過 contract guard。\n"
                        "downstream terminal repo 的 workflow 規則變更後，只維護 root 文件與 `OBSIDIAN.md`，並通過 contract guard。"
                    ),
                    "GitHub / Template 對應": "template/START_HERE.md template/OBSIDIAN.md",
                },
            ),
            "template/OBSIDIAN.md": self._build_doc(
                gcv.OBSIDIAN_HEADERS,
                {
                    "同步範圍": "只維護 root 文件與 `OBSIDIAN.md` 不再建立新的 `template/`",
                    "Workflow 摘要": "downstream terminal repo 的 workflow 規則變更後，只維護 root 文件與 `OBSIDIAN.md`，並通過 contract guard。",
                    "GitHub / Template 對應": "本 repo 不建立 nested `template/`",
                },
            ),
        }
        for relative, content in docs.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def _write_downstream_repo_docs(self, tmp_path):
        docs = {
            "README.md": self._build_doc(
                gcv.README_HEADERS_EN,
                {
                    "Architecture Snapshot": ".github/ + OBSIDIAN.md + external/",
                    "Getting Started": "downstream terminal repo nested `template/`",
                    "Validator Commands": "downstream mode checks root ↔ Obsidian",
                },
            ),
            "README.zh-TW.md": self._build_doc(
                gcv.README_HEADERS_ZH,
                {
                    "架構速覽": ".github/ + OBSIDIAN.md + external/",
                    "開始使用": "downstream terminal repo nested `template/`",
                    "驗證指令": "downstream mode 檢查 root ↔ Obsidian",
                },
            ),
            "OBSIDIAN.md": self._build_doc(
                gcv.OBSIDIAN_HEADERS,
                {
                    "同步範圍": "只維護 root 文件與 `OBSIDIAN.md` 不再建立新的 `template/`",
                    "Workflow 摘要": "downstream terminal repo 的 workflow 規則變更後，只維護 root 文件與 `OBSIDIAN.md`，並通過 contract guard。",
                    "GitHub / Template 對應": "本 repo 不建立 nested `template/`",
                },
            ),
        }
        for relative, content in docs.items():
            path = tmp_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def test_source_mode_passes_when_contract_matches(self, tmp_path):
        self._write_source_repo_docs(tmp_path)
        assert gcv.validate_markdown_contracts(tmp_path) == []

    def test_readme_h2_order_mismatch_fails(self, tmp_path):
        self._write_downstream_repo_docs(tmp_path)
        (tmp_path / "README.md").write_text(
            self._build_doc(
                ["Start Here", "Product Positioning", "Architecture Snapshot"] + gcv.README_HEADERS_EN[3:7] + ["Workflow Overview"] + gcv.README_HEADERS_EN[8:],
                {
                    "Architecture Snapshot": ".github/ + OBSIDIAN.md + external/",
                    "Getting Started": "downstream terminal repo nested `template/`",
                    "Validator Commands": "downstream mode checks root ↔ Obsidian",
                },
            ),
            encoding="utf-8",
        )
        errors = gcv.validate_markdown_contracts(tmp_path)
        assert any("README.md H2 order mismatch" in e for e in errors)

    def test_source_root_readme_missing_sentinel_phrase_fails(self, tmp_path):
        self._write_source_repo_docs(tmp_path)
        path = tmp_path / "README.md"
        path.write_text(path.read_text(encoding="utf-8").replace(".council-forge-source-repo", "sentinel"), encoding="utf-8")
        errors = gcv.validate_markdown_contracts(tmp_path)
        assert any("README.md section 'Getting Started' missing required phrase: .council-forge-source-repo" in e for e in errors)

    def test_missing_required_section_fails(self, tmp_path):
        self._write_downstream_repo_docs(tmp_path)
        path = tmp_path / "README.md"
        content = path.read_text(encoding="utf-8")
        content = content.replace("## Validator Commands\n", "## Validator Command Removed\n", 1)
        path.write_text(content, encoding="utf-8")
        errors = gcv.validate_markdown_contracts(tmp_path)
        assert any("README.md missing required section: Validator Commands" in e for e in errors)

    def test_downstream_readme_source_architecture_wording_fails(self, tmp_path):
        self._write_downstream_repo_docs(tmp_path)
        path = tmp_path / "README.md"
        path.write_text(path.read_text(encoding="utf-8").replace(".github/ + OBSIDIAN.md + external/", "template/ + .github/ + OBSIDIAN.md + external/"), encoding="utf-8")
        errors = gcv.validate_markdown_contracts(tmp_path)
        assert any("README.md section 'Architecture Snapshot' contains forbidden phrase: template/ + .github/ + OBSIDIAN.md + external/" in e for e in errors)

    def test_source_template_readme_missing_downstream_wording_fails(self, tmp_path):
        self._write_source_repo_docs(tmp_path)
        path = tmp_path / "template" / "README.md"
        path.write_text(path.read_text(encoding="utf-8").replace("downstream terminal repo", "terminal repo"), encoding="utf-8")
        errors = gcv.validate_markdown_contracts(tmp_path)
        assert any("template/README.md section 'Getting Started' missing required phrase: downstream terminal repo" in e for e in errors)

    def test_downstream_obsidian_source_only_wording_fails(self, tmp_path):
        self._write_downstream_repo_docs(tmp_path)
        path = tmp_path / "OBSIDIAN.md"
        path.write_text(path.read_text(encoding="utf-8").replace("本 repo 不建立 nested `template/`", "template/START_HERE.md template/OBSIDIAN.md"), encoding="utf-8")
        errors = gcv.validate_markdown_contracts(tmp_path)
        assert any("OBSIDIAN.md section 'GitHub / Template 對應' contains forbidden phrase: template/START_HERE.md" in e for e in errors)

    def test_required_phrase_in_wrong_obsidian_section_still_fails(self, tmp_path):
        self._write_source_repo_docs(tmp_path)
        path = tmp_path / "OBSIDIAN.md"
        original = path.read_text(encoding="utf-8")
        moved = original.replace("template/START_HERE.md template/OBSIDIAN.md", "")
        moved = moved.replace("source template repo template 對應文件 downstream terminal repo", "source template repo template 對應文件 downstream terminal repo template/START_HERE.md template/OBSIDIAN.md")
        path.write_text(moved, encoding="utf-8")
        errors = gcv.validate_markdown_contracts(tmp_path)
        assert any("OBSIDIAN.md section 'GitHub / Template 對應' missing required phrase: template/START_HERE.md" in e for e in errors)

    def test_missing_required_file_fails(self, tmp_path):
        self._write_downstream_repo_docs(tmp_path)
        (tmp_path / "OBSIDIAN.md").unlink()
        errors = gcv.validate_markdown_contracts(tmp_path)
        assert any("Missing required file: OBSIDIAN.md" in e for e in errors)

class TestValidateReadmeStructure:
    def _write_source_repo_docs(self, tmp_path):
        TestValidateMarkdownContracts()._write_source_repo_docs(tmp_path)

    def _write_downstream_repo_docs(self, tmp_path):
        TestValidateMarkdownContracts()._write_downstream_repo_docs(tmp_path)

    def test_matching(self, tmp_path):
        self._write_downstream_repo_docs(tmp_path)
        errors = gcv.validate_readme_structure(tmp_path)
        assert errors == []

    def test_section_count_mismatch(self, tmp_path):
        self._write_downstream_repo_docs(tmp_path)
        zh = tmp_path / "README.zh-TW.md"
        zh.write_text("## 從這裡開始\ntext\n## 產品定位\ntext\n", encoding="utf-8")
        errors = gcv.validate_readme_structure(tmp_path)
        assert any("structure mismatch" in e for e in errors)

    def test_missing_en(self, tmp_path):
        self._write_downstream_repo_docs(tmp_path)
        (tmp_path / "README.md").unlink()
        errors = gcv.validate_readme_structure(tmp_path)
        assert any("Missing README.md" in e for e in errors)

    def test_template_level(self, tmp_path):
        self._write_source_repo_docs(tmp_path)
        tmpl_zh = tmp_path / "template" / "README.zh-TW.md"
        tmpl_zh.write_text("## 從這裡開始\ntext\n", encoding="utf-8")
        errors = gcv.validate_readme_structure(tmp_path)
        assert any("template" in e and "mismatch" in e for e in errors)

    def test_source_mode_missing_template_readmes_fails(self, tmp_path):
        self._write_source_repo_docs(tmp_path)
        (tmp_path / "template" / "README.md").unlink()
        (tmp_path / "template" / "README.zh-TW.md").unlink()
        errors = gcv.validate_readme_structure(tmp_path)
        assert any("Missing README.md in template" in e for e in errors)
        assert any("Missing README.zh-TW.md in template" in e for e in errors)

    def test_downstream_mode_skips_template_readme_check(self, tmp_path):
        self._write_downstream_repo_docs(tmp_path)
        tmpl = tmp_path / "template"
        tmpl.mkdir()
        (tmpl / "README.md").write_text("## Start Here\n", encoding="utf-8")
        (tmpl / "README.zh-TW.md").write_text("## 從這裡開始\n## 產品定位\n", encoding="utf-8")
        errors = gcv.validate_readme_structure(tmp_path)
        assert errors == []

class TestValidateAllowedGeminiModels:
    def test_allowed_models_pass(self, tmp_path):
        for rel in gcv.ACTIVE_GEMINI_POLICY_FILES:
            path = tmp_path / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                " ".join(sorted(gcv.ALLOWED_GEMINI_MODELS)),
                encoding="utf-8",
            )
        errors = gcv.validate_allowed_gemini_models(tmp_path)
        assert errors == []

    def test_disallowed_model_token_fails(self, tmp_path):
        path = tmp_path / "BOOTSTRAP_PROMPT.md"
        path.write_text("gemini-2.5-flash gemini-3.1-flash-lite-preview", encoding="utf-8")
        errors = gcv.validate_allowed_gemini_models(tmp_path)
        assert any("unsupported Gemini model reference" in e for e in errors)

    def test_disallowed_model_fragment_fails(self, tmp_path):
        path = tmp_path / "docs" / "subagent_roles.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Gemini 2.0 flash is forbidden here.", encoding="utf-8")
        errors = gcv.validate_allowed_gemini_models(tmp_path)
        assert any("disallowed Gemini model fragment" in e for e in errors)


# ─────────────────────────────────────────────
# detect_changed_files
# ─────────────────────────────────────────────

class TestValidatePromptCaseSync:
    def test_no_git_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gcv, "detect_changed_files", lambda root: (False, set()))
        errors = gcv.validate_prompt_case_sync(tmp_path)
        assert errors == []

    def test_no_changes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gcv, "detect_changed_files", lambda root: (True, set()))
        errors = gcv.validate_prompt_case_sync(tmp_path)
        assert errors == []

    def test_prompt_changed_without_regression(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            gcv, "detect_changed_files",
            lambda root: (True, {"CLAUDE.md", "AGENTS.md"}),
        )
        errors = gcv.validate_prompt_case_sync(tmp_path)
        assert len(errors) == 1
        assert "prompt regression cases" in errors[0].lower()

    def test_prompt_changed_with_regression(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            gcv, "detect_changed_files",
            lambda root: (True, {
                "CLAUDE.md",
                "artifacts/scripts/drills/prompt_regression_cases.json",
            }),
        )
        errors = gcv.validate_prompt_case_sync(tmp_path)
        assert errors == []

    def test_non_prompt_changes_ok(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            gcv, "detect_changed_files",
            lambda root: (True, {"artifacts/scripts/guard_status_validator.py"}),
        )
        errors = gcv.validate_prompt_case_sync(tmp_path)
        assert errors == []


# ─────────────────────────────────────────────
# validate_readme_structure: missing zh only
# ─────────────────────────────────────────────

class TestValidateReadmeStructureMissingZh:
    def test_missing_zh(self, tmp_path):
        (tmp_path / "README.md").write_text("## Test\n", encoding="utf-8")
        errors = gcv.validate_readme_structure(tmp_path)
        assert any("Missing README.zh-TW.md" in e for e in errors)


# ═════════════════════════════════════════════
# COVERAGE EXPANSION: guard_status_validator
# ═════════════════════════════════════════════


# ─────────────────────────────────────────────
# validate_status_schema: decision_waivers & auto_upgrade_log
# ─────────────────────────────────────────────

class TestGuardContractValidatorCoverageCatchup:
    def test_validate_root_artifact_strictness_surfaces_markdown_errors(self, tmp_path):
        (tmp_path / "artifacts" / "tasks").mkdir(parents=True)
        (tmp_path / "artifacts" / "tasks" / "TASK-Z.task.md").write_text(
            "# Task: TASK-Z\nintentionally incomplete\n",
            encoding="utf-8",
        )
        errors = gcv.validate_root_artifact_strictness(tmp_path)
        assert any("TASK-Z.task.md" in e for e in errors)

    def test_validate_root_artifact_strictness_surfaces_warnings(self, tmp_path, monkeypatch):
        (tmp_path / "artifacts" / "decisions").mkdir(parents=True)
        decision_path = tmp_path / "artifacts" / "decisions" / "TASK-Y.decision.md"
        decision_path.write_text("placeholder\n", encoding="utf-8")
        original = gsv.validate_markdown_artifact

        def with_warning(path, artifact_type, task_id):
            base = original(path, artifact_type, task_id)
            base.warnings.append("synthetic-warning")
            return base

        monkeypatch.setattr(gsv, "validate_markdown_artifact", with_warning)
        errors = gcv.validate_root_artifact_strictness(tmp_path)
        assert any("synthetic-warning" in e for e in errors)

    def test_validate_root_artifact_strictness_surfaces_status_errors(self, tmp_path):
        (tmp_path / "artifacts" / "status").mkdir(parents=True)
        status_payload = {
            "task_id": "TASK-S",
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
        }
        (tmp_path / "artifacts" / "status" / "TASK-S.status.json").write_text(
            json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        errors = gcv.validate_root_artifact_strictness(tmp_path)
        assert any("TASK-S.status.json" in e for e in errors)

class TestRaciAuditor:
    def test_hybrid_sync_drift_raises_error(self, tmp_path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        roles_md = docs_dir / "subagent_roles.md"
        roles_md.write_text(
            "| 角色 | 類型 | R (主執行) | A (最終問責) | C (諮詢) | I (通知) | 主要輸入 | 主要輸出 |\n"
            "|---|---|---|---|---|---|---|---|\n"
            "| Claude Code | 主控代理 | missing_task / plan | -- | -- | -- | -- | -- |\n",
            encoding="utf-8"
        )
        with pytest.raises(ValueError, match="RACI hybrid sync failed"):
            gcv.validate_raci_hybrid_sync(tmp_path)

    def test_detect_raci_violations(self, tmp_path):
        file_path = tmp_path / "artifacts" / "tasks" / "TASK-1001.task.md"
        # Implementer edits a task -> violation
        violations = gcv.detect_raci_violations(file_path, "Implementer", wc.RACI_MATRIX)
        assert len(violations) == 1
        assert violations[0].agent == "Implementer"
        assert violations[0].file_path == file_path
        assert violations[0].required_type == "code (實檔修改)"
        assert violations[0].actual_type == "task"

        # Claude edits a task -> ok
        assert len(gcv.detect_raci_violations(file_path, "Claude Code", wc.RACI_MATRIX)) == 0

    def test_apply_raci_waivers_ex_ante(self):
        v = gcv.RaciViolation(
            agent="Implementer",
            file_path=Path("artifacts/tasks/TASK-1001.task.md"),
            actual_type="task",
            required_type="code (實檔修改)"
        )
        decision = {
            "Waiver Type": "ex-ante",
            "Waived Agent": "Implementer",
            "Waived Artifact Type": "task",
            "Last Updated": "2026-04-26T10:00:00+08:00"
        }
        post_waiver = gcv.apply_raci_waivers([v], [decision])
        assert len(post_waiver) == 0

    def test_apply_raci_waivers_pre_existing_dirty_does_not_expand(self):
        v = gcv.RaciViolation(
            agent="Implementer",
            file_path=Path("artifacts/tasks/TASK-1001.task.md"),
            actual_type="task",
            required_type="code (實檔修改)"
        )
        decision = {
            "Waiver Type": "pre-existing-dirty",
            "Waived Agent": "Implementer",
            "Waived Artifact Type": "task",
            "Last Updated": "2026-04-26T10:00:00+08:00"
        }
        # pre-existing-dirty cannot waive RACI violations
        post_waiver = gcv.apply_raci_waivers([v], [decision])
        assert len(post_waiver) == 1

    def test_main_audit_raci(self, tmp_path):
        import workflow_constants as wc
        # Create minimal repo structure
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        roles_md = docs_dir / "subagent_roles.md"
        
        # mock roles matching workflow_constants
        roles_content = "| 角色 | 類型 | R (主執行) | A | C | I | 主要輸入 | 主要輸出 |\n|---|---|---|---|---|---|---|---|\n"
        for agent, artifacts in wc.RACI_MATRIX.items():
            roles_content += f"| {agent} | Type | {' / '.join(artifacts) or '--'} | -- | -- | -- | -- | -- |\n"
        roles_md.write_text(roles_content, encoding="utf-8")
        
        tasks_dir = tmp_path / "artifacts" / "tasks"
        tasks_dir.mkdir(parents=True)
        task_file = tasks_dir / "TASK-1001.task.md"
        task_file.write_text("dummy", encoding="utf-8")
        
        # Implementer modifying task -> Violation
        ret = gcv.main(["--root", str(tmp_path), "--audit-raci", str(task_file), "Implementer"])
        assert ret == 1
        
        # Claude Code modifying task -> Pass
        ret = gcv.main(["--root", str(tmp_path), "--audit-raci", str(task_file), "Claude Code"])
        assert ret == 0

    def test_validate_raci_hybrid_sync_missing_file(self, tmp_path):
        with pytest.raises(ValueError, match="not found"):
            gcv.validate_raci_hybrid_sync(tmp_path)

    def test_validate_raci_hybrid_sync_mismatch(self, tmp_path):
        import workflow_constants as wc
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        roles_md = docs_dir / "subagent_roles.md"
        
        # Missing agent in docs
        roles_md.write_text("| 角色 | 類型 | R (主執行) | A | C | I | 主要輸入 | 主要輸出 |\n|---|---|---|---|---|---|---|---|\n", encoding="utf-8")
        with pytest.raises(ValueError, match="but not in subagent_roles"):
            gcv.validate_raci_hybrid_sync(tmp_path)

        # Extra agent in docs
        roles_content = "| 角色 | 類型 | R (主執行) | A | C | I | 主要輸入 | 主要輸出 |\n|---|---|---|---|---|---|---|---|\n"
        for agent, artifacts in wc.RACI_MATRIX.items():
            roles_content += f"| {agent} | Type | {' / '.join(artifacts) or '--'} | -- | -- | -- | -- | -- |\n"
        roles_content += "| ExtraAgent | Type | code | -- | -- | -- | -- | -- |\n"
        roles_md.write_text(roles_content, encoding="utf-8")
        with pytest.raises(ValueError, match="but not in RACI_MATRIX"):
            gcv.validate_raci_hybrid_sync(tmp_path)

    def test_detect_raci_violations_all_types(self):
        matrix = {"AgentA": {"plan"}, "AgentB": {"code"}}
        paths = [
            (Path("artifacts/tasks/TASK-1.task.md"), "task"),
            (Path("artifacts/plans/TASK-1.plan.md"), "plan"),
            (Path("artifacts/decisions/TASK-1.decision.md"), "decision"),
            (Path("artifacts/status/TASK-1.status.json"), "status"),
            (Path("artifacts/research/TASK-1.research.md"), "research"),
            (Path("artifacts/test/TASK-1.test.md"), "test"),
            (Path("artifacts/verify/TASK-1.verify.md"), "verify"),
            (Path(".github/memory-bank/file.md"), "Remember Capture draft"),
        ]
        for p, expected_type in paths:
            vs = gcv.detect_raci_violations(p, "AgentC", matrix)
            assert len(vs) == 1
            assert vs[0].actual_type == expected_type
            
        # Test code (實檔修改) mapped to 'code'
        vs = gcv.detect_raci_violations(Path("src/main.py"), "AgentB", matrix)
        assert len(vs) == 0

