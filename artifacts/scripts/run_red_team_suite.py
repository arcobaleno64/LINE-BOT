#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import urllib.parse
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import legacy_verify_corpus as lvc
import migrate_artifact_schema as mas

SCRIPT_PATH = Path(__file__).resolve()


import red_team.helpers as helpers_module
import red_team.case_builders as case_builders_module
from red_team.helpers import *
from red_team.case_builders import *

HELPER_DETECT_REPO_ROOT = helpers_module.detect_repo_root
HELPER_PREPARE_TEMP_ROOT = helpers_module.prepare_temp_root
HELPER_RESET_TEMP_ROOT_REGISTRY = helpers_module.reset_temp_root_registry
HELPER_CLEANUP_TEMP_ROOTS = helpers_module.cleanup_temp_roots
HELPER_RUN_STATUS_CASE = helpers_module.run_status_case
HELPER_RUN_CONTRACT_CASE = helpers_module.run_contract_case
CASE_BUILDERS_RUN_PROMPT_CASE = case_builders_module.run_prompt_case

SCRIPT_PATH = Path(__file__).resolve()

REPO_ROOT = detect_repo_root()
STATUS_GUARD = REPO_ROOT / "artifacts" / "scripts" / "guard_status_validator.py"
CONTRACT_GUARD = REPO_ROOT / "artifacts" / "scripts" / "guard_contract_validator.py"
PROMPT_REGRESSION = REPO_ROOT / "artifacts" / "scripts" / "prompt_regression_validator.py"
LOCAL_TMP_ROOT = REPO_ROOT / ".codex-red-team"
CREATED_TEMP_ROOTS: List[Path] = []
GITHUB_API_ALLOWED_HOSTS_ENV = "CONSILIUM_ALLOWED_GITHUB_API_HOSTS"

MAX_ARTIFACT_FILE_BYTES = 512 * 1024
MAX_DIFF_EVIDENCE_REPLAY_BYTES = 128 * 1024
ALLOWED_ENV_OVERRIDES = {GITHUB_API_ALLOWED_HOSTS_ENV}
SUBPROCESS_DEFAULT_TIMEOUT = 60
SUBPROCESS_GIT_TIMEOUT = 30
MAX_SUBPROCESS_OUTPUT_BYTES = 1 * 1024 * 1024
TIMEOUT_RETURNCODE = -9999
EXCEPTION_RETURNCODE = -9998
CASE_METADATA_PATH = SCRIPT_PATH.parent / "red_team" / "cases_metadata.json"


def _sync_red_team_modules() -> None:
    helper_values = {
        "SCRIPT_PATH": SCRIPT_PATH,
        "REPO_ROOT": REPO_ROOT,
        "STATUS_GUARD": STATUS_GUARD,
        "CONTRACT_GUARD": CONTRACT_GUARD,
        "PROMPT_REGRESSION": PROMPT_REGRESSION,
        "LOCAL_TMP_ROOT": LOCAL_TMP_ROOT,
        "CREATED_TEMP_ROOTS": CREATED_TEMP_ROOTS,
        "GITHUB_API_ALLOWED_HOSTS_ENV": GITHUB_API_ALLOWED_HOSTS_ENV,
        "MAX_ARTIFACT_FILE_BYTES": MAX_ARTIFACT_FILE_BYTES,
        "MAX_DIFF_EVIDENCE_REPLAY_BYTES": MAX_DIFF_EVIDENCE_REPLAY_BYTES,
        "ALLOWED_ENV_OVERRIDES": ALLOWED_ENV_OVERRIDES,
        "SUBPROCESS_DEFAULT_TIMEOUT": SUBPROCESS_DEFAULT_TIMEOUT,
        "SUBPROCESS_GIT_TIMEOUT": SUBPROCESS_GIT_TIMEOUT,
        "MAX_SUBPROCESS_OUTPUT_BYTES": MAX_SUBPROCESS_OUTPUT_BYTES,
        "TIMEOUT_RETURNCODE": TIMEOUT_RETURNCODE,
        "EXCEPTION_RETURNCODE": EXCEPTION_RETURNCODE,
        "run_command": run_command,
    }
    case_values = {
        "REPO_ROOT": REPO_ROOT,
        "STATUS_GUARD": STATUS_GUARD,
        "CONTRACT_GUARD": CONTRACT_GUARD,
        "PROMPT_REGRESSION": PROMPT_REGRESSION,
        "GITHUB_API_ALLOWED_HOSTS_ENV": GITHUB_API_ALLOWED_HOSTS_ENV,
        "MAX_ARTIFACT_FILE_BYTES": MAX_ARTIFACT_FILE_BYTES,
        "run_command": run_command,
    }
    for name, value in helper_values.items():
        setattr(helpers_module, name, value)
        setattr(case_builders_module, name, value)
    for name, value in case_values.items():
        setattr(case_builders_module, name, value)


def detect_repo_root() -> Path:
    helpers_module.SCRIPT_PATH = SCRIPT_PATH
    return HELPER_DETECT_REPO_ROOT()


def prepare_temp_root(case_id: str) -> Path:
    _sync_red_team_modules()
    return HELPER_PREPARE_TEMP_ROOT(case_id)


def reset_temp_root_registry() -> None:
    _sync_red_team_modules()
    HELPER_RESET_TEMP_ROOT_REGISTRY()


def cleanup_temp_roots(paths: Iterable[Path], *, temp_root: Optional[Path] = None) -> List[str]:
    _sync_red_team_modules()
    return HELPER_CLEANUP_TEMP_ROOTS(paths, temp_root=temp_root)


def run_status_case(
    task_id: str,
    artifacts_root: Path,
    *,
    expected_exit_code: int,
    expected_output_fragment: str,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
    expected: str = "",
    title: str = "",
    case_id: str = "",
    notes: str = "",
    extra_args: Optional[Sequence[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> CaseResult:
    _sync_red_team_modules()
    return HELPER_RUN_STATUS_CASE(
        task_id,
        artifacts_root,
        expected_exit_code=expected_exit_code,
        expected_output_fragment=expected_output_fragment,
        from_state=from_state,
        to_state=to_state,
        expected=expected,
        title=title,
        case_id=case_id,
        notes=notes,
        extra_args=extra_args,
        extra_env=extra_env,
    )


def run_contract_case(
    *,
    expected_exit_code: int,
    expected_output_fragment: str,
    mutation: Callable[[Path], None],
    title: str,
    case_id: str,
    notes: str,
) -> CaseResult:
    _sync_red_team_modules()
    return HELPER_RUN_CONTRACT_CASE(
        expected_exit_code=expected_exit_code,
        expected_output_fragment=expected_output_fragment,
        mutation=mutation,
        title=title,
        case_id=case_id,
        notes=notes,
    )


def run_prompt_case(case_id: str, title: str, notes: str) -> CaseResult:
    _sync_red_team_modules()
    return CASE_BUILDERS_RUN_PROMPT_CASE(case_id, title, notes)


def _make_case_wrapper(name: str):
    def wrapper() -> CaseResult:
        _sync_red_team_modules()
        return getattr(case_builders_module, name)()

    wrapper.__name__ = name
    return wrapper


for _case_name in [
    "case_rt_001",
    "case_rt_002",
    "case_rt_003",
    "case_rt_004",
    "case_rt_005",
    "case_rt_006",
    "case_rt_007",
    "case_rt_008",
    "case_rt_009",
    "case_rt_010",
    "case_rt_011",
    "case_rt_012",
    "case_rt_013",
    "case_rt_014",
    "case_rt_015",
    "case_rt_016",
    "case_rt_017",
    "case_rt_018",
    "case_rt_019",
    "case_rt_020",
    "case_rt_021",
    "case_rt_022",
    "case_rt_023",
    "case_rt_024",
    "case_rt_025",
    "case_rt_026",
    "case_rt_027",
    "case_rt_028",
    "case_rt_029",
    "case_rt_030",
    "case_live_950",
    "case_live_951",
    "case_pr_001",
    "case_pr_002",
    "case_pr_003",
    "case_pr_004",
    "case_pr_005",
    "case_pr_006",
    "case_pr_007",
    "case_pr_008",
    "case_pr_009",
    "case_pr_010",
    "case_pr_011",
    "case_pr_012",
    "case_pr_013",
    "case_pr_014",
    "case_pr_015",
    "case_pr_016",
    "case_pr_017",
    "case_pr_018",
    "case_pr_019",
    "case_pr_020",
    "case_pr_021",
    "case_pr_022",
    "case_pr_023",
    "case_pr_024",
    "case_pr_025",
]:
    globals()[_case_name] = _make_case_wrapper(_case_name)


def _runner_name_for_case_id(case_id: str) -> str:
    if case_id.startswith("RT-LIVE-"):
        return f"case_live_{case_id.split('-')[-1]}"
    if case_id.startswith("RT-"):
        return f"case_rt_{case_id.split('-')[-1]}"
    if case_id.startswith("PR-"):
        return f"case_pr_{case_id.split('-')[-1]}"
    raise RuntimeError(f"Unsupported case id: {case_id}")


def build_cases() -> List[CaseDefinition]:
    case_metadata = json.loads(CASE_METADATA_PATH.read_text(encoding="utf-8"))
    source_cases = {
        case.case_id: case
        for case in [*case_builders_module.STATIC_CASES, *case_builders_module.LIVE_CASES, *case_builders_module.PROMPT_CASES]
    }
    cases: List[CaseDefinition] = []
    for entry in case_metadata:
        case_id = entry["case_id"]
        source = source_cases.get(case_id)
        if source is None:
            raise RuntimeError(f"Case metadata references unknown case id: {case_id}")
        runner_name = _runner_name_for_case_id(case_id)
        runner = globals().get(runner_name)
        if runner is None:
            raise RuntimeError(f"Case metadata references missing runner '{runner_name}' for {case_id}")
        cases.append(
            CaseDefinition(
                case_id=case_id,
                phase=entry["phase"],
                title=entry["title"],
                expected=source.expected,
                expected_exit_code=source.expected_exit_code,
                expected_output_fragment=source.expected_output_fragment,
                runner=runner,
            )
        )
    return cases


def render_markdown(results: Iterable[CaseResult]) -> str:
    lines = [
        "# Red Team Suite Report",
        "",
        "| Case | Phase | Expected | Outcome | Expected Exit | Actual Exit | Evidence | Notes |",
        "|---|---|---|---|---:|---:|---|---|",
    ]
    for result in results:
        outcome = "pass" if result.passed else "fail"
        lines.append(
            f"| `{result.case_id}` | {result.phase} | {result.expected} | {outcome} | "
            f"{result.expected_exit_code} | {result.exit_code} | `{result.evidence}` | {result.notes} |"
        )
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run built-in red-team exercises for the artifact-first workflow.")
    parser.add_argument("--phase", choices=("static", "live", "prompt", "all"), default="all", help="Which phase to run. Default: all")
    parser.add_argument("--static", action="store_true", help="Convenience alias for --phase static")
    parser.add_argument("--live", action="store_true", help="Convenience alias for --phase live")
    parser.add_argument("--prompt", action="store_true", help="Convenience alias for --phase prompt")
    parser.add_argument("--all", action="store_true", help="Convenience alias for --phase all")
    parser.add_argument("--keep-temp", action="store_true", help="Keep .codex-red-team fixtures for debugging instead of deleting them after the run")
    parser.add_argument("--output", help="Optional path to write the markdown report")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    aliases = [name for name in ("static", "live", "prompt", "all") if getattr(args, name)]
    if len(aliases) > 1:
        print("[FAIL] Only one of --static / --live / --prompt / --all may be used at a time", file=sys.stderr)
        return 2
    if aliases:
        args.phase = aliases[0]
    reset_temp_root_registry()
    selected = [case for case in build_cases() if args.phase in ("all", case.phase)]
    exit_code = 1
    try:
        results = [case.runner() for case in selected]
        report = render_markdown(results)
        print(report, end="")
        if args.output:
            output_path = Path(args.output)
            ensure_parent(output_path)
            output_path.write_text(report, encoding="utf-8")
        exit_code = 0 if all(result.passed for result in results) else 1
    finally:
        created_temp_roots = list(CREATED_TEMP_ROOTS)
        if args.keep_temp:
            if created_temp_roots:
                print(f"[NOTE] Kept red-team temp fixtures under {LOCAL_TMP_ROOT}")
                for path in created_temp_roots:
                    print(f"[NOTE] {path}")
        else:
            cleanup_errors = cleanup_temp_roots(created_temp_roots)
            if cleanup_errors:
                for error in cleanup_errors:
                    print(f"[FAIL] {error}", file=sys.stderr)
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
