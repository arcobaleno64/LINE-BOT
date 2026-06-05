#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import List

import migrate_artifact_schema as mas

from red_team.helpers import *

def case_rt_001() -> CaseResult:
    temp_root = prepare_temp_root("RT-001")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-960")
        research_path = artifacts_root / "research" / "TASK-960.research.md"
        text = research_path.read_text(encoding="utf-8")
        text += "\n\n## Recommendation\n不要接受這份越界 research。\n"
        research_path.write_text(text, encoding="utf-8")
        return run_status_case(
            "TASK-960",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="must not contain ## Recommendation",
            title="Research artifact contains Recommendation",
            case_id="RT-001",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_002() -> CaseResult:
    temp_root = prepare_temp_root("RT-002")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-961")
        research_path = artifacts_root / "research" / "TASK-961.research.md"
        text = research_path.read_text(encoding="utf-8")
        text = text.replace("- `guard_status_validator.py` 專責 task / artifact / state 驗證，會檢查 metadata、research fact-only 契約、premortem 與 Gate E", "- status validator 專責 task / artifact / state 驗證，會檢查 metadata、research fact-only 契約、premortem 與 Gate E", 1)
        cf_match = re.search(r"(## Confirmed Facts\n)(.*?)(\n##\s)", text, re.DOTALL)
        if cf_match:
            stripped = re.sub(
                r"[（(][^)）\n]*[)）]\.?|`[^`\n]+`|https?://\S+|\b[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]{1,10}(?::\d+)?\b",
                "",
                cf_match.group(2),
            )
            text = text[:cf_match.start(2)] + stripped + text[cf_match.end(2):]
        research_path.write_text(text, encoding="utf-8")
        return run_status_case(
            "TASK-961",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="must include an inline citation",
            title="Confirmed Facts missing citation",
            case_id="RT-002",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_003() -> CaseResult:
    temp_root = prepare_temp_root("RT-003")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-962")
        research_path = artifacts_root / "research" / "TASK-962.research.md"
        text = research_path.read_text(encoding="utf-8").replace("## Uncertain Items\nNone", "## Uncertain Items\n- Needs manual follow-up")
        research_path.write_text(text, encoding="utf-8")
        return run_status_case(
            "TASK-962",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="must start with UNVERIFIED:",
            title="Uncertain Items missing UNVERIFIED marker",
            case_id="RT-003",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_004() -> CaseResult:
    temp_root = prepare_temp_root("RT-004")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-963")
        task_path = artifacts_root / "tasks" / "TASK-963.task.md"
        task_text = task_path.read_text(encoding="utf-8").replace("驗證內建 sample artifacts 與兩支 guard（`guard_status_validator.py`、`guard_contract_validator.py`）在 root repo 中都能正常通過。", "驗證一個 security-sensitive workflow task 在高風險前提下，premortem 是否真的要求 blocking risk。")
        task_path.write_text(task_text, encoding="utf-8")
        plan_path = artifacts_root / "plans" / "TASK-963.plan.md"
        plan_text = plan_path.read_text(encoding="utf-8")
        plan_text = plan_text.replace("Severity: blocking", "Severity: non-blocking", 1)
        extra_risks = """- R3\n  - Risk: security-sensitive task 的 drift 說明沒有被 README 與 Obsidian 同步\n  - Trigger: 演練只更新單一入口文件\n  - Detection: contract guard 或人工交叉閱讀發現不一致\n  - Mitigation: 在同步步驟中強制包含 README 與 Obsidian\n  - Severity: non-blocking\n- R4\n  - Risk: high-risk task 的驗證只靠口頭判定\n  - Trigger: verify evidence 沒有列出實際 guard 命令\n  - Detection: verify artifact 缺少 evidence 指向 guard\n  - Mitigation: 在 verify 中固定列出 guard 命令與結果\n  - Severity: non-blocking\n\n"""
        plan_text = plan_text.replace("## Validation Strategy\n", extra_risks + "## Validation Strategy\n")
        plan_path.write_text(plan_text, encoding="utf-8")
        status_path = artifacts_root / "status" / "TASK-963.status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["state"] = "coding"
        status["required_artifacts"] = ["code", "plan", "research", "status", "task"]
        status["available_artifacts"] = ["code", "plan", "research", "status", "task", "verify"]
        status["missing_artifacts"] = []
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_status_case(
            "TASK-963",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="requires at least 1 blocking risks",
            title="High-risk premortem without blocking risk",
            case_id="RT-004",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_005() -> CaseResult:
    temp_root = prepare_temp_root("RT-005")
    try:
        artifacts_root = copy_task_fixture(temp_root, blocked_sample_source(), "TASK-964", include_improvement=False)
        return run_status_case(
            "TASK-964",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="requires an improvement artifact",
            from_state="blocked",
            to_state="planned",
            title="Blocked resume without improvement artifact",
            case_id="RT-005",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_006() -> CaseResult:
    temp_root = prepare_temp_root("RT-006")
    try:
        artifacts_root = copy_task_fixture(temp_root, blocked_sample_source(), "TASK-965")
        improvement_path = artifacts_root / "improvement" / "TASK-965.improvement.md"
        text = improvement_path.read_text(encoding="utf-8").replace("- Status: applied", "- Status: approved", 1).replace("## 9. Status\napplied", "## 9. Status\napproved")
        improvement_path.write_text(text, encoding="utf-8")
        return run_status_case(
            "TASK-965",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="requires an improvement artifact with Status: applied",
            from_state="blocked",
            to_state="planned",
            title="Blocked resume with non-applied improvement",
            case_id="RT-006",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_007() -> CaseResult:
    def mutation(temp_root: Path) -> None:
        path = temp_root / "template" / "docs" / "workflow_state_machine.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n<!-- red-team drift marker -->\n", encoding="utf-8")
    return run_contract_case(
        expected_exit_code=1,
        expected_output_fragment="Contract drift detected",
        mutation=mutation,
        title="Contract drift between root and template",
        case_id="RT-007",
        notes="template workflow state machine drift",
    )


def case_rt_008() -> CaseResult:
    def mutation(temp_root: Path) -> None:
        path = temp_root / "OBSIDIAN.md"
        text = path.read_text(encoding="utf-8").replace("template/OBSIDIAN.md", "template/OBSIDIAN-REMOVED.md", 1)
        path.write_text(text, encoding="utf-8")
    return run_contract_case(
        expected_exit_code=1,
        expected_output_fragment="missing required phrase: template/OBSIDIAN.md",
        mutation=mutation,
        title="Obsidian drift",
        case_id="RT-008",
        notes="Obsidian GitHub/Template section lost required template mapping",
    )


def case_rt_009() -> CaseResult:
    def mutation(temp_root: Path) -> None:
        path = temp_root / "BOOTSTRAP_PROMPT.md"
        # Remove all lines containing guard_contract_validator.py so the required phrase is absent
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        text = "".join(line for line in lines if "guard_contract_validator.py" not in line)
        path.write_text(text, encoding="utf-8")
    return run_contract_case(
        expected_exit_code=1,
        expected_output_fragment="BOOTSTRAP_PROMPT.md missing required phrase: guard_contract_validator.py",
        mutation=mutation,
        title="Bootstrap missing contract guard",
        case_id="RT-009",
        notes="bootstrap lost contract-guard step",
    )


def case_rt_010() -> CaseResult:
    temp_root = prepare_temp_root("RT-010")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-974")
        research_path = artifacts_root / "research" / "TASK-974.research.md"
        research_text = re.sub(r"\n## Sources\s*\n.*?(?=\n## |\Z)", "", research_path.read_text(encoding="utf-8"), flags=re.DOTALL)
        research_path.write_text(research_text.strip() + "\n", encoding="utf-8")
        return run_status_case(
            "TASK-974",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="missing required ## Sources section",
            title="Research artifact missing Sources section",
            case_id="RT-010",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_011() -> CaseResult:
    temp_root = prepare_temp_root("RT-011")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-975")
        initialize_git_fixture(temp_root)
        code_path = artifacts_root / "code" / "TASK-975.code.md"
        code_text = code_path.read_text(encoding="utf-8")
        code_text = re.sub(
            r"## Mapping To Plan\s*\n.*?(?=\n## |\Z)",
            "## Mapping To Plan\n"
            '- plan_item: 1.1, status: done, evidence: "smoke sample aligned with schema"\n'
            '- plan_item: 1.2, evidence: "missing status should trigger warn"\n',
            code_text,
            flags=re.DOTALL,
        )
        code_path.write_text(code_text, encoding="utf-8")
        return run_status_case(
            "TASK-975",
            artifacts_root,
            expected_exit_code=0,
            expected_output_fragment="Mapping To Plan entry must match",
            title="Code artifact Mapping To Plan malformed entry",
            case_id="RT-011",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_012() -> CaseResult:
    temp_root = prepare_temp_root("RT-012")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-976")
        initialize_git_fixture(temp_root)
        task_path = artifacts_root / "tasks" / "TASK-976.task.md"
        task_text = task_path.read_text(encoding="utf-8")
        task_text = re.sub(
            r"## Project Adapter\s*\n.*?(?=\n## |\Z)",
            "## Project Adapter\nresource-constrained-ui\n",
            task_text,
            flags=re.DOTALL,
        )
        task_path.write_text(task_text, encoding="utf-8")
        status_path = artifacts_root / "status" / "TASK-976.status.json"
        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        status_data["project_adapter"] = "resource-constrained-ui"
        status_path.write_text(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        verify_path = artifacts_root / "verify" / "TASK-976.verify.md"
        verify_text = verify_path.read_text(encoding="utf-8")
        verify_text = re.sub(
            r"## Acceptance Criteria Checklist\s*\n.*?(?=\n## Evidence|\Z)",
            "## Acceptance Criteria Checklist\n\n"
            "### AC-1\n"
            "- Criterion: `python artifacts/scripts/guard_status_validator.py --task-id TASK-976` 回報 `[OK] Validation passed`\n"
            "- Method: `python artifacts/scripts/guard_status_validator.py --task-id TASK-976`\n"
            "- Evidence: smoke sample task remains valid\n"
            "- Result: verified\n"
            "- Reviewer: Claude\n"
            "- Timestamp: 2026-04-15T12:00:00+08:00\n\n"
            "### AC-2\n"
            "- Criterion: verify checklist item 應保留 reviewer 欄位\n"
            "- Method: manual schema spot check\n"
            "- Evidence: structured checklist should include reviewer + timestamp\n"
            "- Result: verified\n"
            "- Timestamp: 2026-04-15T12:01:00+08:00\n",
            verify_text,
            flags=re.DOTALL,
        )
        verify_path.write_text(verify_text, encoding="utf-8")
        return run_status_case(
            "TASK-976",
            artifacts_root,
            expected_exit_code=0,
            expected_output_fragment="missing reviewer field",
            title="Verify artifact checklist reviewer field missing",
            case_id="RT-012",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_013() -> CaseResult:
    temp_root = prepare_temp_root("RT-013")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-966")
        # Set state to verifying so git-backed scope check is active (done state skips live check)
        status_path = artifacts_root / "status" / "TASK-966.status.json"
        status_data = json.loads(status_path.read_text(encoding="utf-8"))
        status_data["state"] = "verifying"
        status_path.write_text(json.dumps(status_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        initialize_git_fixture(temp_root)
        code_path = artifacts_root / "code" / "TASK-966.code.md"
        code_text = code_path.read_text(encoding="utf-8")
        code_path.write_text(code_text + "\n<!-- git-backed scope drift drill -->\n", encoding="utf-8")
        rogue_path = temp_root / "docs" / "rogue-change.md"
        ensure_parent(rogue_path)
        rogue_path.write_text("# Rogue Change\nThis file simulates an undeclared workspace change.\n", encoding="utf-8")
        return run_status_case(
            "TASK-966",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="git-backed scope check found actual changed files not listed",
            title="Git-backed scope drift auto-guard",
            case_id="RT-013",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_014() -> CaseResult:
    temp_root = prepare_temp_root("RT-014")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-967")
        initialize_git_fixture(temp_root)
        base_commit = git_rev_parse(temp_root, "HEAD")
        rogue_path = temp_root / "docs" / "rogue-history.md"
        ensure_parent(rogue_path)
        rogue_path.write_text("# Rogue History\nThis file simulates an undeclared committed change.\n", encoding="utf-8")
        ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add historical replay drift source")
        ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "historical replay drift source"]), "git commit historical replay drift source")
        head_commit = git_rev_parse(temp_root, "HEAD")
        code_path = artifacts_root / "code" / "TASK-967.code.md"
        code_text = code_path.read_text(encoding="utf-8")
        snapshot_files = ["docs/rogue-history.md"]
        snapshot_hash = compute_snapshot_sha256(snapshot_files)
        code_text += (
            "\n\n## Diff Evidence\n"
            "- Evidence Type: commit-range\n"
            "- Base Ref: HEAD~1\n"
            "- Head Ref: HEAD\n"
            f"- Base Commit: {base_commit}\n"
            f"- Head Commit: {head_commit}\n"
            "- Diff Command: git diff --name-only HEAD~1..HEAD\n"
            f"- Changed Files Snapshot: {', '.join(snapshot_files)}\n"
            f"- Snapshot SHA256: {snapshot_hash}\n"
        )
        code_path.write_text(code_text, encoding="utf-8")
        ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add historical replay evidence")
        ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "historical replay evidence"]), "git commit historical replay evidence")
        return run_status_case(
            "TASK-967",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="commit-range scope check found diff files not listed",
            title="Historical commit-range diff reconstruction",
            case_id="RT-014",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_015() -> CaseResult:
    temp_root = prepare_temp_root("RT-015")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-968")
        initialize_git_fixture(temp_root)
        code_path = artifacts_root / "code" / "TASK-968.code.md"
        text = code_path.read_text(encoding="utf-8")
        text = text.replace("## Summary Of Changes", "- `docs/rogue-waiver.md`\n\n## Summary Of Changes", 1)
        code_path.write_text(text, encoding="utf-8")
        return run_status_case(
            "TASK-968",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="--allow-scope-drift requires a decision artifact with ## Guard Exception",
            title="allow-scope-drift without decision waiver",
            case_id="RT-015",
            extra_args=["--allow-scope-drift"],
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_016() -> CaseResult:
    temp_root = prepare_temp_root("RT-016")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-969")
        initialize_git_fixture(temp_root)
        code_path = artifacts_root / "code" / "TASK-969.code.md"
        text = code_path.read_text(encoding="utf-8")
        text = text.replace("## Summary Of Changes", "- `docs/rogue-waiver.md`\n\n## Summary Of Changes", 1)
        code_path.write_text(text, encoding="utf-8")
        decision_path = artifacts_root / "decisions" / "TASK-969.decision.md"
        decision_path.write_text(
            "# Decision Log: TASK-969\n\n"
            "## Metadata\n"
            "- Task ID: TASK-969\n"
            "- Artifact Type: decision\n"
            "- Owner: Claude\n"
            "- Status: done\n"
            "- Last Updated: 2026-04-13T13:55:35+08:00\n\n"
            "## Issue\n"
            "這個 red-team case 需要模擬一個受控的 scope drift waiver。\n\n"
            "## Options Considered\n"
            "- 保持 strict scope，讓案例直接 fail\n"
            "- 使用 `--allow-scope-drift`，但不提供 decision waiver\n"
            "- 使用 `--allow-scope-drift`，並附帶顯式 decision waiver\n\n"
            "## Chosen Option\n"
            "使用 `--allow-scope-drift`，並附帶顯式 decision waiver。\n\n"
            "## Reasoning\n"
            "這個案例的目的就是驗證 validator 只接受結構化 waiver，而不是任何口頭例外。\n\n"
            "## Implications\n"
            "- `docs/rogue-waiver.md` 應被視為明確列出的受控 drift\n"
            "- 沒有 `## Guard Exception` 時，案例必須失敗\n\n"
            "## Follow Up\n"
            "保留此案例作為 decision-gated waiver static drill。\n\n"
            "## Guard Exception\n"
            "- Exception Type: allow-scope-drift\n"
            "- Scope Files: docs/rogue-waiver.md\n"
            "- Justification: red-team static drill requires one explicit waived file to verify the guard boundary.\n",
            encoding="utf-8",
        )
        return run_status_case(
            "TASK-969",
            artifacts_root,
            expected_exit_code=0,
            expected_output_fragment="[OK] Validation passed",
            title="allow-scope-drift with explicit decision waiver",
            case_id="RT-016",
            extra_args=["--allow-scope-drift"],
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_017() -> CaseResult:
    temp_root = prepare_temp_root("RT-017")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-970")
        initialize_git_fixture(temp_root)
        base_commit = git_rev_parse(temp_root, "HEAD")
        pinned_path = temp_root / "docs" / "pinned-history.md"
        ensure_parent(pinned_path)
        pinned_path.write_text("# Pinned History\nThis file simulates a replayable historical change.\n", encoding="utf-8")
        ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add historical checksum source")
        ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "historical checksum source"]), "git commit historical checksum source")
        head_commit = git_rev_parse(temp_root, "HEAD")
        code_path = artifacts_root / "code" / "TASK-970.code.md"
        code_text = code_path.read_text(encoding="utf-8")
        snapshot_files = ["docs/pinned-history.md"]
        code_text += (
            "\n\n## Diff Evidence\n"
            "- Evidence Type: commit-range\n"
            "- Base Ref: HEAD~1\n"
            "- Head Ref: HEAD\n"
            f"- Base Commit: {base_commit}\n"
            f"- Head Commit: {head_commit}\n"
            "- Diff Command: git diff --name-only HEAD~1..HEAD\n"
            f"- Changed Files Snapshot: {', '.join(snapshot_files)}\n"
            f"- Snapshot SHA256: {compute_snapshot_sha256(['docs/pinned-history.md', 'docs/rogue-history.md'])}\n"
        )
        code_path.write_text(code_text, encoding="utf-8")
        ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add historical checksum evidence")
        ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "historical checksum evidence"]), "git commit historical checksum evidence")
        return run_status_case(
            "TASK-970",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="Snapshot SHA256 does not match Changed Files Snapshot",
            title="Historical diff evidence checksum corruption",
            case_id="RT-017",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_018() -> CaseResult:
    temp_root = prepare_temp_root("RT-018")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-971")
        initialize_git_fixture(temp_root)
        repository = "octo/workflow"
        pull_number = "971"
        safe_files = [f"docs/provider-safe-{index:03d}.md" for index in range(1, 101)]
        rogue_file = "docs/provider-rogue-page-2.md"
        pages = {
            1: [{"filename": path} for path in safe_files],
            2: [{"filename": rogue_file}],
            3: [],
        }
        with github_pr_files_server(repository, pull_number, pages) as api_base_url:
            plan_path = artifacts_root / "plans" / "TASK-971.plan.md"
            code_path = artifacts_root / "code" / "TASK-971.code.md"
            declared_files_block = "".join(f"- `{path}`\n" for path in safe_files)
            plan_text = plan_path.read_text(encoding="utf-8")
            plan_text = plan_text.replace("## Files Likely Affected\n", f"## Files Likely Affected\n{declared_files_block}", 1)
            plan_path.write_text(plan_text, encoding="utf-8")
            code_text = code_path.read_text(encoding="utf-8")
            code_text = code_text.replace("## Files Changed\n", f"## Files Changed\n{declared_files_block}", 1)
            code_text = re.sub(r"\n## Diff Evidence\s*\n.*?(?=\n## |\Z)", "", code_text, flags=re.DOTALL)
            snapshot_files = [*safe_files, rogue_file]
            code_text += (
                "\n\n## Diff Evidence\n"
                "- Evidence Type: github-pr\n"
                f"- Repository: {repository}\n"
                f"- PR Number: {pull_number}\n"
                f"- API Base URL: {api_base_url}\n"
                f"- Changed Files Snapshot: {', '.join(snapshot_files)}\n"
                f"- Snapshot SHA256: {compute_snapshot_sha256(snapshot_files)}\n"
            )
            code_path.write_text(code_text, encoding="utf-8")
            ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add github-pr evidence")
            ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "github-pr evidence"]), "git commit github-pr evidence")
            with temporary_env({GITHUB_API_ALLOWED_HOSTS_ENV: "127.0.0.1"}):
                return run_status_case(
                    "TASK-971",
                    artifacts_root,
                    expected_exit_code=1,
                    expected_output_fragment="github-pr scope check found diff files not listed",
                    title="GitHub provider-backed PR second-page scope drift",
                    case_id="RT-018",
                )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_019() -> CaseResult:
    temp_root = prepare_temp_root("RT-019")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-972")
        initialize_git_fixture(temp_root)
        archive_rel = "artifacts/evidence/TASK-972.changed-files.txt"
        archive_path = temp_root / archive_rel
        ensure_parent(archive_path)
        archive_bytes = b"docs/archive-fallback.md\n"
        archive_path.write_bytes(archive_bytes)
        archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        code_path = artifacts_root / "code" / "TASK-972.code.md"
        code_text = code_path.read_text(encoding="utf-8")
        snapshot_files = ["docs/archive-fallback.md"]
        code_text += (
            "\n\n## Diff Evidence\n"
            "- Evidence Type: commit-range\n"
            f"- Base Commit: {'1' * 40}\n"
            f"- Head Commit: {'2' * 40}\n"
            "- Diff Command: git diff --name-only <base>..<head>\n"
            f"- Changed Files Snapshot: {', '.join(snapshot_files)}\n"
            f"- Snapshot SHA256: {compute_snapshot_sha256(snapshot_files)}\n"
            f"- Archive Path: {archive_rel}\n"
            f"- Archive SHA256: {archive_sha256}\n"
        )
        code_path.write_text(code_text, encoding="utf-8")
        ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add archive fallback evidence")
        ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "archive fallback evidence"]), "git commit archive fallback evidence")
        return run_status_case(
            "TASK-972",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="commit-range archive fallback found diff files not listed",
            title="Historical diff archive fallback reconstruction",
            case_id="RT-019",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_020() -> CaseResult:
    temp_root = prepare_temp_root("RT-020")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-973")
        initialize_git_fixture(temp_root)
        archive_rel = "artifacts/evidence/TASK-973.changed-files.txt"
        archive_path = temp_root / archive_rel
        ensure_parent(archive_path)
        archive_bytes = b"docs/archive-corrupt.md\n"
        archive_path.write_bytes(archive_bytes)
        code_path = artifacts_root / "code" / "TASK-973.code.md"
        code_text = code_path.read_text(encoding="utf-8")
        snapshot_files = ["docs/archive-corrupt.md"]
        code_text += (
            "\n\n## Diff Evidence\n"
            "- Evidence Type: commit-range\n"
            f"- Base Commit: {'1' * 40}\n"
            f"- Head Commit: {'2' * 40}\n"
            "- Diff Command: git diff --name-only <base>..<head>\n"
            f"- Changed Files Snapshot: {', '.join(snapshot_files)}\n"
            f"- Snapshot SHA256: {compute_snapshot_sha256(snapshot_files)}\n"
            f"- Archive Path: {archive_rel}\n"
            f"- Archive SHA256: {'0' * 64}\n"
        )
        code_path.write_text(code_text, encoding="utf-8")
        ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add archive corruption evidence")
        ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "archive corruption evidence"]), "git commit archive corruption evidence")
        return run_status_case(
            "TASK-973",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="Archive SHA256 does not match archive file",
            title="Historical diff archive corruption",
            case_id="RT-020",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_021() -> CaseResult:
    temp_root = prepare_temp_root("RT-021")
    task_id = "TASK-LITE-001"
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", task_id)
        for artifact_type, extension in (("plans", ".plan.md"), ("verify", ".verify.md")):
            path = artifacts_root / artifact_type / f"{task_id}{extension}"
            if path.exists():
                path.unlink()
        status_path = artifacts_root / "status" / f"{task_id}.status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["state"] = "researched"
        status["required_artifacts"] = ["research", "status", "task"]
        status["available_artifacts"] = ["code", "research", "status", "task"]
        status["missing_artifacts"] = []
        status["last_updated"] = "2026-04-15T12:00:00+08:00"
        write_text = json.dumps(status, ensure_ascii=False, indent=2) + "\n"
        status_path.write_text(write_text, encoding="utf-8")
        return run_status_case(
            task_id,
            artifacts_root,
            expected_exit_code=0,
            expected_output_fragment="lightweight candidate",
            title="Auto-classify lightweight candidate without plan artifact",
            case_id="RT-021",
            extra_args=["--auto-classify"],
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_022() -> CaseResult:
    temp_root = prepare_temp_root("RT-022")
    task_id = "TASK-LITE-002"
    command = [sys.executable, str(STATUS_GUARD), "--task-id", task_id, "--artifacts-root", str(temp_root / "artifacts"), "--auto-classify"]
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", task_id)
        task_path = artifacts_root / "tasks" / f"{task_id}.task.md"
        task_text = task_path.read_text(encoding="utf-8")
        task_text = task_text.replace("## Constraints\n", "## Constraints\n- lightweight: true\n- premortem: required\n", 1)
        task_path.write_text(task_text, encoding="utf-8")
        result = run_command(command)
        status_path = artifacts_root / "status" / f"{task_id}.status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        auto_upgrade_log = status.get("auto_upgrade_log", [])
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        passed = (
            result.returncode == 0
            and "[AUTO-UPGRADE]" in output
            and isinstance(auto_upgrade_log, list)
            and bool(auto_upgrade_log)
        )
        notes = "auto_upgrade_log written to status.json" if passed else "missing auto_upgrade_log after auto-upgrade"
        synthetic = completed_process_from_output(command, result.returncode if passed else 1, output)
        return build_case_result(
            case_id="RT-022",
            phase="static",
            title="Auto-classify escalates lightweight task with premortem",
            expected="pass",
            expected_exit_code=0,
            expected_output_fragment="[AUTO-UPGRADE]",
            result=synthetic,
            notes=notes,
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_023() -> CaseResult:
    temp_root = prepare_temp_root("RT-023")
    task_id = "TASK-LITE-003"
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", task_id)
        status_path = artifacts_root / "status" / f"{task_id}.status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        status["decision_waivers"] = [
            {
                "gate": "Gate_B",
                "reason": "expired waiver drill",
                "approver": "Claude",
                "expires": "2026-04-14T23:59:59+08:00",
            }
        ]
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return run_status_case(
            task_id,
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="waiver expired",
            title="Expired decision waiver is rejected",
            case_id="RT-023",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_024() -> CaseResult:
    temp_root = prepare_temp_root("RT-024")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-974")
        initialize_git_fixture(temp_root)
        repository = "octo/workflow"
        pull_number = "974"
        files = ["docs/allowlist-check.md"]
        pages = {1: [{"filename": path} for path in files], 2: []}
        with github_pr_files_server(repository, pull_number, pages) as api_base_url:
            plan_path = artifacts_root / "plans" / "TASK-974.plan.md"
            code_path = artifacts_root / "code" / "TASK-974.code.md"
            declared_files_block = "".join(f"- `{path}`\n" for path in files)
            plan_text = plan_path.read_text(encoding="utf-8")
            plan_text = plan_text.replace("## Files Likely Affected\n", f"## Files Likely Affected\n{declared_files_block}", 1)
            plan_path.write_text(plan_text, encoding="utf-8")
            code_text = code_path.read_text(encoding="utf-8")
            code_text = code_text.replace("## Files Changed\n", f"## Files Changed\n{declared_files_block}", 1)
            code_text = re.sub(r"\n## Diff Evidence\s*\n.*?(?=\n## |\Z)", "", code_text, flags=re.DOTALL)
            code_text += (
                "\n\n## Diff Evidence\n"
                "- Evidence Type: github-pr\n"
                f"- Repository: {repository}\n"
                f"- PR Number: {pull_number}\n"
                f"- API Base URL: {api_base_url}\n"
                f"- Changed Files Snapshot: {', '.join(files)}\n"
                f"- Snapshot SHA256: {compute_snapshot_sha256(files)}\n"
            )
            code_path.write_text(code_text, encoding="utf-8")
            ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add github-pr allowlist rejection")
            ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "github-pr allowlist rejection"]), "git commit github-pr allowlist rejection")
            return run_status_case(
                "TASK-974",
                artifacts_root,
                expected_exit_code=1,
                expected_output_fragment="API Base URL host '127.0.0.1' is not allowed",
                title="GitHub provider-backed PR rejects non-allowlisted API host",
                case_id="RT-024",
            )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_025() -> CaseResult:
    temp_root = prepare_temp_root("RT-025")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-975")
        initialize_git_fixture(temp_root)
        repository = "octo/workflow"
        pull_number = "975"
        files = ["docs/provider-allowlisted.md", "docs/provider-enterprise.md"]
        pages = {1: [{"filename": path} for path in files], 2: []}
        with github_pr_files_server(repository, pull_number, pages) as api_base_url:
            plan_path = artifacts_root / "plans" / "TASK-975.plan.md"
            code_path = artifacts_root / "code" / "TASK-975.code.md"
            declared_files_block = "".join(f"- `{path}`\n" for path in files)
            plan_text = plan_path.read_text(encoding="utf-8")
            plan_text = plan_text.replace("## Files Likely Affected\n", f"## Files Likely Affected\n{declared_files_block}", 1)
            plan_path.write_text(plan_text, encoding="utf-8")
            code_text = code_path.read_text(encoding="utf-8")
            code_text = code_text.replace("## Files Changed\n", f"## Files Changed\n{declared_files_block}", 1)
            code_text = re.sub(r"\n## Diff Evidence\s*\n.*?(?=\n## |\Z)", "", code_text, flags=re.DOTALL)
            code_text += (
                "\n\n## Diff Evidence\n"
                "- Evidence Type: github-pr\n"
                f"- Repository: {repository}\n"
                f"- PR Number: {pull_number}\n"
                f"- API Base URL: {api_base_url}\n"
                f"- Changed Files Snapshot: {', '.join(files)}\n"
                f"- Snapshot SHA256: {compute_snapshot_sha256(files)}\n"
            )
            code_path.write_text(code_text, encoding="utf-8")
            ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add github-pr allowlist success")
            ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "github-pr allowlist success"]), "git commit github-pr allowlist success")
            with temporary_env({GITHUB_API_ALLOWED_HOSTS_ENV: "127.0.0.1"}):
                return run_status_case(
                    "TASK-975",
                    artifacts_root,
                    expected_exit_code=0,
                    expected_output_fragment="[OK] Validation passed",
                    title="GitHub provider-backed PR accepts explicit allowlisted API host",
                    case_id="RT-025",
                )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_026() -> CaseResult:
    temp_root = prepare_temp_root("RT-026")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-976")
        plan_path = artifacts_root / "plans" / "TASK-976.plan.md"
        oversized_suffix = "x" * (MAX_ARTIFACT_FILE_BYTES + 1)
        plan_path.write_text(plan_path.read_text(encoding="utf-8") + "\n" + oversized_suffix, encoding="utf-8")
        return run_status_case(
            "TASK-976",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="Text file too large",
            title="Oversized workflow artifact is rejected before parsing",
            case_id="RT-026",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_027() -> CaseResult:
    temp_root = prepare_temp_root("RT-027")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-977")
        initialize_git_fixture(temp_root)
        archive_rel = "artifacts/evidence/TASK-977.changed-files.txt"
        archive_path = temp_root / archive_rel
        ensure_parent(archive_path)
        snapshot_files = [f"docs/archive-cap-{index:04d}-{'x' * 64}.md" for index in range(1, 1801)]
        archive_bytes = ("\n".join(snapshot_files) + "\n").encode("utf-8")
        archive_path.write_bytes(archive_bytes)
        archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        code_path = artifacts_root / "code" / "TASK-977.code.md"
        code_text = code_path.read_text(encoding="utf-8")
        code_text += (
            "\n\n## Diff Evidence\n"
            "- Evidence Type: commit-range\n"
            f"- Base Commit: {'1' * 40}\n"
            f"- Head Commit: {'2' * 40}\n"
            "- Diff Command: git diff --name-only <base>..<head>\n"
            f"- Changed Files Snapshot: {', '.join(snapshot_files)}\n"
            f"- Snapshot SHA256: {compute_snapshot_sha256(snapshot_files)}\n"
            f"- Archive Path: {archive_rel}\n"
            f"- Archive SHA256: {archive_sha256}\n"
        )
        code_path.write_text(code_text, encoding="utf-8")
        ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add archive replay byte cap evidence")
        ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "archive replay byte cap evidence"]), "git commit archive replay byte cap evidence")
        return run_status_case(
            "TASK-977",
            artifacts_root,
            expected_exit_code=1,
            expected_output_fragment="exceeds replay byte cap",
            title="Oversized archive fallback is rejected before parsing",
            case_id="RT-027",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_028() -> CaseResult:
    temp_root = prepare_temp_root("RT-028")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-978")
        initialize_git_fixture(temp_root)
        repository = "octo/workflow"
        pull_number = "978"
        files = [f"docs/provider-cap-{index:03d}-{'x' * 1300}.md" for index in range(1, 101)]
        pages = {1: [{"filename": path} for path in files], 2: []}
        with github_pr_files_server(repository, pull_number, pages) as api_base_url:
            code_path = artifacts_root / "code" / "TASK-978.code.md"
            code_text = code_path.read_text(encoding="utf-8")
            code_text = re.sub(r"\n## Diff Evidence\s*\n.*?(?=\n## |\Z)", "", code_text, flags=re.DOTALL)
            code_text += (
                "\n\n## Diff Evidence\n"
                "- Evidence Type: github-pr\n"
                f"- Repository: {repository}\n"
                f"- PR Number: {pull_number}\n"
                f"- API Base URL: {api_base_url}\n"
                f"- Changed Files Snapshot: {', '.join(files)}\n"
                f"- Snapshot SHA256: {compute_snapshot_sha256(files)}\n"
            )
            code_path.write_text(code_text, encoding="utf-8")
            ensure_command_ok(run_git_command(temp_root, ["add", "."]), "git add provider replay byte cap evidence")
            ensure_command_ok(run_git_command(temp_root, ["commit", "-q", "-m", "provider replay byte cap evidence"]), "git commit provider replay byte cap evidence")
            with temporary_env({GITHUB_API_ALLOWED_HOSTS_ENV: "127.0.0.1"}):
                return run_status_case(
                    "TASK-978",
                    artifacts_root,
                    expected_exit_code=1,
                    expected_output_fragment="exceeds replay byte cap",
                    title="Oversized provider response is rejected before JSON parsing",
                    case_id="RT-028",
                )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_rt_029() -> CaseResult:
    def mutation(temp_root: Path) -> None:
        path = temp_root / "template" / "README.md"
        text = path.read_text(encoding="utf-8").replace(
            ".github/ + OBSIDIAN.md + external/",
            "template/ + .github/ + OBSIDIAN.md + external/",
            1,
        )
        path.write_text(text, encoding="utf-8")
    return run_contract_case(
        expected_exit_code=1,
        expected_output_fragment="template/README.md section 'Architecture Snapshot' contains forbidden phrase: template/ + .github/ + OBSIDIAN.md + external/",
        mutation=mutation,
        title="README source/downstream wording drift",
        case_id="RT-029",
        notes="template README architecture snapshot regressed to source-only wording",
    )


def case_rt_030() -> CaseResult:
    temp_root = prepare_temp_root("RT-030")
    try:
        artifacts_root = copy_task_fixture(temp_root, "TASK-900", "TASK-977")
        overwrite_verify_with_corpus_case(artifacts_root, "TASK-977", "unparseable-fragment")
        report = mas.migrate_repository(temp_root, apply=True, input_mode=mas.EXTERNAL_LEGACY_MODE)
        verify_path = artifacts_root / "verify" / "TASK-977.verify.md"
        verify_text = verify_path.read_text(encoding="utf-8")
        status_payload = json.loads((artifacts_root / "status" / "TASK-977.status.json").read_text(encoding="utf-8"))
        passed = (
            report.changed_count() > 0
            and "Imported from external legacy verify artifact via manual-rewrite-fallback; confidence=low." in verify_text
            and "## Pass Fail Result\nfail" in verify_text
            and "MANUAL_CHECK_DEFERRED" in verify_text
            and bool(status_payload.get("open_verification_debts"))
        )
        output = "\n".join(
            [
                "[OK] fail-closed external legacy import confirmed" if passed else "[FAIL] external legacy import escaped fail-closed policy",
                f"changed_files={report.changed_count()}",
                f"open_verification_debts={status_payload.get('open_verification_debts', [])}",
            ]
        )
        result = completed_process_from_output(
            ["python", str(REPO_ROOT / "artifacts" / "scripts" / "migrate_artifact_schema.py")],
            0 if passed else 1,
            output,
        )
        return build_case_result(
            case_id="RT-030",
            phase="static",
            title="External legacy unparseable import stays fail-closed",
            expected="pass",
            expected_exit_code=0,
            expected_output_fragment="fail-closed external legacy import confirmed",
            result=result,
            notes="unparseable external legacy verify stays deferred with open verification debt",
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def case_live_950() -> CaseResult:
    result = run_command([sys.executable, str(STATUS_GUARD), "--task-id", "TASK-950", "--artifacts-root", str(REPO_ROOT / "artifacts")])
    return build_case_result(
        case_id="RT-LIVE-950",
        phase="live",
        title="Role boundary live drill",
        expected="pass",
        expected_exit_code=0,
        expected_output_fragment="[OK] Validation passed",
        result=result,
        notes="TASK-950 live drill should stay valid after decision / improvement closure",
    )


def case_live_951() -> CaseResult:
    result = run_command([sys.executable, str(STATUS_GUARD), "--task-id", "TASK-951", "--artifacts-root", str(REPO_ROOT / "artifacts")])
    return build_case_result(
        case_id="RT-LIVE-951",
        phase="live",
        title="Blocked / PDCA / resume live drill",
        expected="pass",
        expected_exit_code=0,
        expected_output_fragment="[OK] Validation passed",
        result=result,
        notes="TASK-951 live drill should prove Gate E before resume",
    )


def run_prompt_case(case_id: str, title: str, notes: str) -> CaseResult:
    result = run_command([sys.executable, str(PROMPT_REGRESSION), "--root", str(REPO_ROOT), "--case-id", case_id])
    return build_case_result(
        case_id=case_id,
        phase="prompt",
        title=title,
        expected="pass",
        expected_exit_code=0,
        expected_output_fragment="Prompt Regression Report",
        result=result,
        notes=notes,
    )


def case_pr_001() -> CaseResult:
    return run_prompt_case(
        "PR-001",
        "Violation input handling contract",
        "CLAUDE/CODEX prompts should enforce STOP or blocked behavior under ambiguous or invalid inputs",
    )


def case_pr_002() -> CaseResult:
    return run_prompt_case(
        "PR-002",
        "Role boundary contract",
        "Prompt contracts should prevent role overreach across Claude/Gemini/Codex",
    )


def case_pr_003() -> CaseResult:
    return run_prompt_case(
        "PR-003",
        "Fake citation defense contract",
        "Research prompt should enforce claim-level citation and anti-fabrication rules",
    )


def case_pr_004() -> CaseResult:
    return run_prompt_case(
        "PR-004",
        "Mixed truth-source isolation contract",
        "Research prompt should isolate upstream truth source from local fork assumptions",
    )


def case_pr_005() -> CaseResult:
    return run_prompt_case(
        "PR-005",
        "Research recommendation boundary",
        "Research prompt should explicitly forbid recommendation or architecture design outputs",
    )


def case_pr_006() -> CaseResult:
    return run_prompt_case(
        "PR-006",
        "Blocked wording quality contract",
        "Implementation prompt should keep blocked criteria explicit and avoid optimistic ambiguity",
    )


def case_pr_007() -> CaseResult:
    return run_prompt_case(
        "PR-007",
        "Premortem enforcement contract",
        "Implementation prompt should enforce premortem quality before coding",
    )


def case_pr_008() -> CaseResult:
    return run_prompt_case(
        "PR-008",
        "Artifact-only truth and completion contract",
        "Claude prompt should rely only on artifacts and reject completion without artifacts, verification, and evidence",
    )


def case_pr_009() -> CaseResult:
    return run_prompt_case(
        "PR-009",
        "Source/downstream sync split contract",
        "Workflow prompt should distinguish source template repos from downstream terminal repos",
    )


def case_pr_010() -> CaseResult:
    return run_prompt_case(
        "PR-010",
        "Research blocked preconditions and Gemini allowlist contract",
        "Gemini prompt should block bad research inputs and keep active workflow files on the allowlisted Gemini models",
    )


def case_pr_011() -> CaseResult:
    return run_prompt_case(
        "PR-011",
        "Implementation summary discipline contract",
        "Codex prompt should preserve approved-plan discipline, summary artifacts, and single-writer behavior",
    )


def case_pr_012() -> CaseResult:
    return run_prompt_case(
        "PR-012",
        "Conflict to decision routing contract",
        "Workflow contract should route conflicts into a recorded decision log before progress continues",
    )


def case_pr_013() -> CaseResult:
    return run_prompt_case(
        "PR-013",
        "Decision artifact trigger matrix contract",
        "Workflow contract should define when a decision artifact is mandatory for conflicts, tradeoffs, and validation failures",
    )


def case_pr_014() -> CaseResult:
    return run_prompt_case(
        "PR-014",
        "Decision artifact schema completeness contract",
        "Decision artifacts should preserve the chain from issue to follow-up rather than a single conclusion",
    )


def case_pr_015() -> CaseResult:
    return run_prompt_case(
        "PR-015",
        "External failure stop contract",
        "Claude prompt should stop and record external environment, build, or test failures without expanding scope",
    )


def case_pr_016() -> CaseResult:
    return run_prompt_case(
        "PR-016",
        "Decision-gated scope waiver contract",
        "Workflow contract should require an explicit decision waiver before --allow-scope-drift can downgrade failures",
    )


def case_pr_017() -> CaseResult:
    return run_prompt_case(
        "PR-017",
        "Historical diff evidence contract",
        "Workflow contract should define commit-range diff evidence for clean-task historical reconstruction",
    )


def case_pr_018() -> CaseResult:
    return run_prompt_case(
        "PR-018",
        "Pinned diff evidence integrity contract",
        "Workflow contract should require pinned commits plus snapshot checksum for immutable historical replay",
    )


def case_pr_019() -> CaseResult:
    return run_prompt_case(
        "PR-019",
        "GitHub provider-backed diff evidence contract",
        "Workflow contract should define GitHub PR files evidence, API base override, and token boundary for provider-backed replay",
    )


def case_pr_020() -> CaseResult:
    return run_prompt_case(
        "PR-020",
        "Archive retention fallback contract",
        "Workflow contract should define archive-backed fallback and archive integrity checks when git objects are no longer available",
    )


def case_pr_021() -> CaseResult:
    return run_prompt_case(
        "PR-021",
        "Gemini memory-bank curator draft-only contract",
        "Workflow contract should keep Gemini as a read-only memory-bank curator while Claude/Codex retain write authority",
    )


def case_pr_022() -> CaseResult:
    return run_prompt_case(
        "PR-022",
        "Claude CLI-first routing boundary contract",
        "Claude should stay CLI-first and route by task type, risk score, and context cost",
    )


def case_pr_023() -> CaseResult:
    return run_prompt_case(
        "PR-023",
        "Codex model/effort and subagent separation contract",
        "Codex should record task-scale execution profile and separate implementation from regression verification",
    )


def case_pr_024() -> CaseResult:
    return run_prompt_case(
        "PR-024",
        "Gemini Tavily draft cache boundary contract",
        "Gemini Tavily output should remain research/cache draft evidence and never become a direct memory-bank write",
    )


def case_pr_025() -> CaseResult:
    return run_prompt_case(
        "PR-025",
        "Memory-bank librarian quality filter contract",
        "Memory-bank capture should reject obvious, stale, short-lived, or untraceable information",
    )


STATIC_CASES: List[CaseDefinition] = [
    CaseDefinition("RT-001", "static", "Research artifact contains Recommendation", "fail", 1, "must not contain ## Recommendation", case_rt_001),
    CaseDefinition("RT-002", "static", "Confirmed Facts missing citation", "fail", 1, "must include an inline citation", case_rt_002),
    CaseDefinition("RT-003", "static", "Uncertain Items missing UNVERIFIED marker", "fail", 1, "must start with UNVERIFIED:", case_rt_003),
    CaseDefinition("RT-004", "static", "High-risk premortem without blocking risk", "fail", 1, "requires at least 1 blocking risks", case_rt_004),
    CaseDefinition("RT-005", "static", "Blocked resume without improvement artifact", "fail", 1, "requires an improvement artifact", case_rt_005),
    CaseDefinition("RT-006", "static", "Blocked resume with non-applied improvement", "fail", 1, "requires an improvement artifact with Status: applied", case_rt_006),
    CaseDefinition("RT-007", "static", "Contract drift between root and template", "fail", 1, "Contract drift detected", case_rt_007),
    CaseDefinition("RT-008", "static", "Obsidian drift", "fail", 1, "missing required phrase: template/OBSIDIAN.md", case_rt_008),
    CaseDefinition("RT-009", "static", "Bootstrap missing contract guard", "fail", 1, "BOOTSTRAP_PROMPT.md missing required phrase: guard_contract_validator.py", case_rt_009),
    CaseDefinition("RT-010", "static", "Research artifact missing Sources section", "fail", 1, "missing required ## Sources section", case_rt_010),
    CaseDefinition("RT-011", "static", "Code artifact Mapping To Plan malformed entry", "pass", 0, "Mapping To Plan entry must match", case_rt_011),
    CaseDefinition("RT-012", "static", "Verify artifact checklist reviewer field missing", "pass", 0, "missing reviewer field", case_rt_012),
    CaseDefinition("RT-013", "static", "Git-backed scope drift auto-guard", "fail", 1, "git-backed scope check found actual changed files not listed", case_rt_013),
    CaseDefinition("RT-014", "static", "Historical commit-range diff reconstruction", "fail", 1, "commit-range scope check found diff files not listed", case_rt_014),
    CaseDefinition("RT-015", "static", "allow-scope-drift without decision waiver", "fail", 1, "--allow-scope-drift requires a decision artifact with ## Guard Exception", case_rt_015),
    CaseDefinition("RT-016", "static", "allow-scope-drift with explicit decision waiver", "pass", 0, "[OK] Validation passed", case_rt_016),
    CaseDefinition("RT-017", "static", "Historical diff evidence checksum corruption", "fail", 1, "Snapshot SHA256 does not match Changed Files Snapshot", case_rt_017),
    CaseDefinition("RT-018", "static", "GitHub provider-backed PR second-page scope drift", "fail", 1, "github-pr scope check found diff files not listed", case_rt_018),
    CaseDefinition("RT-019", "static", "Historical diff archive fallback reconstruction", "fail", 1, "commit-range archive fallback found diff files not listed", case_rt_019),
    CaseDefinition("RT-020", "static", "Historical diff archive corruption", "fail", 1, "Archive SHA256 does not match archive file", case_rt_020),
    CaseDefinition("RT-021", "static", "Auto-classify lightweight candidate without plan artifact", "pass", 0, "lightweight candidate", case_rt_021),
    CaseDefinition("RT-022", "static", "Auto-classify escalates lightweight task with premortem", "pass", 0, "[AUTO-UPGRADE]", case_rt_022),
    CaseDefinition("RT-023", "static", "Expired decision waiver is rejected", "fail", 1, "waiver expired", case_rt_023),
    CaseDefinition("RT-024", "static", "GitHub provider-backed PR rejects non-allowlisted API host", "fail", 1, "API Base URL host '127.0.0.1' is not allowed", case_rt_024),
    CaseDefinition("RT-025", "static", "GitHub provider-backed PR accepts explicit allowlisted API host", "pass", 0, "[OK] Validation passed", case_rt_025),
    CaseDefinition("RT-026", "static", "Oversized workflow artifact is rejected before parsing", "fail", 1, "Text file too large", case_rt_026),
    CaseDefinition("RT-027", "static", "Oversized archive fallback is rejected before parsing", "fail", 1, "exceeds replay byte cap", case_rt_027),
    CaseDefinition("RT-028", "static", "Oversized provider response is rejected before JSON parsing", "fail", 1, "exceeds replay byte cap", case_rt_028),
    CaseDefinition("RT-029", "static", "README source/downstream wording drift", "fail", 1, "template/README.md section 'Architecture Snapshot' contains forbidden phrase: template/ + .github/ + OBSIDIAN.md + external/", case_rt_029),
    CaseDefinition("RT-030", "static", "External legacy unparseable import stays fail-closed", "pass", 0, "fail-closed external legacy import confirmed", case_rt_030),
]

LIVE_CASES: List[CaseDefinition] = [
    CaseDefinition("RT-LIVE-950", "live", "Role boundary live drill", "pass", 0, "[OK] Validation passed", case_live_950),
    CaseDefinition("RT-LIVE-951", "live", "Blocked / PDCA / resume live drill", "pass", 0, "[OK] Validation passed", case_live_951),
]

PROMPT_CASES: List[CaseDefinition] = [
    CaseDefinition("PR-001", "prompt", "Violation input handling contract", "pass", 0, "Prompt Regression Report", case_pr_001),
    CaseDefinition("PR-002", "prompt", "Role boundary contract", "pass", 0, "Prompt Regression Report", case_pr_002),
    CaseDefinition("PR-003", "prompt", "Fake citation defense contract", "pass", 0, "Prompt Regression Report", case_pr_003),
    CaseDefinition("PR-004", "prompt", "Mixed truth-source isolation contract", "pass", 0, "Prompt Regression Report", case_pr_004),
    CaseDefinition("PR-005", "prompt", "Research recommendation boundary", "pass", 0, "Prompt Regression Report", case_pr_005),
    CaseDefinition("PR-006", "prompt", "Blocked wording quality contract", "pass", 0, "Prompt Regression Report", case_pr_006),
    CaseDefinition("PR-007", "prompt", "Premortem enforcement contract", "pass", 0, "Prompt Regression Report", case_pr_007),
    CaseDefinition("PR-008", "prompt", "Artifact-only truth and completion contract", "pass", 0, "Prompt Regression Report", case_pr_008),
    CaseDefinition("PR-009", "prompt", "Source/downstream sync split contract", "pass", 0, "Prompt Regression Report", case_pr_009),
    CaseDefinition("PR-010", "prompt", "Research blocked preconditions and Gemini allowlist contract", "pass", 0, "Prompt Regression Report", case_pr_010),
    CaseDefinition("PR-011", "prompt", "Implementation summary discipline contract", "pass", 0, "Prompt Regression Report", case_pr_011),
    CaseDefinition("PR-012", "prompt", "Conflict to decision routing contract", "pass", 0, "Prompt Regression Report", case_pr_012),
    CaseDefinition("PR-013", "prompt", "Decision artifact trigger matrix contract", "pass", 0, "Prompt Regression Report", case_pr_013),
    CaseDefinition("PR-014", "prompt", "Decision artifact schema completeness contract", "pass", 0, "Prompt Regression Report", case_pr_014),
    CaseDefinition("PR-015", "prompt", "External failure stop contract", "pass", 0, "Prompt Regression Report", case_pr_015),
    CaseDefinition("PR-016", "prompt", "Decision-gated scope waiver contract", "pass", 0, "Prompt Regression Report", case_pr_016),
    CaseDefinition("PR-017", "prompt", "Historical diff evidence contract", "pass", 0, "Prompt Regression Report", case_pr_017),
    CaseDefinition("PR-018", "prompt", "Pinned diff evidence integrity contract", "pass", 0, "Prompt Regression Report", case_pr_018),
    CaseDefinition("PR-019", "prompt", "GitHub provider-backed diff evidence contract", "pass", 0, "Prompt Regression Report", case_pr_019),
    CaseDefinition("PR-020", "prompt", "Archive retention fallback contract", "pass", 0, "Prompt Regression Report", case_pr_020),
    CaseDefinition("PR-021", "prompt", "Gemini memory-bank curator draft-only contract", "pass", 0, "Prompt Regression Report", case_pr_021),
    CaseDefinition("PR-022", "prompt", "Claude CLI-first routing boundary contract", "pass", 0, "Prompt Regression Report", case_pr_022),
    CaseDefinition("PR-023", "prompt", "Codex model/effort and subagent separation contract", "pass", 0, "Prompt Regression Report", case_pr_023),
    CaseDefinition("PR-024", "prompt", "Gemini Tavily draft cache boundary contract", "pass", 0, "Prompt Regression Report", case_pr_024),
    CaseDefinition("PR-025", "prompt", "Memory-bank librarian quality filter contract", "pass", 0, "Prompt Regression Report", case_pr_025),
]


