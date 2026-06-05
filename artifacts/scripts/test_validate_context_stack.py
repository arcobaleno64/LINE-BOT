"""Split unit tests for validate_context_stack per TASK-1054."""
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


class TestContextStackHelpers:
    def test_estimate_tokens_counts_cjk_and_ascii(self):
        result = vcs.estimate_tokens("abc def 測試")
        assert result >= 5

    def test_extract_frontmatter_name(self):
        text = "---\nname: sample-skill\ndescription: test\n---\n# Title"
        assert vcs.extract_frontmatter_name(text) == "sample-skill"

    def test_extract_headings(self):
        headings = vcs.extract_headings("# One\n## Two\n### Three")
        assert headings == ["One", "Two", "Three"]

class TestContextStackChecks:
    def _write_file(self, root: Path, rel_path: str, content: str) -> None:
        path = root / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _build_valid_repo(self, root: Path) -> None:
        self._write_file(
            root,
            ".github/memory-bank/artifact-rules.md",
            "# Task\ncontent\n# Plan\ncontent\n# Code\ncontent\n# Verify\ncontent\n",
        )
        self._write_file(
            root,
            ".github/memory-bank/workflow-gates.md",
            "# Intake\ncontent\n# Research\ncontent\n# Planning\ncontent\n# Coding\ncontent\n# Review\ncontent\n",
        )
        self._write_file(
            root,
            ".github/memory-bank/prompt-patterns.md",
            "# Agent Dispatch\ncontent\n# Artifact Output\ncontent\n",
        )
        self._write_file(
            root,
            ".github/memory-bank/project-facts.md",
            "# 技術棧\ncontent\n# 主要組件\ncontent\n# 環境變數\ncontent\n",
        )
        self._write_file(
            root,
            ".github/copilot-instructions.md",
            "short copilot instructions",
        )
        self._write_file(
            root,
            ".github/prompts/example.md",
            "---\nname: example-prompt\n---\n# Prompt",
        )
        self._write_file(
            root,
            ".github/skills/example/SKILL.md",
            "---\nname: example-skill\n---\n# Skill",
        )
        self._write_file(
            root,
            "docs/reference.md",
            "reference target",
        )
        self._write_file(
            root,
            "template/.github/memory-bank/artifact-rules.md",
            "# Task\ncontent\n# Plan\ncontent\n# Code\ncontent\n# Verify\ncontent\n",
        )
        self._write_file(
            root,
            "template/.github/memory-bank/workflow-gates.md",
            "# Intake\ncontent\n# Research\ncontent\n# Planning\ncontent\n# Coding\ncontent\n# Review\ncontent\n",
        )
        self._write_file(
            root,
            "template/.github/memory-bank/prompt-patterns.md",
            "# Agent Dispatch\ncontent\n# Artifact Output\ncontent\n",
        )
        self._write_file(
            root,
            "template/.github/memory-bank/project-facts.md",
            "# 技術棧\ncontent\n# 主要組件\ncontent\n# 環境變數\ncontent\n",
        )
        self._write_file(
            root,
            "template/.github/prompts/example.md",
            "---\nname: example-prompt\n---\n# Prompt",
        )
        self._write_file(
            root,
            "template/.github/skills/example/SKILL.md",
            "---\nname: example-skill\n---\n# Skill",
        )
        self._write_file(
            root,
            "template/.github/copilot-instructions.md",
            "short copilot instructions",
        )

    def test_check_memory_bank_existence(self, tmp_path):
        self._build_valid_repo(tmp_path)
        assert vcs.check_memory_bank_existence(tmp_path) == []

    def test_check_cross_references_flags_missing_target(self, tmp_path):
        self._build_valid_repo(tmp_path)
        path = tmp_path / ".github/memory-bank/artifact-rules.md"
        path.write_text("# Task\nsee docs/missing.md\n# Plan\ncontent\n# Code\ncontent\n# Verify\ncontent\n", encoding="utf-8")
        errors = vcs.check_cross_references(tmp_path)
        assert any("docs/missing.md" in error for error in errors)

    def test_check_frontmatter_and_uniqueness(self, tmp_path):
        self._build_valid_repo(tmp_path)
        errors, names = vcs.check_frontmatter(tmp_path)
        assert errors == []
        assert names["prompt"] == ["example-prompt"]
        assert names["skill"] == ["example-skill"]
        assert vcs.check_name_uniqueness(names) == []

    def test_check_name_uniqueness_detects_collisions(self):
        errors = vcs.check_name_uniqueness(
            {"prompt": ["dup", "dup", "shared"], "skill": ["skill", "shared"]}
        )
        assert any("Duplicate prompt name" in error for error in errors)
        assert any("Name collision" in error for error in errors)

    def test_check_copilot_instructions_size_flags_oversized_file(self, tmp_path):
        self._build_valid_repo(tmp_path)
        oversized = "詞" * 1400
        (tmp_path / ".github/copilot-instructions.md").write_text(oversized, encoding="utf-8")
        errors = vcs.check_copilot_instructions_size(tmp_path)
        assert any("copilot-instructions" in error for error in errors)

    def test_check_template_sync_reports_missing_template_file(self, tmp_path):
        self._build_valid_repo(tmp_path)
        (tmp_path / "template/.github/skills/example/SKILL.md").unlink()
        errors = vcs.check_template_sync(tmp_path)
        assert any("template/.github/skills missing" in error for error in errors)

    def test_check_memory_bank_quality_warns_on_orphan_and_long_file(self, tmp_path):
        self._build_valid_repo(tmp_path)
        long_content = "# Task\ncontent\n# Plan\ncontent\n# Code\ncontent\n# Verify\ncontent\n" + "\n".join(
            f"line {index}" for index in range(130)
        )
        (tmp_path / ".github/memory-bank/artifact-rules.md").write_text(
            long_content,
            encoding="utf-8",
        )
        (tmp_path / ".github/memory-bank/prompt-patterns.md").write_text(
            "# Agent Dispatch\ncontent\n# Artifact Output\n",
            encoding="utf-8",
        )
        issues = vcs.check_memory_bank_quality(tmp_path)
        assert any("consider consolidation" in issue for issue in issues)
        assert any("orphan section" in issue for issue in issues)

    def test_main_passes_on_valid_repo(self, tmp_path, monkeypatch, capsys):
        self._build_valid_repo(tmp_path)
        monkeypatch.setattr(sys, "argv", ["validate_context_stack.py", "--root", str(tmp_path)])
        # init_streams() rewrites sys.stdout when encoding != utf-8; that breaks pytest's
        # capsys capture path. Patch it to a no-op for this test.
        monkeypatch.setattr(vcs, "init_streams", lambda *a, **kw: None)
        assert vcs.main() == 0
        captured = capsys.readouterr()
        assert "PASSED" in captured.out


# ═════════════════════════════════════════════
# EDGE-CASE TESTS
# ═════════════════════════════════════════════


TAIPEI_TZ = timezone(timedelta(hours=8))


# ─────────────────────────────────────────────
# parse_csv_file_tokens
# ─────────────────────────────────────────────

class TestVcsExtras:
    def test_normalize_text_basic(self):
        assert prv.normalize_text("Hello  World\n") == "hello world "

    def test_contains_any(self):
        assert prv.contains_any("hello world", ["world", "foo"])
        assert not prv.contains_any("hello world", ["bar", "baz"])

    def test_check_near_terms_true(self):
        assert prv.check_near_terms("abc def ghi", ["abc", "ghi"], 20)

    def test_check_near_terms_false(self):
        text = "abc " + "x" * 300 + " ghi"
        assert not prv.check_near_terms(text.lower(), ["abc", "ghi"], 10)


# ─────────────────────────────────────────────
# detect_historical_diff_scope_drift (partial)
# ─────────────────────────────────────────────

class TestVcsEstimateTokens:
    def test_ascii(self):
        tokens = vcs.estimate_tokens("hello world foo bar")
        assert tokens >= 4

    def test_cjk(self):
        tokens = vcs.estimate_tokens("你好世界")
        assert tokens >= 4  # 4 chars × 1.5

    def test_mixed(self):
        tokens = vcs.estimate_tokens("hello 你好 world")
        assert tokens >= 4

class TestVcsExtractFrontmatterName:
    def test_valid(self):
        text = "---\nname: my-prompt\ndescription: test\n---\n# Content"
        assert vcs.extract_frontmatter_name(text) == "my-prompt"

    def test_no_frontmatter(self):
        assert vcs.extract_frontmatter_name("# No frontmatter") is None

    def test_no_name(self):
        text = "---\ndescription: test\n---\n# Content"
        assert vcs.extract_frontmatter_name(text) is None

class TestVcsExtractHeadings:
    def test_basic(self):
        text = "# H1\n## H2\n### H3\nContent\n"
        result = vcs.extract_headings(text)
        assert "H1" in result
        assert "H2" in result
        assert "H3" in result

class TestVcsCheckMemoryBankExistence:
    def test_no_dir(self, tmp_path):
        errors = vcs.check_memory_bank_existence(tmp_path)
        assert any("Directory missing" in e for e in errors)

    def test_missing_file(self, tmp_path):
        mb = tmp_path / ".github" / "memory-bank"
        mb.mkdir(parents=True)
        errors = vcs.check_memory_bank_existence(tmp_path)
        assert any("Missing" in e for e in errors)

    def test_empty_file(self, tmp_path):
        mb = tmp_path / ".github" / "memory-bank"
        mb.mkdir(parents=True)
        for fname in vcs.MEMORY_BANK_EXPECTED_FILES:
            (mb / fname).write_text("", encoding="utf-8")
        errors = vcs.check_memory_bank_existence(tmp_path)
        assert any("Empty file" in e for e in errors)

    def test_all_present(self, tmp_path):
        mb = tmp_path / ".github" / "memory-bank"
        mb.mkdir(parents=True)
        for fname in vcs.MEMORY_BANK_EXPECTED_FILES:
            (mb / fname).write_text("# Content\nSome text\n", encoding="utf-8")
        errors = vcs.check_memory_bank_existence(tmp_path)
        assert not errors

class TestVcsCheckCrossReferences:
    def test_no_dir(self, tmp_path):
        errors = vcs.check_cross_references(tmp_path)
        assert not errors

    def test_broken_ref(self, tmp_path):
        mb = tmp_path / ".github" / "memory-bank"
        mb.mkdir(parents=True)
        (mb / "test.md").write_text("see `docs/nonexistent.md`", encoding="utf-8")
        errors = vcs.check_cross_references(tmp_path)
        assert any("Broken xref" in e for e in errors)

    def test_valid_ref(self, tmp_path):
        mb = tmp_path / ".github" / "memory-bank"
        mb.mkdir(parents=True)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "existing.md").write_text("x", encoding="utf-8")
        (mb / "test.md").write_text("see `docs/existing.md`", encoding="utf-8")
        errors = vcs.check_cross_references(tmp_path)
        assert not errors

class TestVcsCheckFrontmatter:
    def test_malformed(self, tmp_path):
        pd = tmp_path / ".github" / "prompts"
        pd.mkdir(parents=True)
        (pd / "bad.md").write_text("---\nname: test\nno closing", encoding="utf-8")
        errors, names = vcs.check_frontmatter(tmp_path)
        assert any("Malformed" in e for e in errors)

    def test_valid_prompt(self, tmp_path):
        pd = tmp_path / ".github" / "prompts"
        pd.mkdir(parents=True)
        (pd / "good.md").write_text("---\nname: my-prompt\n---\n# Content", encoding="utf-8")
        errors, names = vcs.check_frontmatter(tmp_path)
        assert "my-prompt" in names["prompt"]

    def test_skill_missing_frontmatter(self, tmp_path):
        sd = tmp_path / ".github" / "skills" / "test-skill"
        sd.mkdir(parents=True)
        (sd / "SKILL.md").write_text("# No frontmatter\nContent", encoding="utf-8")
        errors, names = vcs.check_frontmatter(tmp_path)
        assert any("Missing or malformed" in e for e in errors)

    def test_valid_skill(self, tmp_path):
        sd = tmp_path / ".github" / "skills" / "test-skill"
        sd.mkdir(parents=True)
        (sd / "SKILL.md").write_text("---\nname: test-skill\n---\n# Content", encoding="utf-8")
        errors, names = vcs.check_frontmatter(tmp_path)
        assert "test-skill" in names["skill"]

class TestVcsCheckNameUniqueness:
    def test_no_duplicates(self):
        names = {"prompt": ["a", "b"], "skill": ["c", "d"]}
        assert not vcs.check_name_uniqueness(names)

    def test_duplicate_prompt(self):
        names = {"prompt": ["a", "a"], "skill": []}
        errors = vcs.check_name_uniqueness(names)
        assert any("Duplicate prompt" in e for e in errors)

    def test_duplicate_skill(self):
        names = {"prompt": [], "skill": ["x", "x"]}
        errors = vcs.check_name_uniqueness(names)
        assert any("Duplicate skill" in e for e in errors)

    def test_collision(self):
        names = {"prompt": ["shared"], "skill": ["shared"]}
        errors = vcs.check_name_uniqueness(names)
        assert any("collision" in e for e in errors)

class TestVcsCheckCopilotInstructionsSize:
    def test_missing(self, tmp_path):
        errors = vcs.check_copilot_instructions_size(tmp_path)
        assert any("Missing" in e for e in errors)

    def test_within_limit(self, tmp_path):
        ci = tmp_path / ".github" / "copilot-instructions.md"
        ci.parent.mkdir(parents=True)
        ci.write_text("Short content\n", encoding="utf-8")
        errors = vcs.check_copilot_instructions_size(tmp_path)
        assert not errors

    def test_over_limit(self, tmp_path):
        ci = tmp_path / ".github" / "copilot-instructions.md"
        ci.parent.mkdir(parents=True)
        ci.write_text("word " * 3000, encoding="utf-8")
        errors = vcs.check_copilot_instructions_size(tmp_path)
        assert any("tokens" in e for e in errors)

class TestVcsCheckTemplateSync:
    def test_no_template(self, tmp_path):
        errors = vcs.check_template_sync(tmp_path)
        assert not errors

    def test_missing_template_dir(self, tmp_path):
        (tmp_path / ".github" / "memory-bank").mkdir(parents=True)
        (tmp_path / ".github" / "memory-bank" / "test.md").write_text("x", encoding="utf-8")
        tg = tmp_path / "template" / ".github"
        tg.mkdir(parents=True)
        errors = vcs.check_template_sync(tmp_path)
        assert any("Missing template dir" in e for e in errors)

    def test_missing_file(self, tmp_path):
        (tmp_path / ".github" / "memory-bank").mkdir(parents=True)
        (tmp_path / ".github" / "memory-bank" / "test.md").write_text("x", encoding="utf-8")
        tmb = tmp_path / "template" / ".github" / "memory-bank"
        tmb.mkdir(parents=True)
        errors = vcs.check_template_sync(tmp_path)
        assert any("missing: test.md" in e for e in errors)

    def test_copilot_instructions_missing(self, tmp_path):
        (tmp_path / ".github").mkdir(parents=True)
        (tmp_path / ".github" / "copilot-instructions.md").write_text("x", encoding="utf-8")
        (tmp_path / "template" / ".github").mkdir(parents=True)
        errors = vcs.check_template_sync(tmp_path)
        assert any("copilot-instructions.md missing" in e for e in errors)

class TestVcsCheckMemoryBankQuality:
    def test_no_dir(self, tmp_path):
        errors = vcs.check_memory_bank_quality(tmp_path)
        assert not errors

    def test_missing_heading(self, tmp_path):
        mb = tmp_path / ".github" / "memory-bank"
        mb.mkdir(parents=True)
        (mb / "artifact-rules.md").write_text("# Rules\n## Random\nContent\n", encoding="utf-8")
        errors = vcs.check_memory_bank_quality(tmp_path)
        assert any("missing required heading" in e for e in errors)

    def test_orphan_section(self, tmp_path):
        mb = tmp_path / ".github" / "memory-bank"
        mb.mkdir(parents=True)
        content = "# Rules\n## Task\ncontent\n## Empty Section\n## Code\ncontent\n"
        (mb / "artifact-rules.md").write_text(content, encoding="utf-8")
        errors = vcs.check_memory_bank_quality(tmp_path)
        assert any("orphan section" in e for e in errors)

    def test_long_file_warning(self, tmp_path):
        mb = tmp_path / ".github" / "memory-bank"
        mb.mkdir(parents=True)
        lines = ["# Rules\n## Task\ncontent\n## Plan\ncontent\n## Code\ncontent\n## Verify\ncontent\n"]
        lines.extend(["x\n"] * 130)
        (mb / "artifact-rules.md").write_text("".join(lines), encoding="utf-8")
        errors = vcs.check_memory_bank_quality(tmp_path)
        assert any("lines" in e for e in errors)

    def test_code_fence_skips_headings(self, tmp_path):
        """Cover L285-286,288: code fence at top level skips inner headings."""
        mb = tmp_path / ".github" / "memory-bank"
        mb.mkdir(parents=True)
        # Code fence wrapping a heading — the heading inside shouldn't be
        # treated as a real section (so no orphan warning for it)
        content = (
            "# Rules\n"
            "## Task\n"
            "content\n"
            "```\n"
            "## Fake Heading Inside Fence\n"
            "```\n"
            "## Plan\n"
            "content\n"
            "## Code\n"
            "content\n"
            "## Verify\n"
            "content\n"
        )
        (mb / "artifact-rules.md").write_text(content, encoding="utf-8")
        errors = vcs.check_memory_bank_quality(tmp_path)
        # The "Fake Heading Inside Fence" should NOT produce an orphan warning
        assert not any("Fake Heading" in e for e in errors)

    def test_heading_with_code_fence_content(self, tmp_path):
        """Cover L296,298-300: heading followed by code fence counts as content."""
        mb = tmp_path / ".github" / "memory-bank"
        mb.mkdir(parents=True)
        content = (
            "# Rules\n"
            "## Task\n"
            "```python\n"
            "print('hello')\n"
            "```\n"
            "## Plan\n"
            "content\n"
            "## Code\n"
            "content\n"
            "## Verify\n"
            "content\n"
        )
        (mb / "artifact-rules.md").write_text(content, encoding="utf-8")
        errors = vcs.check_memory_bank_quality(tmp_path)
        # ## Task has code fence as content — should NOT be orphan
        assert not any("orphan" in e and "Task" in e for e in errors)

class TestVcsUtf8Wrapping:
    """Cover L19, L21: module-level stdout/stderr UTF-8 wrapping."""

    def test_wraps_non_utf8_stdout(self):
        # init_streams is now an explicit CLI helper rather than module-import side effect;
        # call it directly instead of relying on importlib.reload to trigger the wrap.
        import io as _io
        orig_stdout = sys.stdout
        try:
            fake = _io.TextIOWrapper(_io.BytesIO(), encoding="ascii")
            sys.stdout = fake
            vcs.init_streams()
            assert sys.stdout.encoding == "utf-8"
        finally:
            sys.stdout = orig_stdout

    def test_wraps_non_utf8_stderr(self):
        import io as _io
        orig_stderr = sys.stderr
        try:
            fake = _io.TextIOWrapper(_io.BytesIO(), encoding="ascii")
            sys.stderr = fake
            vcs.init_streams()
            assert sys.stderr.encoding == "utf-8"
        finally:
            sys.stderr = orig_stderr


# ─────────────────────────────────────────────
# prompt_regression_validator — deeper branches
# ─────────────────────────────────────────────

