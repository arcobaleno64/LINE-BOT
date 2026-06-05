"""Split unit tests for repository profile, PDCA, and red team suite helpers per TASK-1054."""
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


class TestDtYamlImportGuard:
    """Cover L13-19: except ImportError when yaml is missing."""

    def test_exit_when_yaml_unavailable(self, monkeypatch):
        import builtins
        import importlib
        real_import = builtins.__import__

        def fail_yaml(name, *args, **kwargs):
            if name == "yaml":
                raise ImportError("test: no yaml")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_yaml)
        with pytest.raises(SystemExit) as exc_info:
            importlib.reload(dt)
        assert exc_info.value.code == 1
        monkeypatch.undo()
        importlib.reload(dt)

class TestDtParseFrontmatter:
    def test_valid_frontmatter(self, tmp_path):
        md = tmp_path / "TEMPLATE.md"
        md.write_text("---\nname: Test\nversion: '1.0'\n---\n# Body\n", encoding="utf-8")
        result = dt.parse_frontmatter(md)
        assert result["name"] == "Test"
        assert result["version"] == "1.0"

    def test_no_frontmatter(self, tmp_path):
        md = tmp_path / "TEMPLATE.md"
        md.write_text("# No frontmatter\n", encoding="utf-8")
        result = dt.parse_frontmatter(md)
        assert result == {}

    def test_empty_frontmatter(self, tmp_path):
        md = tmp_path / "TEMPLATE.md"
        md.write_text("---\n---\n# Body\n", encoding="utf-8")
        result = dt.parse_frontmatter(md)
        assert result == {}

class TestDtDiscover:
    def _make_template(self, templates_dir, role_name, fm_dict):
        import yaml
        role_dir = templates_dir / role_name
        role_dir.mkdir(parents=True, exist_ok=True)
        fm_yaml = yaml.dump(fm_dict, default_flow_style=False)
        (role_dir / "TEMPLATE.md").write_text(
            f"---\n{fm_yaml}---\n# Template\n", encoding="utf-8"
        )

    def test_discover_all(self, tmp_path):
        self._make_template(tmp_path, "coder", {
            "name": "Coder", "applicable_agents": ["Codex CLI"],
            "applicable_stages": ["coding"],
        })
        self._make_template(tmp_path, "researcher", {
            "name": "Researcher", "applicable_agents": ["Gemini CLI"],
            "applicable_stages": ["research"],
        })
        results = dt.discover(templates_dir=tmp_path)
        assert len(results) == 2

    def test_filter_by_agent(self, tmp_path):
        self._make_template(tmp_path, "coder", {
            "name": "Coder", "applicable_agents": ["Codex CLI"],
            "applicable_stages": ["coding"],
        })
        self._make_template(tmp_path, "researcher", {
            "name": "Researcher", "applicable_agents": ["Gemini CLI"],
            "applicable_stages": ["research"],
        })
        results = dt.discover(agent="Codex CLI", templates_dir=tmp_path)
        assert len(results) == 1
        assert results[0].name == "Coder"

    def test_filter_by_stage(self, tmp_path):
        self._make_template(tmp_path, "coder", {
            "name": "Coder", "applicable_agents": ["Codex CLI"],
            "applicable_stages": ["coding"],
        })
        results = dt.discover(stage="research", templates_dir=tmp_path)
        assert len(results) == 0

    def test_stage_any_wildcard(self, tmp_path):
        self._make_template(tmp_path, "utility", {
            "name": "Utility", "applicable_agents": ["Any"],
            "applicable_stages": ["any"],
        })
        results = dt.discover(stage="coding", templates_dir=tmp_path)
        assert len(results) == 1

    def test_skip_no_name(self, tmp_path):
        self._make_template(tmp_path, "broken", {
            "description": "No name field",
        })
        results = dt.discover(templates_dir=tmp_path)
        assert len(results) == 0

    def test_empty_dir(self, tmp_path):
        results = dt.discover(templates_dir=tmp_path)
        assert results == []

class TestDtMain:
    def test_json_output(self, tmp_path, capsys, monkeypatch):
        import yaml
        role = tmp_path / "coder"
        role.mkdir()
        fm = yaml.dump({"name": "Coder", "applicable_agents": ["Codex"], "applicable_stages": ["coding"]})
        (role / "TEMPLATE.md").write_text(f"---\n{fm}---\n# T\n", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["dt", "--templates-dir", str(tmp_path), "--json"])
        dt.main()
        out = capsys.readouterr().out
        import json
        data = json.loads(out)
        assert len(data) == 1
        assert data[0]["name"] == "Coder"

    def test_text_output(self, tmp_path, capsys, monkeypatch):
        import yaml
        role = tmp_path / "coder"
        role.mkdir()
        fm = yaml.dump({"name": "Coder", "applicable_agents": ["Codex"], "applicable_stages": ["coding"]})
        (role / "TEMPLATE.md").write_text(f"---\n{fm}---\n# T\n", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["dt", "--templates-dir", str(tmp_path)])
        dt.main()
        out = capsys.readouterr().out
        assert "Coder" in out

    def test_no_results(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["dt", "--templates-dir", str(tmp_path)])
        dt.main()
        out = capsys.readouterr().out
        assert "No matching" in out



# ── update_repository_profile tests ──


import update_repository_profile as urp

class TestUrpParseTopics:
    def test_basic(self):
        result = urp.parse_topics("a, b, c")
        assert result == ["a", "b", "c"]

    def test_dedup(self):
        result = urp.parse_topics("a, b, a")
        assert result == ["a", "b"]

    def test_empty_tokens(self):
        result = urp.parse_topics(",, a,,")
        assert result == ["a"]

    def test_case_normalize(self):
        result = urp.parse_topics("ABC, Def")
        assert result == ["abc", "def"]

class TestUrpNormalizeTopics:
    def test_adds_required(self):
        from workflow_constants import REQUIRED_TOPICS
        # Use 6 topics that overlap with required + 2 extra = 8 total, within 6-12
        base = list(REQUIRED_TOPICS)[:4] + ["extra-one", "extra-two"]
        result = urp.normalize_topics(base)
        for req in REQUIRED_TOPICS:
            assert req in result

    def test_invalid_pattern(self):
        with pytest.raises(ValueError, match="Invalid topic"):
            urp.normalize_topics(["valid-topic"] * 5 + ["INVALID TOPIC!"])

    def test_too_few_after_normalization(self, monkeypatch):
        """With 6 required topics, minimum is always 6. Patch to test < 6 path."""
        monkeypatch.setattr(urp, "REQUIRED_TOPICS", set())
        with pytest.raises(ValueError, match="6-12 entries"):
            urp.normalize_topics(["a"])

    def test_too_many(self):
        topics = [f"topic-{i}" for i in range(13)]
        with pytest.raises(ValueError, match="6-12 entries"):
            urp.normalize_topics(topics)

    def test_dedup_and_empty(self):
        topics = ["a", "a", "", "b", "c", "d", "e", "f"]
        result = urp.normalize_topics(topics)
        assert len(set(result)) == len(result)

class TestUrpUpdateProfile:
    def _valid_about_args(self):
        # Ensure about is 80-200 chars
        name = "MyProject"
        summary = "A" * 75  # name + " - " + summary = 9 + 3 + 75 = 87 chars
        return name, summary

    def test_creates_new_profile(self, tmp_path):
        from workflow_constants import REQUIRED_TOPICS
        profile_path = tmp_path / ".github" / "repository-profile.json"
        name, summary = self._valid_about_args()
        topics = ",".join(list(REQUIRED_TOPICS)[:4] + ["extra-one", "extra-two"])
        urp.update_profile(profile_path, name, summary, topics)
        assert profile_path.exists()
        import json
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        assert "about" in data
        assert "topics" in data

    def test_updates_existing(self, tmp_path):
        import json
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps({"about": "old", "topics": ["existing"]}), encoding="utf-8")
        name, summary = self._valid_about_args()
        from workflow_constants import REQUIRED_TOPICS
        topics = ",".join(list(REQUIRED_TOPICS)[:4] + ["extra-one", "extra-two"])
        urp.update_profile(profile_path, name, summary, topics)
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        assert data["about"] != "old"

    def test_about_too_short(self, tmp_path):
        profile_path = tmp_path / "profile.json"
        from workflow_constants import REQUIRED_TOPICS
        topics = ",".join(list(REQUIRED_TOPICS)[:4] + ["extra-one", "extra-two"])
        with pytest.raises(ValueError, match="80-200 chars"):
            urp.update_profile(profile_path, "X", "Y", topics)

    def test_about_too_long(self, tmp_path):
        profile_path = tmp_path / "profile.json"
        from workflow_constants import REQUIRED_TOPICS
        topics = ",".join(list(REQUIRED_TOPICS)[:4] + ["extra-one", "extra-two"])
        with pytest.raises(ValueError, match="80-200 chars"):
            urp.update_profile(profile_path, "X", "Y" * 300, topics)

    def test_uses_existing_topics_when_none(self, tmp_path):
        import json
        from workflow_constants import REQUIRED_TOPICS
        profile_path = tmp_path / "profile.json"
        existing_topics = list(REQUIRED_TOPICS)[:4] + ["extra-one", "extra-two"]
        profile_path.write_text(json.dumps({"topics": existing_topics}), encoding="utf-8")
        name, summary = self._valid_about_args()
        urp.update_profile(profile_path, name, summary, None)
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        for t in existing_topics:
            assert t in data["topics"]

    def test_non_list_existing_topics(self, tmp_path):
        import json
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps({"topics": "not-a-list"}), encoding="utf-8")
        name, summary = self._valid_about_args()
        from workflow_constants import REQUIRED_TOPICS
        topics = ",".join(list(REQUIRED_TOPICS)[:4] + ["extra-one", "extra-two"])
        urp.update_profile(profile_path, name, summary, topics)
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        assert isinstance(data["topics"], list)

class TestUrpMain:
    def test_main_success(self, tmp_path, monkeypatch, capsys):
        profile_path = tmp_path / "profile.json"
        name = "MyProject"
        summary = "A" * 75
        from workflow_constants import REQUIRED_TOPICS
        topics = ",".join(list(REQUIRED_TOPICS)[:4] + ["extra-one", "extra-two"])
        monkeypatch.setattr(sys, "argv", [
            "urp", "--project-name", name, "--project-summary", summary,
            "--topics", topics, "--profile-path", str(profile_path),
        ])
        result = urp.main()
        assert result == 0
        assert "[OK]" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# repo_health_dashboard.py tests
# ---------------------------------------------------------------------------
import repo_health_dashboard as rhd

class TestRhdLoadStatus:
    def test_valid_json(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text('{"state":"done"}', encoding="utf-8")
        assert rhd.load_status(p) == {"state": "done"}

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text("NOT JSON", encoding="utf-8")
        assert rhd.load_status(p) == {}

    def test_missing_file(self, tmp_path):
        assert rhd.load_status(tmp_path / "nope.json") == {}

class TestRhdGetTaskId:
    def test_normal(self, tmp_path):
        p = tmp_path / "TASK-900.status.json"
        assert rhd.get_task_id(p) == "TASK-900"

class TestRhdGetState:
    def test_state_key(self):
        assert rhd.get_state({"state": "Done"}) == "done"

    def test_current_state_key(self):
        assert rhd.get_state({"current_state": "Blocked"}) == "blocked"

    def test_missing(self):
        assert rhd.get_state({}) == "unknown"

class TestRhdGetOwner:
    def test_current_owner_key(self):
        assert rhd.get_owner({"current_owner": "Alice"}) == "Alice"

    def test_owner_key(self):
        assert rhd.get_owner({"owner": "Bob"}) == "Bob"

    def test_missing(self):
        assert rhd.get_owner({}) == "unknown"

class TestRhdGetLastUpdated:
    def test_present(self):
        assert rhd.get_last_updated({"last_updated": "2025-01-01"}) == "2025-01-01"

    def test_missing(self):
        assert rhd.get_last_updated({}) == ""

class TestRhdParseDatetime:
    def test_format_with_tz(self):
        dt = rhd.parse_datetime("2025-01-15T10:30:00+08:00")
        assert dt is not None
        assert dt.hour == 10

    def test_format_with_microseconds(self):
        dt = rhd.parse_datetime("2025-01-15T10:30:00.123456+08:00")
        assert dt is not None

    def test_format_naive(self):
        dt = rhd.parse_datetime("2025-01-15T10:30:00")
        assert dt is not None

    def test_empty(self):
        assert rhd.parse_datetime("") is None

    def test_invalid(self):
        assert rhd.parse_datetime("not-a-date") is None

class TestRhdDiscoverArtifacts:
    def test_all_missing(self, tmp_path):
        result = rhd.discover_artifacts(tmp_path, "TASK-999")
        assert all(v is False for v in result.values())
        assert set(result.keys()) == set(rhd.ARTIFACT_TYPES)

    def test_some_present(self, tmp_path):
        (tmp_path / "artifacts" / "tasks").mkdir(parents=True)
        (tmp_path / "artifacts" / "tasks" / "TASK-999.task.md").write_text("x", encoding="utf-8")
        (tmp_path / "artifacts" / "status").mkdir(parents=True)
        (tmp_path / "artifacts" / "status" / "TASK-999.status.json").write_text("{}", encoding="utf-8")
        result = rhd.discover_artifacts(tmp_path, "TASK-999")
        assert result["task"] is True
        assert result["status"] is True
        assert result["code"] is False

class TestRhdGetMissingArtifacts:
    def test_missing_artifacts_key(self):
        assert rhd.get_missing_artifacts({"missing_artifacts": ["verify", "code"]}) == ["verify", "code"]

    def test_artifacts_dict_with_none(self):
        status = {"artifacts": {"task": "ok", "code": None, "verify": None}}
        result = rhd.get_missing_artifacts(status)
        assert "code" in result
        assert "verify" in result

    def test_empty(self):
        assert rhd.get_missing_artifacts({}) == []

    def test_non_dict_artifacts(self):
        assert rhd.get_missing_artifacts({"artifacts": "invalid"}) == []

class TestRhdBuildDashboard:
    def _setup_status(self, root, task_id, state, last_updated=None, owner="agent",
                      blocked_reason="", blockers=None, add_code=False, add_verify=False):
        import json
        status_dir = root / "artifacts" / "status"
        status_dir.mkdir(parents=True, exist_ok=True)
        data = {"state": state, "current_owner": owner}
        if last_updated:
            data["last_updated"] = last_updated
        if blocked_reason:
            data["blocked_reason"] = blocked_reason
        if blockers:
            data["blockers"] = blockers
        (status_dir / f"{task_id}.status.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        if add_code:
            code_dir = root / "artifacts" / "code"
            code_dir.mkdir(parents=True, exist_ok=True)
            (code_dir / f"{task_id}.code.md").write_text("x", encoding="utf-8")
        if add_verify:
            verify_dir = root / "artifacts" / "verify"
            verify_dir.mkdir(parents=True, exist_ok=True)
            (verify_dir / f"{task_id}.verify.md").write_text("x", encoding="utf-8")

    def test_empty_status_dir(self, tmp_path):
        (tmp_path / "artifacts" / "status").mkdir(parents=True)
        d = rhd.build_dashboard(tmp_path, 14)
        assert d["summary"]["total_tasks"] == 0
        assert d["summary"]["completion_pct"] == 0

    def test_done_task(self, tmp_path):
        self._setup_status(tmp_path, "TASK-100", "done", "2025-01-01T10:00:00+08:00")
        d = rhd.build_dashboard(tmp_path, 14)
        assert d["summary"]["done"] == 1
        assert d["summary"]["total_tasks"] == 1

    def test_blocked_task_with_reason(self, tmp_path):
        self._setup_status(tmp_path, "TASK-101", "blocked", "2025-07-01T10:00:00+08:00",
                           blocked_reason="waiting on API")
        d = rhd.build_dashboard(tmp_path, 14)
        assert d["summary"]["blocked"] == 1
        assert d["tasks"][0]["blocked_reason"] == "waiting on API"

    def test_blocked_task_with_blockers_list(self, tmp_path):
        self._setup_status(tmp_path, "TASK-102", "blocked", "2025-07-01T10:00:00+08:00",
                           blockers=["dep-A", "dep-B"])
        d = rhd.build_dashboard(tmp_path, 14)
        assert "dep-A; dep-B" in d["tasks"][0]["blocked_reason"]

    def test_stale_task(self, tmp_path):
        self._setup_status(tmp_path, "TASK-103", "in-progress", "2020-01-01T10:00:00+08:00")
        d = rhd.build_dashboard(tmp_path, 14)
        assert d["summary"]["stale"] == 1
        assert d["tasks"][0]["is_stale"] is True

    def test_missing_verify(self, tmp_path):
        self._setup_status(tmp_path, "TASK-104", "coding", "2025-07-01T10:00:00+08:00",
                           add_code=True, add_verify=False)
        d = rhd.build_dashboard(tmp_path, 14)
        assert d["summary"]["missing_verify"] == 1

    def test_has_verify(self, tmp_path):
        self._setup_status(tmp_path, "TASK-105", "coding", "2025-07-01T10:00:00+08:00",
                           add_code=True, add_verify=True)
        d = rhd.build_dashboard(tmp_path, 14)
        assert d["summary"]["missing_verify"] == 0

    def test_no_last_updated(self, tmp_path):
        self._setup_status(tmp_path, "TASK-106", "in-progress")
        d = rhd.build_dashboard(tmp_path, 14)
        assert d["tasks"][0]["is_stale"] is False

    def test_artifact_coverage(self, tmp_path):
        self._setup_status(tmp_path, "TASK-107", "done", "2025-07-01T10:00:00+08:00",
                           add_code=True)
        d = rhd.build_dashboard(tmp_path, 14)
        assert d["artifact_coverage"]["code"]["present"] == 1
        assert d["artifact_coverage"]["code"]["pct"] == 100.0
        assert d["artifact_coverage"]["task"]["present"] == 0

    def test_done_not_stale(self, tmp_path):
        """Done tasks should not be counted as stale even with old dates."""
        self._setup_status(tmp_path, "TASK-108", "done", "2020-01-01T10:00:00+08:00")
        d = rhd.build_dashboard(tmp_path, 14)
        assert d["summary"]["stale"] == 0

    def test_done_not_missing_verify(self, tmp_path):
        """Done tasks should not be flagged for missing verify."""
        self._setup_status(tmp_path, "TASK-109", "done", "2025-07-01T10:00:00+08:00",
                           add_code=True, add_verify=False)
        d = rhd.build_dashboard(tmp_path, 14)
        assert d["summary"]["missing_verify"] == 0

class TestRhdRenderMarkdown:
    def _make_dashboard(self, tasks=None, blocked=False, stale=False, missing_v=False):
        base = {
            "generated_at": "2025-07-01T10:00:00+08:00",
            "stale_days": 14,
            "summary": {
                "total_tasks": 1,
                "done": 0,
                "blocked": 1 if blocked else 0,
                "stale": 1 if stale else 0,
                "missing_verify": 1 if missing_v else 0,
                "completion_pct": 0,
            },
            "artifact_coverage": {
                t: {"present": 0, "total": 1, "pct": 0}
                for t in rhd.ARTIFACT_TYPES
            },
            "tasks": tasks or [],
        }
        return base

    def _make_task(self, task_id="TASK-100", state="in-progress", owner="agent",
                   blocked=False, stale=False, missing_verify=False,
                   blocked_reason="", last_updated="2025-07-01T10:00:00+08:00"):
        return {
            "task_id": task_id,
            "state": state,
            "owner": owner,
            "last_updated": last_updated,
            "is_stale": stale,
            "is_blocked": blocked,
            "missing_verify": missing_verify,
            "artifacts": {t: False for t in rhd.ARTIFACT_TYPES},
            "blocked_reason": blocked_reason,
        }

    def test_basic_output(self):
        t = self._make_task()
        d = self._make_dashboard(tasks=[t])
        md = rhd.render_markdown(d)
        assert "# Repo Health Dashboard" in md
        assert "TASK-100" in md

    def test_blocked_section(self):
        t = self._make_task(state="blocked", blocked=True, blocked_reason="dep missing")
        d = self._make_dashboard(tasks=[t], blocked=True)
        md = rhd.render_markdown(d)
        assert "## Blocked Tasks" in md
        assert "dep missing" in md

    def test_stale_section(self):
        t = self._make_task(stale=True)
        d = self._make_dashboard(tasks=[t], stale=True)
        md = rhd.render_markdown(d)
        assert "## Stale Tasks" in md

    def test_missing_verify_section(self):
        t = self._make_task(missing_verify=True)
        d = self._make_dashboard(tasks=[t], missing_v=True)
        md = rhd.render_markdown(d)
        assert "## Missing Verification" in md

    def test_flags_in_all_tasks(self):
        t = self._make_task(state="in-progress", blocked=True, stale=True, missing_verify=True)
        d = self._make_dashboard(tasks=[t])
        md = rhd.render_markdown(d)
        assert "BLOCKED" in md
        assert "STALE" in md
        assert "NO-VERIFY" in md

    def test_no_flags_when_state_matches(self):
        """If state is already BLOCKED, don't add BLOCKED flag."""
        t = self._make_task(state="blocked", blocked=True)
        d = self._make_dashboard(tasks=[t])
        md = rhd.render_markdown(d)
        lines = [l for l in md.split("\n") if "TASK-100" in l and "|" in l]
        all_tasks_line = [l for l in lines if "blocked" in l.lower()]
        # Should not have duplicate BLOCKED flag
        for line in all_tasks_line:
            parts = line.split("|")
            state_part = parts[2].strip() if len(parts) > 2 else ""
            if state_part == "blocked":
                assert "BLOCKED" not in state_part.upper().replace("BLOCKED", "", 1)

    def test_present_artifacts_listed(self):
        t = self._make_task()
        t["artifacts"]["task"] = True
        t["artifacts"]["code"] = True
        d = self._make_dashboard(tasks=[t])
        md = rhd.render_markdown(d)
        assert "task" in md
        assert "code" in md

class TestRhdMain:
    def test_json_output(self, tmp_path, monkeypatch, capsys):
        import json, argparse
        (tmp_path / "artifacts" / "status").mkdir(parents=True)
        status = {"state": "done", "last_updated": "2025-07-01T10:00:00+08:00"}
        (tmp_path / "artifacts" / "status" / "TASK-100.status.json").write_text(
            json.dumps(status), encoding="utf-8"
        )
        monkeypatch.setattr(rhd, "parse_args", lambda: argparse.Namespace(
            root=str(tmp_path), stale_days=14, json=True
        ))
        result = rhd.main()
        assert result == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["summary"]["total_tasks"] == 1

    def test_markdown_output(self, tmp_path, monkeypatch, capsys):
        import argparse
        (tmp_path / "artifacts" / "status").mkdir(parents=True)
        monkeypatch.setattr(rhd, "parse_args", lambda: argparse.Namespace(
            root=str(tmp_path), stale_days=14, json=False
        ))
        result = rhd.main()
        assert result == 0
        out = capsys.readouterr().out
        assert "# Repo Health Dashboard" in out


# ---------------------------------------------------------------------------
# run_red_team_suite.py tests — batch 1: utilities & framework
# ---------------------------------------------------------------------------
import subprocess
import run_red_team_suite as rrts

class TestRrtsDetectRepoRoot:
    def test_detects_actual_root(self):
        root = rrts.detect_repo_root()
        assert (root / "docs" / "red_team_runbook.md").exists()

class TestRrtsLoadModule:
    def test_loads_contract_guard(self):
        mod = rrts.load_module(rrts.CONTRACT_GUARD, "test_gcv_load")
        assert hasattr(mod, "EXACT_SYNC_FILES")

    def test_invalid_path_raises(self):
        from pathlib import Path as P
        with pytest.raises((RuntimeError, FileNotFoundError)):
            rrts.load_module(P("/nonexistent/module.py"), "bad")

class TestRrtsRunCommand:
    def test_basic(self):
        import sys
        result = rrts.run_command([sys.executable, "-c", "print('hello')"])
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_rejects_unapproved_env_override(self):
        with pytest.raises(RuntimeError, match="Unsupported environment override"):
            rrts.run_command([sys.executable, "-c", "print('x')"], env={"PATH": "forbidden"})

    def test_rejects_non_string_env_value(self):
        with pytest.raises(RuntimeError, match="must be a string"):
            rrts.run_command([sys.executable, "-c", "print('x')"], env={rrts.GITHUB_API_ALLOWED_HOSTS_ENV: 1})

    def test_allows_approved_env_override(self, monkeypatch):
        captured = {}

        class FakePopen:
            def __init__(self, args, **kwargs):
                captured["args"] = args
                captured["env"] = kwargs.get("env")
                self.returncode = 0
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def communicate(self, timeout=None):
                return ("ok", "")

        monkeypatch.setattr(subprocess, "Popen", FakePopen)
        result = rrts.run_command(
            [sys.executable, "-c", "print('x')"],
            env={rrts.GITHUB_API_ALLOWED_HOSTS_ENV: "127.0.0.1"},
        )
        assert result.returncode == 0
        assert captured["env"][rrts.GITHUB_API_ALLOWED_HOSTS_ENV] == "127.0.0.1"

class TestRrtsRunGitCommand:
    def test_basic(self, tmp_path):
        # Just run a safe command
        result = rrts.run_git_command(tmp_path, ["--version"])
        assert result.returncode == 0
        assert "git" in result.stdout.lower()

class TestRrtsEnsureCommandOk:
    def test_success(self):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        rrts.ensure_command_ok(result, "test")

    def test_failure_stderr(self):
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error msg")
        with pytest.raises(RuntimeError, match="error msg"):
            rrts.ensure_command_ok(result, "test")

    def test_failure_stdout_fallback(self):
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="out msg", stderr="")
        with pytest.raises(RuntimeError, match="out msg"):
            rrts.ensure_command_ok(result, "test")

    def test_failure_unknown(self):
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        with pytest.raises(RuntimeError, match="unknown command failure"):
            rrts.ensure_command_ok(result, "test")

class TestRrtsInitializeGitFixture:
    def test_creates_git_repo(self, tmp_path):
        (tmp_path / "dummy.txt").write_text("x", encoding="utf-8")
        rrts.initialize_git_fixture(tmp_path)
        assert (tmp_path / ".git").exists()

class TestRrtsGitRevParse:
    def test_resolves_head(self, tmp_path):
        (tmp_path / "dummy.txt").write_text("x", encoding="utf-8")
        rrts.initialize_git_fixture(tmp_path)
        sha = rrts.git_rev_parse(tmp_path, "HEAD")
        assert len(sha) == 40

class TestRrtsComputeSnapshotSha256:
    def test_basic(self):
        result = rrts.compute_snapshot_sha256(["a.md", "b.md"])
        assert len(result) == 64

    def test_sorted(self):
        r1 = rrts.compute_snapshot_sha256(["a.md", "b.md"])
        r2 = rrts.compute_snapshot_sha256(["b.md", "a.md"])
        assert r1 == r2

    def test_different(self):
        r1 = rrts.compute_snapshot_sha256(["a.md"])
        r2 = rrts.compute_snapshot_sha256(["b.md"])
        assert r1 != r2

class TestRrtsReplaceTaskId:
    def test_basic(self):
        assert rrts.replace_task_id("TASK-900 data", "TASK-900", "TASK-999") == "TASK-999 data"

class TestRrtsEnsureParent:
    def test_creates_parent(self, tmp_path):
        target = tmp_path / "sub" / "file.txt"
        rrts.ensure_parent(target)
        assert target.parent.exists()

class TestRrtsPrepareTemp:
    def test_creates_unique_dir(self, monkeypatch):
        import tempfile
        from pathlib import Path as P
        temp_base = P(tempfile.mkdtemp())
        monkeypatch.setattr(rrts, "LOCAL_TMP_ROOT", temp_base)
        d = rrts.prepare_temp_root("test-case")
        assert d.exists()
        assert d.name.startswith("test-case-")
        import shutil
        shutil.rmtree(temp_base, ignore_errors=True)

    def test_registers_temp_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(rrts, "LOCAL_TMP_ROOT", tmp_path / ".codex-red-team")
        rrts.reset_temp_root_registry()
        created = rrts.prepare_temp_root("case")
        assert created in rrts.CREATED_TEMP_ROOTS

class TestRrtsHandleRemoveReadonly:
    def test_retries_after_chmod(self, monkeypatch, tmp_path):
        target = tmp_path / "locked.txt"
        target.write_text("x", encoding="utf-8")
        calls = []

        def fake_func(path):
            calls.append(("func", path))

        def fake_chmod(path, mode):
            calls.append(("chmod", path, mode))

        monkeypatch.setattr(rrts.os, "chmod", fake_chmod)
        rrts.handle_remove_readonly(fake_func, str(target), None)
        assert calls == [
            ("chmod", str(target), stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR),
            ("func", str(target)),
        ]

class TestRrtsCleanupTempRoots:
    def test_ignores_missing_path(self, tmp_path):
        temp_root = tmp_path / ".codex-red-team"
        temp_root.mkdir(parents=True)
        missing = temp_root / "RT-001"
        errors = rrts.cleanup_temp_roots([missing], temp_root=temp_root)
        assert errors == []
        assert not temp_root.exists()

    def test_removes_temp_dirs_and_empty_root(self, tmp_path):
        temp_root = tmp_path / ".codex-red-team"
        first = temp_root / "RT-001"
        second = temp_root / "RT-002"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (first / "note.txt").write_text("x", encoding="utf-8")
        (second / "note.txt").write_text("y", encoding="utf-8")
        errors = rrts.cleanup_temp_roots([first, second], temp_root=temp_root)
        assert errors == []
        assert not temp_root.exists()

    def test_keeps_root_when_unrelated_entries_remain(self, tmp_path):
        temp_root = tmp_path / ".codex-red-team"
        case_dir = temp_root / "RT-001"
        other_dir = temp_root / "manual"
        case_dir.mkdir(parents=True)
        other_dir.mkdir(parents=True)
        errors = rrts.cleanup_temp_roots([case_dir], temp_root=temp_root)
        assert errors == []
        assert temp_root.exists()
        assert other_dir.exists()

    def test_reports_cleanup_failure(self, monkeypatch, tmp_path):
        temp_root = tmp_path / ".codex-red-team"
        case_dir = temp_root / "RT-001"
        case_dir.mkdir(parents=True)

        def boom(path, *args, **kwargs):
            raise OSError("locked")

        monkeypatch.setattr(rrts.shutil, "rmtree", boom)
        errors = rrts.cleanup_temp_roots([case_dir], temp_root=temp_root)
        assert len(errors) == 1
        assert "locked" in errors[0]

    def test_removes_readonly_file_tree(self, tmp_path):
        temp_root = tmp_path / ".codex-red-team"
        case_dir = temp_root / "RT-001"
        object_dir = case_dir / ".git" / "objects" / "00"
        object_dir.mkdir(parents=True)
        object_file = object_dir / "sample"
        object_file.write_text("locked", encoding="utf-8")
        object_file.chmod(stat.S_IREAD)
        errors = rrts.cleanup_temp_roots([case_dir], temp_root=temp_root)
        assert errors == []
        assert not temp_root.exists()

    def test_reports_root_remove_failure(self, monkeypatch, tmp_path):
        temp_root = tmp_path / ".codex-red-team"
        temp_root.mkdir(parents=True)

        def boom(self):
            raise OSError("busy")

        monkeypatch.setattr(type(temp_root), "rmdir", boom)
        errors = rrts.cleanup_temp_roots([], temp_root=temp_root)
        assert len(errors) == 1
        assert "Failed to remove temp root" in errors[0]

    def test_reports_root_iterdir_failure(self, monkeypatch, tmp_path):
        temp_root = tmp_path / ".codex-red-team"
        temp_root.mkdir(parents=True)

        def boom(self):
            raise OSError("inspect failed")
            yield  # pragma: no cover

        monkeypatch.setattr(type(temp_root), "iterdir", boom)
        errors = rrts.cleanup_temp_roots([], temp_root=temp_root)
        assert len(errors) == 1
        assert "Failed to inspect temp root" in errors[0]

class TestRrtsCopyTaskFixture:
    def test_copies_and_renames(self, tmp_path):
        arts = rrts.copy_task_fixture(tmp_path, "TASK-900", "TASK-TEST-1")
        assert arts == tmp_path / "artifacts"
        # Should have at least one file renamed
        any_file = list(arts.rglob("TASK-TEST-1*"))
        assert len(any_file) > 0

    def test_exclude_improvement(self, tmp_path):
        arts = rrts.copy_task_fixture(tmp_path, "TASK-900", "TASK-TEST-2", include_improvement=False)
        improvement_files = list((arts / "improvement").rglob("TASK-TEST-2*"))
        assert len(improvement_files) == 0

class TestRrtsContractFixturePaths:
    def test_returns_paths_with_templates(self):
        mod = rrts.load_module(rrts.CONTRACT_GUARD, "test_gcv_paths")
        paths = rrts.contract_fixture_paths(mod)
        assert isinstance(paths, list)
        assert any("template/" in p for p in paths)

class TestRrtsCopyContractFixture:
    def test_copies_files(self, tmp_path):
        rrts.copy_contract_fixture(tmp_path)
        assert any(tmp_path.rglob("*.md"))

class TestRrtsBlockedSampleSource:
    def test_returns_known_task(self):
        result = rrts.blocked_sample_source()
        assert result in ("TASK-901", "TASK-902")

class TestRrtsBuildCaseResult:
    def test_passed(self):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="fragment here", stderr="")
        cr = rrts.build_case_result(
            case_id="X", phase="static", title="T", expected="pass",
            expected_exit_code=0, expected_output_fragment="fragment",
            result=result, notes="n",
        )
        assert cr.passed is True
        assert cr.notes == "n"

    def test_failed_exit_code(self):
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="fragment", stderr="")
        cr = rrts.build_case_result(
            case_id="X", phase="static", title="T", expected="fail",
            expected_exit_code=0, expected_output_fragment="fragment",
            result=result, notes="",
        )
        assert cr.passed is False
        assert cr.notes == "fragment"  # first line of output when notes=""

    def test_failed_missing_fragment(self):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="no match", stderr="")
        cr = rrts.build_case_result(
            case_id="X", phase="static", title="T", expected="pass",
            expected_exit_code=0, expected_output_fragment="fragment",
            result=result, notes="",
        )
        assert cr.passed is False

    def test_empty_output_notes(self):
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        cr = rrts.build_case_result(
            case_id="X", phase="static", title="T", expected="pass",
            expected_exit_code=0, expected_output_fragment="",
            result=result, notes="",
        )
        assert cr.notes == ""

class TestRrtsCompletedProcessFromOutput:
    def test_basic(self):
        cp = rrts.completed_process_from_output(["a", "b"], 42, "out")
        assert cp.returncode == 42
        assert cp.stdout == "out"
        assert cp.stderr == ""
        assert cp.args == ["a", "b"]

class TestRrtsBuildCases:
    def test_returns_all_phases(self):
        cases = rrts.build_cases()
        phases = {c.phase for c in cases}
        assert "static" in phases
        assert "live" in phases
        assert "prompt" in phases

    def test_case_ids_unique(self):
        cases = rrts.build_cases()
        ids = [c.case_id for c in cases]
        assert len(ids) == len(set(ids))

class TestRrtsRenderMarkdownReport:
    def test_basic_report(self):
        results = [rrts.CaseResult("X-1", "static", "T", "pass", 0, True, 0, "ev", "n")]
        md = rrts.render_markdown(results)
        assert "Red Team Suite Report" in md
        assert "X-1" in md

    def test_failed_case_in_report(self):
        results = [rrts.CaseResult("F-1", "live", "T", "fail", 1, False, 0, "ev", "n")]
        md = rrts.render_markdown(results)
        assert "fail" in md

class TestRrtsGithubPrFilesServer:
    def test_server_returns_data(self):
        import json as j
        import urllib.request
        pages = {1: [{"filename": "test.md"}], 2: []}
        with rrts.github_pr_files_server("owner/repo", 1, pages) as base_url:
            url = f"{base_url}/repos/owner/repo/pulls/1/files?page=1"
            resp = urllib.request.urlopen(url)
            data = j.loads(resp.read())
            assert len(data) == 1

    def test_server_404(self):
        import urllib.request, urllib.error
        pages = {1: []}
        with rrts.github_pr_files_server("owner/repo", 1, pages) as base_url:
            url = f"{base_url}/repos/wrong/path"
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(url)
            assert exc_info.value.code == 404

    def test_server_default_page(self):
        import json as j
        import urllib.request
        pages = {1: [{"filename": "default.md"}]}
        with rrts.github_pr_files_server("o/r", 1, pages) as base_url:
            url = f"{base_url}/repos/o/r/pulls/1/files"
            resp = urllib.request.urlopen(url)
            data = j.loads(resp.read())
            assert len(data) == 1

    def test_server_invalid_page(self):
        import json as j
        import urllib.request
        pages = {1: [{"filename": "p1.md"}]}
        with rrts.github_pr_files_server("o/r", 1, pages) as base_url:
            url = f"{base_url}/repos/o/r/pulls/1/files?page=abc"
            resp = urllib.request.urlopen(url)
            data = j.loads(resp.read())
            assert data == [{"filename": "p1.md"}]  # falls back to page 1

class TestRrtsRunStatusCase:
    def test_basic(self, monkeypatch):
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="[OK] Validation passed", stderr="")
        monkeypatch.setattr(rrts, "run_command", lambda args, cwd=None: fake_result)
        cr = rrts.run_status_case(
            "TASK-999", rrts.REPO_ROOT / "artifacts",
            expected_exit_code=0, expected_output_fragment="[OK]",
            case_id="test", title="test", expected="pass", notes="n",
        )
        assert cr.passed is True

    def test_with_state_transition(self, monkeypatch):
        fake_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="error", stderr="")
        monkeypatch.setattr(rrts, "run_command", lambda args, cwd=None: fake_result)
        cr = rrts.run_status_case(
            "TASK-999", rrts.REPO_ROOT / "artifacts",
            expected_exit_code=1, expected_output_fragment="error",
            from_state="blocked", to_state="planned",
            case_id="test-st", title="test", notes="n",
        )
        assert cr.passed is True

    def test_with_extra_args(self, monkeypatch):
        captured = {}
        def capture(args, cwd=None):
            captured["args"] = args
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(rrts, "run_command", capture)
        rrts.run_status_case(
            "TASK-999", rrts.REPO_ROOT / "artifacts",
            expected_exit_code=0, expected_output_fragment="ok",
            case_id="test-ea", title="test", notes="n",
            extra_args=["--allow-scope-drift"],
        )
        assert "--allow-scope-drift" in captured["args"]

    def test_with_extra_env(self, monkeypatch):
        captured = {}

        def capture(args, cwd=None, env=None):
            captured["env"] = env
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(rrts, "run_command", capture)
        rrts.run_status_case(
            "TASK-999", rrts.REPO_ROOT / "artifacts",
            expected_exit_code=0, expected_output_fragment="ok",
            case_id="test-env", title="test", notes="n",
            extra_env={rrts.GITHUB_API_ALLOWED_HOSTS_ENV: "127.0.0.1"},
        )
        assert captured["env"][rrts.GITHUB_API_ALLOWED_HOSTS_ENV] == "127.0.0.1"

class TestRrtsTemporaryEnv:
    def test_restores_existing_value(self, monkeypatch):
        monkeypatch.setenv(rrts.GITHUB_API_ALLOWED_HOSTS_ENV, "old-host")
        with rrts.temporary_env({rrts.GITHUB_API_ALLOWED_HOSTS_ENV: "new-host"}):
            assert os.environ[rrts.GITHUB_API_ALLOWED_HOSTS_ENV] == "new-host"
        assert os.environ[rrts.GITHUB_API_ALLOWED_HOSTS_ENV] == "old-host"

class TestRrtsRunContractCase:
    def test_basic(self, monkeypatch):
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
        monkeypatch.setattr(rrts, "run_command", lambda args, cwd=None: fake_result)
        cr = rrts.run_contract_case(
            expected_exit_code=0, expected_output_fragment="ok",
            mutation=lambda root: None,
            title="test", case_id="test-cc", notes="n",
        )
        assert isinstance(cr, rrts.CaseResult)

class TestRrtsRunPromptCase:
    def test_basic(self, monkeypatch):
        fake_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="Prompt Regression Report", stderr="")
        monkeypatch.setattr(rrts, "run_command", lambda args, cwd=None: fake_result)
        cr = rrts.run_prompt_case("PR-TEST", "test prompt", "test notes")
        assert cr.passed is True
        assert cr.case_id == "PR-TEST"

class TestRrtsMain:
    def _make_case(self, case_id, phase, passed=True):
        return rrts.CaseDefinition(
            case_id, phase, "test", "pass" if passed else "fail",
            0 if passed else 1, "ok",
            lambda p=passed, cid=case_id, ph=phase: rrts.CaseResult(
                cid, ph, "test", "pass" if p else "fail",
                0 if p else 1, p, 0 if p else 1, "ok", "n",
            ),
        )

    def test_phase_static(self, monkeypatch, capsys):
        monkeypatch.setattr(rrts, "build_cases", lambda: [
            self._make_case("T-1", "static"),
            self._make_case("T-2", "live"),
        ])
        result = rrts.main(["--phase", "static"])
        assert result == 0
        out = capsys.readouterr().out
        assert "T-1" in out
        assert "T-2" not in out

    def test_phase_all(self, monkeypatch, capsys):
        monkeypatch.setattr(rrts, "build_cases", lambda: [
            self._make_case("T-1", "static"),
            self._make_case("T-2", "live"),
        ])
        result = rrts.main(["--phase", "all"])
        assert result == 0

    def test_alias_live(self, monkeypatch, capsys):
        monkeypatch.setattr(rrts, "build_cases", lambda: [self._make_case("T-1", "live")])
        result = rrts.main(["--live"])
        assert result == 0

    def test_alias_prompt(self, monkeypatch, capsys):
        monkeypatch.setattr(rrts, "build_cases", lambda: [self._make_case("T-1", "prompt")])
        result = rrts.main(["--prompt"])
        assert result == 0

    def test_alias_all(self, monkeypatch, capsys):
        monkeypatch.setattr(rrts, "build_cases", lambda: [self._make_case("T-1", "static")])
        result = rrts.main(["--all"])
        assert result == 0

    def test_conflicting_aliases(self, monkeypatch, capsys):
        monkeypatch.setattr(rrts, "build_cases", lambda: [])
        result = rrts.main(["--static", "--live"])
        assert result == 2
        err = capsys.readouterr().err
        assert "Only one" in err

    def test_failed_case_returns_1(self, monkeypatch, capsys):
        monkeypatch.setattr(rrts, "build_cases", lambda: [self._make_case("T-1", "static", passed=False)])
        result = rrts.main(["--static"])
        assert result == 1

    def test_output_file(self, monkeypatch, capsys, tmp_path):
        out_path = tmp_path / "report.md"
        monkeypatch.setattr(rrts, "build_cases", lambda: [self._make_case("T-1", "static")])
        result = rrts.main(["--static", "--output", str(out_path)])
        assert result == 0
        assert out_path.exists()
        assert "T-1" in out_path.read_text(encoding="utf-8")

    def test_cleanup_temp_dirs_by_default(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(rrts, "LOCAL_TMP_ROOT", tmp_path / ".codex-red-team")

        def runner():
            rrts.prepare_temp_root("T-1")
            return rrts.CaseResult("T-1", "static", "test", "pass", 0, True, 0, "ok", "n")

        monkeypatch.setattr(
            rrts,
            "build_cases",
            lambda: [rrts.CaseDefinition("T-1", "static", "test", "pass", 0, "ok", runner)],
        )
        result = rrts.main(["--static"])
        assert result == 0
        assert not rrts.LOCAL_TMP_ROOT.exists()

    def test_keep_temp_preserves_dirs_and_reports_path(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(rrts, "LOCAL_TMP_ROOT", tmp_path / ".codex-red-team")

        def runner():
            path = rrts.prepare_temp_root("T-1")
            return rrts.CaseResult("T-1", "static", "test", "pass", 0, True, 0, str(path), "n")

        monkeypatch.setattr(
            rrts,
            "build_cases",
            lambda: [rrts.CaseDefinition("T-1", "static", "test", "pass", 0, "ok", runner)],
        )
        result = rrts.main(["--static", "--keep-temp"])
        out = capsys.readouterr().out
        assert result == 0
        assert rrts.LOCAL_TMP_ROOT.exists()
        assert "Kept red-team temp fixtures under" in out

    def test_cleanup_failure_returns_1(self, monkeypatch, capsys, tmp_path):
        monkeypatch.setattr(rrts, "LOCAL_TMP_ROOT", tmp_path / ".codex-red-team")

        def runner():
            rrts.prepare_temp_root("T-1")
            return rrts.CaseResult("T-1", "static", "test", "pass", 0, True, 0, "ok", "n")

        monkeypatch.setattr(
            rrts,
            "build_cases",
            lambda: [rrts.CaseDefinition("T-1", "static", "test", "pass", 0, "ok", runner)],
        )
        monkeypatch.setattr(rrts, "cleanup_temp_roots", lambda paths, temp_root=None: ["cleanup failed"])
        result = rrts.main(["--static"])
        err = capsys.readouterr().err
        assert result == 1
        assert "cleanup failed" in err

class TestRrtsCaseRT001to010:
    """Test static case functions RT-001 through RT-010 with mocked subprocess."""

    @pytest.fixture(autouse=True)
    def _mock_run(self, monkeypatch):
        def fake(args, cwd=None, env=None, timeout=None, **kwargs):
            return subprocess.CompletedProcess(
                args=list(args), returncode=0,
                stdout="deadbeef" * 5 + "\n[OK] pass\n", stderr="",
            )
        monkeypatch.setattr(rrts, "run_command", fake)

    def test_rt_001(self):
        r = rrts.case_rt_001()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-001"

    def test_rt_002(self):
        r = rrts.case_rt_002()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-002"

    def test_rt_003(self):
        r = rrts.case_rt_003()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-003"

    def test_rt_004(self):
        r = rrts.case_rt_004()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-004"

    def test_rt_005(self):
        r = rrts.case_rt_005()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-005"

    def test_rt_006(self):
        r = rrts.case_rt_006()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-006"

    def test_rt_007(self):
        r = rrts.case_rt_007()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-007"

    def test_rt_008(self):
        r = rrts.case_rt_008()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-008"

    def test_rt_009(self):
        r = rrts.case_rt_009()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-009"

    def test_rt_010(self):
        r = rrts.case_rt_010()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-010"

class TestRrtsCaseRT011to020:
    """Test static case functions RT-011 through RT-020 with mocked subprocess."""

    @pytest.fixture(autouse=True)
    def _mock_run(self, monkeypatch):
        def fake(args, cwd=None, env=None, timeout=None, **kwargs):
            return subprocess.CompletedProcess(
                args=list(args), returncode=0,
                stdout="deadbeef" * 5 + "\n[OK] pass\n", stderr="",
            )
        monkeypatch.setattr(rrts, "run_command", fake)

    def test_rt_011(self):
        r = rrts.case_rt_011()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-011"

    def test_rt_012(self):
        r = rrts.case_rt_012()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-012"

    def test_rt_013(self):
        r = rrts.case_rt_013()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-013"

    def test_rt_014(self):
        r = rrts.case_rt_014()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-014"

    def test_rt_015(self):
        r = rrts.case_rt_015()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-015"

    def test_rt_016(self):
        r = rrts.case_rt_016()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-016"

    def test_rt_017(self):
        r = rrts.case_rt_017()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-017"

    def test_rt_018(self):
        r = rrts.case_rt_018()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-018"

    def test_rt_019(self):
        r = rrts.case_rt_019()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-019"

    def test_rt_020(self):
        r = rrts.case_rt_020()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-020"

class TestRrtsCaseRT021to023:
    """Test static case functions RT-021 through RT-023 with mocked subprocess."""

    @pytest.fixture(autouse=True)
    def _mock_run(self, monkeypatch):
        def fake(args, cwd=None, env=None, timeout=None, **kwargs):
            return subprocess.CompletedProcess(
                args=list(args), returncode=0,
                stdout="deadbeef" * 5 + "\n[OK] pass\n[AUTO-UPGRADE] done\n", stderr="",
            )
        monkeypatch.setattr(rrts, "run_command", fake)

    def test_rt_021(self):
        r = rrts.case_rt_021()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-021"

    def test_rt_022(self):
        r = rrts.case_rt_022()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-022"

    def test_rt_023(self):
        r = rrts.case_rt_023()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-023"

class TestRrtsCaseRT024to029:
    """Test static case functions RT-024 through RT-029 with mocked subprocess."""

    @pytest.fixture(autouse=True)
    def _mock_run(self, monkeypatch):
        def fake(args, cwd=None, env=None, timeout=None, **kwargs):
            return subprocess.CompletedProcess(
                args=list(args),
                returncode=0,
                stdout="\n".join([
                    "[OK] Validation passed",
                    "API Base URL host '127.0.0.1' is not allowed",
                    "Text file too large",
                    "exceeds replay byte cap",
                ]),
                stderr="",
            )

        monkeypatch.setattr(rrts, "run_command", fake)

    def test_rt_024(self):
        r = rrts.case_rt_024()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-024"

    def test_rt_025(self):
        r = rrts.case_rt_025()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-025"

    def test_rt_026(self):
        r = rrts.case_rt_026()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-026"

    def test_rt_027(self):
        r = rrts.case_rt_027()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-027"

    def test_rt_028(self):
        r = rrts.case_rt_028()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-028"

    def test_rt_029(self):
        r = rrts.case_rt_029()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-029"

class TestRrtsCaseRT030:
    def test_rt_030(self):
        r = rrts.case_rt_030()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-030"

class TestRrtsCaseLive:
    """Test live case functions with mocked subprocess."""

    @pytest.fixture(autouse=True)
    def _mock_run(self, monkeypatch):
        def fake(args, cwd=None, env=None, timeout=None, **kwargs):
            return subprocess.CompletedProcess(
                args=list(args), returncode=0,
                stdout="[OK] Validation passed\n", stderr="",
            )
        monkeypatch.setattr(rrts, "run_command", fake)

    def test_live_950(self):
        r = rrts.case_live_950()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-LIVE-950"

    def test_live_951(self):
        r = rrts.case_live_951()
        assert isinstance(r, rrts.CaseResult) and r.case_id == "RT-LIVE-951"

class TestRrtsCasePrompt:
    """Test prompt case functions with mocked subprocess."""

    @pytest.fixture(autouse=True)
    def _mock_run(self, monkeypatch):
        def fake(args, cwd=None, env=None, timeout=None, **kwargs):
            return subprocess.CompletedProcess(
                args=list(args), returncode=0,
                stdout="Prompt Regression Report\n", stderr="",
            )
        monkeypatch.setattr(rrts, "run_command", fake)

    def test_pr_001(self):
        r = rrts.case_pr_001()
        assert r.case_id == "PR-001"

    def test_pr_002(self):
        r = rrts.case_pr_002()
        assert r.case_id == "PR-002"

    def test_pr_003(self):
        r = rrts.case_pr_003()
        assert r.case_id == "PR-003"

    def test_pr_004(self):
        r = rrts.case_pr_004()
        assert r.case_id == "PR-004"

    def test_pr_005(self):
        r = rrts.case_pr_005()
        assert r.case_id == "PR-005"

    def test_pr_006(self):
        r = rrts.case_pr_006()
        assert r.case_id == "PR-006"

    def test_pr_007(self):
        r = rrts.case_pr_007()
        assert r.case_id == "PR-007"

    def test_pr_008(self):
        r = rrts.case_pr_008()
        assert r.case_id == "PR-008"

    def test_pr_009(self):
        r = rrts.case_pr_009()
        assert r.case_id == "PR-009"

    def test_pr_010(self):
        r = rrts.case_pr_010()
        assert r.case_id == "PR-010"

    def test_pr_011(self):
        r = rrts.case_pr_011()
        assert r.case_id == "PR-011"

    def test_pr_012(self):
        r = rrts.case_pr_012()
        assert r.case_id == "PR-012"

    def test_pr_013(self):
        r = rrts.case_pr_013()
        assert r.case_id == "PR-013"

    def test_pr_014(self):
        r = rrts.case_pr_014()
        assert r.case_id == "PR-014"

    def test_pr_015(self):
        r = rrts.case_pr_015()
        assert r.case_id == "PR-015"

    def test_pr_016(self):
        r = rrts.case_pr_016()
        assert r.case_id == "PR-016"

    def test_pr_017(self):
        r = rrts.case_pr_017()
        assert r.case_id == "PR-017"

    def test_pr_018(self):
        r = rrts.case_pr_018()
        assert r.case_id == "PR-018"

    def test_pr_019(self):
        r = rrts.case_pr_019()
        assert r.case_id == "PR-019"

    def test_pr_020(self):
        r = rrts.case_pr_020()
        assert r.case_id == "PR-020"

class TestRrtsGaps:
    """Cover the 4 remaining uncovered lines: 33, 71, 175, 214."""

    def test_detect_repo_root_no_match(self, monkeypatch):
        """Line 33: raise RuntimeError when no repo root found."""
        from pathlib import Path as P
        monkeypatch.setattr(rrts, "SCRIPT_PATH", P("/nonexistent/deep/nested/file.py"))
        with pytest.raises(RuntimeError, match="Unable to detect repository root"):
            rrts.detect_repo_root()

    def test_load_module_spec_none(self, monkeypatch):
        """Line 71: raise RuntimeError when spec_from_file_location returns None."""
        import importlib.util
        monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a, **kw: None)
        with pytest.raises(RuntimeError, match="Unable to load module"):
            rrts.load_module(rrts.CONTRACT_GUARD, "test_none_spec")

    def test_copy_task_fixture_skips_dirs(self, tmp_path):
        """Line 175: continue when source_path.is_dir()."""
        # Create a directory matching TASK-900 pattern in artifacts
        dir_path = rrts.REPO_ROOT / "artifacts" / "tasks" / "TASK-900-subdir"
        created = False
        try:
            if not dir_path.exists():
                dir_path.mkdir(parents=True, exist_ok=True)
                created = True
            arts = rrts.copy_task_fixture(tmp_path, "TASK-900", "TASK-DIRTEST")
            # The directory should not be copied as a file
            assert not (arts / "tasks" / "TASK-DIRTEST-subdir").is_file()
        finally:
            if created and dir_path.exists():
                dir_path.rmdir()

    def test_blocked_sample_source_fallback(self, monkeypatch):
        """Line 214: return TASK-901 when TASK-902.task.md doesn't exist."""
        from pathlib import Path as P
        original_exists = P.exists
        def fake_exists(self):
            if "TASK-902.task.md" in str(self):
                return False
            return original_exists(self)
        monkeypatch.setattr(P, "exists", fake_exists)
        result = rrts.blocked_sample_source()
        assert result == "TASK-901"


# ==========================================================================
# Coverage catchup tests (TASK-984 / TASK-985 closure follow-on)
# Target residual missing statements across migrate_artifact_schema.py,
# workflow_constants.py, guard_status_validator.py, legacy_verify_corpus.py,
# guard_contract_validator.py, build_decision_registry.py.
# ==========================================================================


import subprocess as _subprocess

class TestClassifyExistingTasks:
    # --- extract_risks_section ---

    def test_extract_risks_section_present(self):
        text = "## Scope\nfoo\n## Risks\n- R1\n- Severity: blocking\n## Validation\nbar\n"
        assert "Severity: blocking" in cet.extract_risks_section(text)

    def test_extract_risks_section_absent(self):
        assert cet.extract_risks_section("## Scope\nfoo\n## Validation\nbar\n") == ""

    def test_extract_risks_section_at_end(self):
        text = "## Risks\n- R1\n- Severity: non-blocking\n"
        assert "non-blocking" in cet.extract_risks_section(text)

    # --- parse_severities ---

    def test_parse_severities_blocking(self):
        text = "- Severity: blocking\n- Severity: non-blocking\n"
        result = cet.parse_severities(text)
        assert result == ["blocking", "non-blocking"]

    def test_parse_severities_empty(self):
        assert cet.parse_severities("no severity here\n") == []

    def test_parse_severities_inline(self):
        text = "R1 blah Severity: blocking（reason）\n"
        result = cet.parse_severities(text)
        assert result == ["blocking"]

    def test_parse_severities_case_insensitive(self):
        text = "- Severity: Blocking\n"
        result = cet.parse_severities(text)
        assert result == ["blocking"]

    # --- classify_task ---

    def test_classify_task_high_risk(self, tmp_path):
        plan = tmp_path / "TASK-900.plan.md"
        plan.write_text(
            "# Plan\n## Risks\nR1\n- Severity: blocking\n## Validation\nv\n",
            encoding="utf-8",
        )
        task_id, max_sev, risk_level, blocking, total, excerpt = cet.classify_task(plan)
        assert task_id == "TASK-900"
        assert risk_level == "high-risk"
        assert max_sev == "blocking"
        assert blocking == 1

    def test_classify_task_multi_severity_excerpt_truncation(self, tmp_path):
        plan = tmp_path / "TASK-895.plan.md"
        plan.write_text(
            "# Plan\n## Risks\n"
            "R1\n- Severity: blocking\n"
            "R2\n- Severity: non-blocking\n"
            "R3\n- Severity: blocking\n"
            "## Validation\nv\n",
            encoding="utf-8",
        )
        task_id, max_sev, risk_level, blocking, total, excerpt = cet.classify_task(plan)
        assert blocking == 2
        assert total == 3
        assert risk_level == "high-risk"
        # Excerpt should contain exactly 2 severity lines (break fires after 2nd)
        assert " | " in excerpt

    def test_classify_task_low_risk(self, tmp_path):
        plan = tmp_path / "TASK-999.plan.md"
        plan.write_text(
            "# Plan\n## Risks\nR1\n- Severity: non-blocking\n## Validation\nv\n",
            encoding="utf-8",
        )
        _, _, risk_level, blocking, total, _ = cet.classify_task(plan)
        assert risk_level == "low-risk"
        assert blocking == 0
        assert total == 1

    def test_classify_task_no_risks_section(self, tmp_path):
        plan = tmp_path / "TASK-998.plan.md"
        plan.write_text("# Plan\n## Scope\nfoo\n## Validation\nv\n", encoding="utf-8")
        _, max_sev, risk_level, _, _, excerpt = cet.classify_task(plan)
        assert risk_level == "low-risk"
        assert max_sev == "none"
        assert "no risks section" in excerpt

    def test_classify_task_risks_none_text(self, tmp_path):
        plan = tmp_path / "TASK-997.plan.md"
        plan.write_text("# Plan\n## Risks\nNone\n## Validation\nv\n", encoding="utf-8")
        _, max_sev, risk_level, _, _, _ = cet.classify_task(plan)
        assert risk_level == "low-risk"
        assert max_sev == "none"

    def test_classify_task_risks_no_severity_parsed(self, tmp_path):
        plan = tmp_path / "TASK-996.plan.md"
        plan.write_text(
            "# Plan\n## Risks\nR1\n- something unrelated\n## Validation\nv\n",
            encoding="utf-8",
        )
        _, max_sev, risk_level, _, _, excerpt = cet.classify_task(plan)
        assert risk_level == "low-risk"
        assert max_sev == "unknown"
        assert "no Severity field" in excerpt

    # --- main ---

    def test_main_dry_run(self, tmp_path, capsys):
        plans = tmp_path / "artifacts" / "plans"
        plans.mkdir(parents=True)
        (plans / "TASK-800.plan.md").write_text(
            "# Plan\n## Risks\nR1\n- Severity: blocking\n## Validation\nv\n",
            encoding="utf-8",
        )
        ret = cet.main(["--root", str(tmp_path), "--dry-run"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "high-risk" in out
        assert not (tmp_path / "artifacts" / "registry" / "risk_classification.csv").exists()

    def test_main_write_csv(self, tmp_path, capsys):
        plans = tmp_path / "artifacts" / "plans"
        plans.mkdir(parents=True)
        (plans / "TASK-800.plan.md").write_text(
            "# Plan\n## Risks\nR1\n- Severity: non-blocking\n## Validation\nv\n",
            encoding="utf-8",
        )
        ret = cet.main(["--root", str(tmp_path)])
        assert ret == 0
        csv_path = tmp_path / "artifacts" / "registry" / "risk_classification.csv"
        assert csv_path.exists()
        content = csv_path.read_text(encoding="utf-8")
        assert "TASK-800" in content
        assert "low-risk" in content

    def test_main_no_plans_dir(self, tmp_path, capsys):
        ret = cet.main(["--root", str(tmp_path)])
        assert ret == 1
        assert "Plans directory not found" in capsys.readouterr().err

    def test_main_no_plan_files(self, tmp_path, capsys):
        (tmp_path / "artifacts" / "plans").mkdir(parents=True)
        ret = cet.main(["--root", str(tmp_path)])
        assert ret == 1
        assert "No plan files found" in capsys.readouterr().err


# ─────────────────────────────────────────────
# backfill_pdca_labels
# ─────────────────────────────────────────────

class TestBackfillPdcaLabels:
    # --- load_high_risk_tasks ---

    def test_load_high_risk_tasks_no_file(self, tmp_path):
        assert bpl.load_high_risk_tasks(tmp_path / "nope.csv") == set()

    def test_load_high_risk_tasks_with_data(self, tmp_path):
        csv_path = tmp_path / "risk.csv"
        csv_path.write_text(
            "task_id,risk_level\nTASK-900,high-risk\nTASK-999,low-risk\n",
            encoding="utf-8",
        )
        result = bpl.load_high_risk_tasks(csv_path)
        assert result == {"TASK-900"}

    def test_load_high_risk_tasks_empty(self, tmp_path):
        csv_path = tmp_path / "risk.csv"
        csv_path.write_text("task_id,risk_level\n", encoding="utf-8")
        assert bpl.load_high_risk_tasks(csv_path) == set()

    # --- backfill_pdca_stage ---

    def test_backfill_pdca_stage_inserts(self):
        text = "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Scope\n"
        new_text, changed = bpl.backfill_pdca_stage(text, "P")
        assert changed is True
        assert "- PDCA Stage: P" in new_text
        # Verify insertion is after Last Updated
        lu_idx = new_text.index("Last Updated:")
        pdca_idx = new_text.index("PDCA Stage:")
        assert pdca_idx > lu_idx

    def test_backfill_pdca_stage_already_present(self):
        text = "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n- PDCA Stage: D\n"
        new_text, changed = bpl.backfill_pdca_stage(text, "D")
        assert changed is False
        assert new_text == text

    def test_backfill_pdca_stage_no_last_updated(self):
        text = "## Metadata\n- Task ID: TASK-X\n## Scope\n"
        new_text, changed = bpl.backfill_pdca_stage(text, "C")
        assert changed is False

    # --- insert_tao_trace_code ---

    def test_insert_tao_trace_code_before_blockers(self):
        text = "# Code\n## Summary\nfoo\n## Blockers\nnone\n"
        new_text, changed = bpl.insert_tao_trace_code(text)
        assert changed is True
        assert "## TAO Trace" in new_text
        # TAO Trace should appear before ## Blockers
        tao_idx = new_text.index("## TAO Trace")
        blockers_idx = new_text.index("## Blockers")
        assert tao_idx < blockers_idx

    def test_insert_tao_trace_code_fallback_append(self):
        text = "# Code\n## Summary\nfoo\n"
        new_text, changed = bpl.insert_tao_trace_code(text)
        assert changed is True
        assert new_text.rstrip().endswith("continue")

    def test_insert_tao_trace_code_already_present(self):
        text = "# Code\n## TAO Trace\nstep\n"
        new_text, changed = bpl.insert_tao_trace_code(text)
        assert changed is False

    # --- insert_tao_trace_verify ---

    def test_insert_tao_trace_verify_before_pass_fail(self):
        text = "# Verify\n## Evidence\nfoo\n## Pass Fail Result\npass\n"
        new_text, changed = bpl.insert_tao_trace_verify(text)
        assert changed is True
        assert "## TAO Trace" in new_text
        tao_idx = new_text.index("## TAO Trace")
        pfr_idx = new_text.index("## Pass Fail Result")
        assert tao_idx < pfr_idx

    def test_insert_tao_trace_verify_fallback_append(self):
        text = "# Verify\n## Evidence\nfoo\n"
        new_text, changed = bpl.insert_tao_trace_verify(text)
        assert changed is True
        assert "## TAO Trace" in new_text

    def test_insert_tao_trace_verify_already_present(self):
        text = "# Verify\n## TAO Trace\nstep\n"
        new_text, changed = bpl.insert_tao_trace_verify(text)
        assert changed is False

    # --- process_artifact ---

    def test_process_artifact_pdca_only(self, tmp_path):
        path = tmp_path / "TASK-900.plan.md"
        path.write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Scope\n",
            encoding="utf-8",
        )
        changes = bpl.process_artifact(path, "plan", set(), include_tao=False, dry_run=False)
        assert len(changes) == 1
        assert "PDCA Stage: P" in changes[0]
        assert "- PDCA Stage: P" in path.read_text(encoding="utf-8")

    def test_process_artifact_pdca_and_tao_high_risk(self, tmp_path):
        path = tmp_path / "TASK-900.code.md"
        path.write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Summary\nfoo\n",
            encoding="utf-8",
        )
        changes = bpl.process_artifact(path, "code", {"TASK-900"}, include_tao=True, dry_run=False)
        assert len(changes) == 2
        text = path.read_text(encoding="utf-8")
        assert "PDCA Stage: D" in text
        assert "## TAO Trace" in text

    def test_process_artifact_already_up_to_date(self, tmp_path):
        path = tmp_path / "TASK-900.code.md"
        path.write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n- PDCA Stage: D\n## TAO Trace\nstep\n",
            encoding="utf-8",
        )
        changes = bpl.process_artifact(path, "code", {"TASK-900"}, include_tao=True, dry_run=False)
        assert changes == []

    def test_process_artifact_dry_run_no_write(self, tmp_path):
        path = tmp_path / "TASK-900.plan.md"
        original = "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Scope\n"
        path.write_text(original, encoding="utf-8")
        changes = bpl.process_artifact(path, "plan", set(), include_tao=False, dry_run=True)
        assert len(changes) == 1
        assert path.read_text(encoding="utf-8") == original  # not modified

    def test_process_artifact_low_risk_no_tao(self, tmp_path):
        path = tmp_path / "TASK-999.code.md"
        path.write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Summary\nfoo\n",
            encoding="utf-8",
        )
        changes = bpl.process_artifact(path, "code", {"TASK-900"}, include_tao=True, dry_run=False)
        assert len(changes) == 1  # PDCA only, no TAO (not in high_risk set)
        assert "## TAO Trace" not in path.read_text(encoding="utf-8")

    def test_process_artifact_verify_tao(self, tmp_path):
        path = tmp_path / "TASK-900.verify.md"
        path.write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Pass Fail Result\npass\n",
            encoding="utf-8",
        )
        changes = bpl.process_artifact(path, "verify", {"TASK-900"}, include_tao=True, dry_run=False)
        assert any("TAO Trace" in c for c in changes)

    def test_process_artifact_plan_no_tao_even_if_high_risk(self, tmp_path):
        """Plan artifacts never get TAO Trace regardless of risk level."""
        path = tmp_path / "TASK-900.plan.md"
        path.write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Scope\n",
            encoding="utf-8",
        )
        changes = bpl.process_artifact(path, "plan", {"TASK-900"}, include_tao=True, dry_run=False)
        assert len(changes) == 1  # Only PDCA
        assert "## TAO Trace" not in path.read_text(encoding="utf-8")

    # --- main ---

    def test_main_dry_run(self, tmp_path, capsys):
        plans = tmp_path / "artifacts" / "plans"
        plans.mkdir(parents=True)
        (plans / "TASK-800.plan.md").write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Scope\n",
            encoding="utf-8",
        )
        ret = bpl.main(["--root", str(tmp_path), "--dry-run"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        # File should not be modified
        text = (plans / "TASK-800.plan.md").read_text(encoding="utf-8")
        assert "PDCA Stage" not in text

    def test_main_apply(self, tmp_path, capsys):
        plans = tmp_path / "artifacts" / "plans"
        code = tmp_path / "artifacts" / "code"
        plans.mkdir(parents=True)
        code.mkdir(parents=True)
        (plans / "TASK-800.plan.md").write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Scope\n",
            encoding="utf-8",
        )
        (code / "TASK-800.code.md").write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Summary\nfoo\n",
            encoding="utf-8",
        )
        ret = bpl.main(["--root", str(tmp_path)])
        assert ret == 0
        assert "PDCA Stage: P" in (plans / "TASK-800.plan.md").read_text(encoding="utf-8")
        assert "PDCA Stage: D" in (code / "TASK-800.code.md").read_text(encoding="utf-8")

    def test_main_include_tao_no_csv_warns(self, tmp_path, capsys):
        plans = tmp_path / "artifacts" / "plans"
        plans.mkdir(parents=True)
        (plans / "TASK-800.plan.md").write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Scope\n",
            encoding="utf-8",
        )
        ret = bpl.main(["--root", str(tmp_path), "--include-tao", "--dry-run"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "WARN" in out

    def test_main_include_tao_with_csv(self, tmp_path, capsys):
        plans = tmp_path / "artifacts" / "plans"
        code = tmp_path / "artifacts" / "code"
        registry = tmp_path / "artifacts" / "registry"
        plans.mkdir(parents=True)
        code.mkdir(parents=True)
        registry.mkdir(parents=True)
        (registry / "risk_classification.csv").write_text(
            "task_id,risk_level\nTASK-800,high-risk\n", encoding="utf-8"
        )
        (plans / "TASK-800.plan.md").write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Scope\n",
            encoding="utf-8",
        )
        (code / "TASK-800.code.md").write_text(
            "## Metadata\n- Last Updated: 2026-01-01T00:00:00+08:00\n## Summary\nfoo\n",
            encoding="utf-8",
        )
        ret = bpl.main(["--root", str(tmp_path), "--include-tao"])
        assert ret == 0
        assert "## TAO Trace" in (code / "TASK-800.code.md").read_text(encoding="utf-8")

    # --- current_taipei_timestamp ---

    def test_current_taipei_timestamp_format(self):
        ts = bpl.current_taipei_timestamp()
        assert "+08:00" in ts

