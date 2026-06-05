"""Split unit tests for workflow_constants per TASK-1054."""
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


class TestWorkflowConstants:
    def test_required_topics_is_set(self):
        assert isinstance(wc.REQUIRED_TOPICS, set)
        assert "multi-agent" in wc.REQUIRED_TOPICS
        assert len(wc.REQUIRED_TOPICS) == 6

    def test_topic_pattern(self):
        assert wc.TOPIC_PATTERN.match("multi-agent")
        assert wc.TOPIC_PATTERN.match("developer-tools")
        assert not wc.TOPIC_PATTERN.match("UPPERCASE")
        assert not wc.TOPIC_PATTERN.match("has space")

    def test_resolve_policy_for_docs_spec_removes_test(self):
        policy = wc.resolve_verification_policy("mvp", "docs-spec")
        assert "test" not in policy["required_artifacts_by_state"]["done"]

    def test_resolve_policy_for_web_app_requires_build_guarantee(self):
        policy = wc.resolve_verification_policy("production", "web-app")
        assert policy["requires_build_guarantee"] is True
        assert "Build Guarantee" in policy["verify_required_sections"]

    def test_rule_tables_are_self_consistent(self):
        assert wc.validate_workflow_rule_tables() == []


# ─────────────────────────────────────────────
# validate_context_stack
# ─────────────────────────────────────────────

class TestWorkflowConstantsCoverageCatchup:
    def test_resolve_adapter_chain_unknown_rule(self):
        with pytest.raises(ValueError, match="Unknown project adapter rule"):
            wc._resolve_adapter_chain("missing-rule")

    def test_resolve_adapter_chain_detects_cycle(self, monkeypatch):
        rules = {
            "cycle-a": {**wc.PROJECT_ADAPTER_RULES["generic"], "inherits": "cycle-b"},
            "cycle-b": {**wc.PROJECT_ADAPTER_RULES["generic"], "inherits": "cycle-a"},
        }
        monkeypatch.setattr(wc, "PROJECT_ADAPTER_RULES", rules)
        with pytest.raises(ValueError, match="cycle"):
            wc._resolve_adapter_chain("cycle-a")

    def test_resolve_verification_policy_missing_profile_raises(self, monkeypatch):
        profiles = {k: v for k, v in wc.ASSURANCE_PROFILES.items() if k != "poc"}
        monkeypatch.setattr(wc, "ASSURANCE_PROFILES", profiles)
        with pytest.raises(ValueError, match="Missing assurance profile: poc"):
            wc.resolve_verification_policy("poc", "generic")

    def test_resolve_verification_policy_missing_fields_raises(self, monkeypatch):
        broken = {
            **wc.ASSURANCE_PROFILES,
            "poc": {
                "required_artifacts_by_state": wc.ASSURANCE_PROFILES["poc"]["required_artifacts_by_state"],
            },
        }
        monkeypatch.setattr(wc, "ASSURANCE_PROFILES", broken)
        with pytest.raises(ValueError, match="missing fields"):
            wc.resolve_verification_policy("poc", "generic")

    def test_resolve_verification_policy_discards_artifact_via_override(self, monkeypatch):
        rules = {
            "generic": wc.PROJECT_ADAPTER_RULES["generic"],
            "drop-plan": {
                "inherits": "generic",
                "artifact_overrides_by_state": {"planned": {"plan": False}},
                "verify_section_overrides": set(),
                "verify_field_overrides": set(),
                "allowed_reason_codes": set(),
                "forbidden_reason_codes": set(),
                "requires_build_guarantee": False,
            },
        }
        monkeypatch.setattr(wc, "PROJECT_ADAPTER_RULES", rules)
        monkeypatch.setattr(wc, "PROJECT_ADAPTERS", tuple(rules.keys()))
        policy = wc.resolve_verification_policy("poc", "drop-plan")
        assert "plan" not in policy["required_artifacts_by_state"]["planned"]

    def test_derive_verification_readiness_production_ready(self):
        assert (
            wc.derive_verification_readiness(
                "production", "generic", state="done", open_verification_debts=[]
            )
            == "production-ready"
        )

    def test_validate_workflow_rule_tables_clean(self):
        assert wc.validate_workflow_rule_tables() == []

    def test_validate_workflow_rule_tables_missing_profile(self, monkeypatch):
        profiles = {k: v for k, v in wc.ASSURANCE_PROFILES.items() if k != "mvp"}
        monkeypatch.setattr(wc, "ASSURANCE_PROFILES", profiles)
        errors = wc.validate_workflow_rule_tables()
        assert any("Missing assurance profile" in e for e in errors)

    def test_validate_workflow_rule_tables_missing_fields(self, monkeypatch):
        broken = {
            k: ({**v, "required_artifacts_by_state": v.get("required_artifacts_by_state", {})} if k != "poc" else {"required_artifacts_by_state": v["required_artifacts_by_state"]})
            for k, v in wc.ASSURANCE_PROFILES.items()
        }
        monkeypatch.setattr(wc, "ASSURANCE_PROFILES", broken)
        errors = wc.validate_workflow_rule_tables()
        assert any("missing fields" in e for e in errors)

    def test_validate_workflow_rule_tables_bad_states(self, monkeypatch):
        bad_poc = {**wc.ASSURANCE_PROFILES["poc"]}
        bad_poc["required_artifacts_by_state"] = {"drafted": {"task"}}
        profiles = {**wc.ASSURANCE_PROFILES, "poc": bad_poc}
        monkeypatch.setattr(wc, "ASSURANCE_PROFILES", profiles)
        errors = wc.validate_workflow_rule_tables()
        assert any("must define required_artifacts_by_state" in e for e in errors)

    def test_validate_workflow_rule_tables_unknown_artifact(self, monkeypatch):
        bad_poc = {**wc.ASSURANCE_PROFILES["poc"]}
        states = {s: set(arts) for s, arts in bad_poc["required_artifacts_by_state"].items()}
        states["drafted"] = states["drafted"] | {"bogus_artifact"}
        bad_poc["required_artifacts_by_state"] = states
        profiles = {**wc.ASSURANCE_PROFILES, "poc": bad_poc}
        monkeypatch.setattr(wc, "ASSURANCE_PROFILES", profiles)
        errors = wc.validate_workflow_rule_tables()
        assert any("unknown artifacts" in e for e in errors)

    def test_validate_workflow_rule_tables_unknown_verify_field(self, monkeypatch):
        bad_poc = {**wc.ASSURANCE_PROFILES["poc"]}
        bad_poc["verify_required_fields"] = set(bad_poc["verify_required_fields"]) | {"bogus_field"}
        profiles = {**wc.ASSURANCE_PROFILES, "poc": bad_poc}
        monkeypatch.setattr(wc, "ASSURANCE_PROFILES", profiles)
        errors = wc.validate_workflow_rule_tables()
        assert any("unknown fields" in e for e in errors)

    def test_validate_workflow_rule_tables_unknown_status_debt(self, monkeypatch):
        bad_poc = {**wc.ASSURANCE_PROFILES["poc"]}
        bad_poc["status_debt_results"] = set(bad_poc["status_debt_results"]) | {"bogus"}
        profiles = {**wc.ASSURANCE_PROFILES, "poc": bad_poc}
        monkeypatch.setattr(wc, "ASSURANCE_PROFILES", profiles)
        errors = wc.validate_workflow_rule_tables()
        assert any("unknown results" in e for e in errors)

    def test_validate_workflow_rule_tables_bad_readiness(self, monkeypatch):
        bad_poc = {**wc.ASSURANCE_PROFILES["poc"]}
        bad_poc["default_verification_readiness"] = "nope"
        profiles = {**wc.ASSURANCE_PROFILES, "poc": bad_poc}
        monkeypatch.setattr(wc, "ASSURANCE_PROFILES", profiles)
        errors = wc.validate_workflow_rule_tables()
        assert any("default_verification_readiness must be one of" in e for e in errors)

    def test_validate_workflow_rule_tables_missing_adapter_rule(self, monkeypatch):
        adapters = tuple(list(wc.PROJECT_ADAPTERS) + ["missing-rule"])
        monkeypatch.setattr(wc, "PROJECT_ADAPTERS", adapters)
        errors = wc.validate_workflow_rule_tables()
        assert any("Missing project adapter rule" in e for e in errors)

    def test_validate_workflow_rule_tables_unknown_inherits(self, monkeypatch):
        rules = {**wc.PROJECT_ADAPTER_RULES}
        rules["orphan"] = {
            **wc.PROJECT_ADAPTER_RULES["generic"],
            "inherits": "does-not-exist",
        }
        monkeypatch.setattr(wc, "PROJECT_ADAPTER_RULES", rules)
        monkeypatch.setattr(wc, "PROJECT_ADAPTERS", tuple(rules.keys()))
        errors = wc.validate_workflow_rule_tables()
        assert any("inherits unknown adapter" in e for e in errors)

    def test_validate_workflow_rule_tables_unknown_override_state(self, monkeypatch):
        rules = {**wc.PROJECT_ADAPTER_RULES}
        rules["stateful"] = {
            **wc.PROJECT_ADAPTER_RULES["generic"],
            "artifact_overrides_by_state": {"no-such-state": {"task": True}},
        }
        monkeypatch.setattr(wc, "PROJECT_ADAPTER_RULES", rules)
        monkeypatch.setattr(wc, "PROJECT_ADAPTERS", tuple(rules.keys()))
        errors = wc.validate_workflow_rule_tables()
        assert any("unknown state" in e for e in errors)

    def test_validate_workflow_rule_tables_unknown_override_artifacts(self, monkeypatch):
        rules = {**wc.PROJECT_ADAPTER_RULES}
        rules["art-bad"] = {
            **wc.PROJECT_ADAPTER_RULES["generic"],
            "artifact_overrides_by_state": {"drafted": {"bogus_artifact": True}},
        }
        monkeypatch.setattr(wc, "PROJECT_ADAPTER_RULES", rules)
        monkeypatch.setattr(wc, "PROJECT_ADAPTERS", tuple(rules.keys()))
        errors = wc.validate_workflow_rule_tables()
        assert any("artifact_overrides_by_state uses unknown artifacts" in e for e in errors)

    def test_validate_workflow_rule_tables_unknown_verify_field_override(self, monkeypatch):
        rules = {**wc.PROJECT_ADAPTER_RULES}
        rules["fld-bad"] = {
            **wc.PROJECT_ADAPTER_RULES["generic"],
            "verify_field_overrides": {"bogus_field"},
        }
        monkeypatch.setattr(wc, "PROJECT_ADAPTER_RULES", rules)
        monkeypatch.setattr(wc, "PROJECT_ADAPTERS", tuple(rules.keys()))
        errors = wc.validate_workflow_rule_tables()
        assert any("verify_field_overrides uses unknown fields" in e for e in errors)

    def test_validate_workflow_rule_tables_unknown_reason_codes(self, monkeypatch):
        rules = {**wc.PROJECT_ADAPTER_RULES}
        rules["rc-bad"] = {
            **wc.PROJECT_ADAPTER_RULES["generic"],
            "allowed_reason_codes": {"BOGUS_CODE"},
        }
        monkeypatch.setattr(wc, "PROJECT_ADAPTER_RULES", rules)
        monkeypatch.setattr(wc, "PROJECT_ADAPTERS", tuple(rules.keys()))
        errors = wc.validate_workflow_rule_tables()
        assert any("unknown reason codes" in e for e in errors)

    def test_validate_workflow_rule_tables_resolve_failure(self, monkeypatch):
        rules = {**wc.PROJECT_ADAPTER_RULES}
        rules["loop-a"] = {
            **wc.PROJECT_ADAPTER_RULES["generic"],
            "inherits": "loop-b",
        }
        rules["loop-b"] = {
            **wc.PROJECT_ADAPTER_RULES["generic"],
            "inherits": "loop-a",
        }
        monkeypatch.setattr(wc, "PROJECT_ADAPTER_RULES", rules)
        monkeypatch.setattr(
            wc, "PROJECT_ADAPTERS", tuple(list(wc.PROJECT_ADAPTERS) + ["loop-a", "loop-b"])
        )
        errors = wc.validate_workflow_rule_tables()
        assert any("cycle" in e.lower() for e in errors)

    def test_validate_workflow_rule_tables_resolved_policy_missing_key(self, monkeypatch):
        original = wc.resolve_verification_policy

        def strip_key(*args, **kwargs):
            policy = original(*args, **kwargs)
            policy.pop("status_debt_results", None)
            return policy

        monkeypatch.setattr(wc, "resolve_verification_policy", strip_key)
        errors = wc.validate_workflow_rule_tables()
        assert any("missing contract key" in e for e in errors)

    def test_validate_workflow_rule_tables_resolved_policy_bad_reason_codes(self, monkeypatch):
        original = wc.resolve_verification_policy

        def pollute(*args, **kwargs):
            policy = original(*args, **kwargs)
            policy["allowed_reason_codes"] = set(policy["allowed_reason_codes"]) | {"ALIEN_CODE"}
            return policy

        monkeypatch.setattr(wc, "resolve_verification_policy", pollute)
        errors = wc.validate_workflow_rule_tables()
        assert any("exposes unknown reason codes" in e for e in errors)

    def test_validate_workflow_rule_tables_resolved_policy_bad_results(self, monkeypatch):
        original = wc.resolve_verification_policy

        def pollute(*args, **kwargs):
            policy = original(*args, **kwargs)
            policy["allowed_results"] = set(policy["allowed_results"]) | {"alien_result"}
            return policy

        monkeypatch.setattr(wc, "resolve_verification_policy", pollute)
        errors = wc.validate_workflow_rule_tables()
        assert any("exposes unknown verification results" in e for e in errors)

    def test_validate_workflow_rule_tables_resolved_policy_bad_readiness(self, monkeypatch):
        original = wc.resolve_verification_policy

        def pollute(*args, **kwargs):
            policy = original(*args, **kwargs)
            policy["default_verification_readiness"] = "invalid-readiness"
            return policy

        monkeypatch.setattr(wc, "resolve_verification_policy", pollute)
        errors = wc.validate_workflow_rule_tables()
        assert any("invalid readiness" in e for e in errors)

    def test_validate_workflow_rule_tables_resolved_policy_bad_states(self, monkeypatch):
        original = wc.resolve_verification_policy

        def pollute(*args, **kwargs):
            policy = original(*args, **kwargs)
            policy["required_artifacts_by_state"] = {"drafted": set()}
            return policy

        monkeypatch.setattr(wc, "resolve_verification_policy", pollute)
        errors = wc.validate_workflow_rule_tables()
        assert any("must cover all workflow states" in e for e in errors)

