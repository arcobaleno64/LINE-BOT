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


def detect_repo_root() -> Path:
    matches = [
        parent
        for parent in SCRIPT_PATH.parents
        if (parent / "docs" / "red_team_runbook.md").exists()
        and (parent / "artifacts" / "scripts" / "guard_contract_validator.py").exists()
        and (parent / "template").exists()
    ]
    if not matches:
        raise RuntimeError(f"Unable to detect repository root from {SCRIPT_PATH}")
    return matches[-1]


REPO_ROOT = detect_repo_root()
STATUS_GUARD = REPO_ROOT / "artifacts" / "scripts" / "guard_status_validator.py"
CONTRACT_GUARD = REPO_ROOT / "artifacts" / "scripts" / "guard_contract_validator.py"
PROMPT_REGRESSION = REPO_ROOT / "artifacts" / "scripts" / "prompt_regression_validator.py"
LOCAL_TMP_ROOT = REPO_ROOT / ".codex-red-team"
CREATED_TEMP_ROOTS: List[Path] = []
GITHUB_API_ALLOWED_HOSTS_ENV = "CONSILIUM_ALLOWED_GITHUB_API_HOSTS"


@dataclass
class CaseResult:
    case_id: str
    phase: str
    title: str
    expected: str
    expected_exit_code: int
    passed: bool
    exit_code: int
    evidence: str
    notes: str


@dataclass
class CaseDefinition:
    case_id: str
    phase: str
    title: str
    expected: str
    expected_exit_code: int
    expected_output_fragment: str
    runner: Callable[[], CaseResult]


def load_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MAX_ARTIFACT_FILE_BYTES = 512 * 1024
MAX_DIFF_EVIDENCE_REPLAY_BYTES = 128 * 1024
ALLOWED_ENV_OVERRIDES = {GITHUB_API_ALLOWED_HOSTS_ENV}
SUBPROCESS_DEFAULT_TIMEOUT = 60
SUBPROCESS_GIT_TIMEOUT = 30
MAX_SUBPROCESS_OUTPUT_BYTES = 1 * 1024 * 1024
TIMEOUT_RETURNCODE = -9999
EXCEPTION_RETURNCODE = -9998

__all__ = [
    "SCRIPT_PATH",
    "detect_repo_root",
    "REPO_ROOT",
    "STATUS_GUARD",
    "CONTRACT_GUARD",
    "PROMPT_REGRESSION",
    "LOCAL_TMP_ROOT",
    "CREATED_TEMP_ROOTS",
    "GITHUB_API_ALLOWED_HOSTS_ENV",
    "CaseResult",
    "CaseDefinition",
    "load_module",
    "MAX_ARTIFACT_FILE_BYTES",
    "MAX_DIFF_EVIDENCE_REPLAY_BYTES",
    "ALLOWED_ENV_OVERRIDES",
    "SUBPROCESS_DEFAULT_TIMEOUT",
    "SUBPROCESS_GIT_TIMEOUT",
    "MAX_SUBPROCESS_OUTPUT_BYTES",
    "TIMEOUT_RETURNCODE",
    "EXCEPTION_RETURNCODE",
    "_cap_output",
    "run_command",
    "run_git_command",
    "ensure_command_ok",
    "initialize_git_fixture",
    "git_rev_parse",
    "compute_snapshot_sha256",
    "github_pr_files_server",
    "temporary_env",
    "replace_task_id",
    "ensure_parent",
    "prepare_temp_root",
    "reset_temp_root_registry",
    "handle_remove_readonly",
    "cleanup_temp_roots",
    "copy_task_fixture",
    "overwrite_verify_with_corpus_case",
    "contract_fixture_paths",
    "copy_contract_fixture",
    "blocked_sample_source",
    "build_case_result",
    "completed_process_from_output",
    "run_status_case",
    "run_contract_case",
]


def _cap_output(text: str, max_bytes: int = MAX_SUBPROCESS_OUTPUT_BYTES) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="replace") + f"\n[OUTPUT TRUNCATED at {max_bytes} bytes]"


def run_command(args: Sequence[str], cwd: Optional[Path] = None, env: Optional[Dict[str, str]] = None, timeout: int = SUBPROCESS_DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    merged_env = None
    if env:
        invalid_keys = sorted(set(env) - ALLOWED_ENV_OVERRIDES)
        if invalid_keys:
            raise RuntimeError(f"Unsupported environment override(s): {', '.join(invalid_keys)}")
        for key, value in env.items():
            if not isinstance(value, str):
                raise RuntimeError(f"Environment override '{key}' must be a string")
        merged_env = os.environ.copy()
        merged_env.update(env)
    try:
        with subprocess.Popen(
            args,
            cwd=cwd or REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=merged_env,
        ) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                return subprocess.CompletedProcess(
                    args=list(args),
                    returncode=TIMEOUT_RETURNCODE,
                    stdout=f"[TIMEOUT after {timeout}s]\n{_cap_output(stdout)}",
                    stderr=_cap_output(stderr),
                )
            return subprocess.CompletedProcess(
                args=list(args),
                returncode=proc.returncode,
                stdout=_cap_output(stdout),
                stderr=_cap_output(stderr),
            )
    except Exception as exc:
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=EXCEPTION_RETURNCODE,
            stdout="",
            stderr=f"[ERROR] Unexpected subprocess exception: {exc}",
        )


def run_git_command(repo_root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return run_command(["git", "-C", str(repo_root), *args], cwd=REPO_ROOT, timeout=SUBPROCESS_GIT_TIMEOUT)


def ensure_command_ok(result: subprocess.CompletedProcess[str], description: str) -> None:
    if result.returncode == 0:
        return
    detail = result.stderr.strip() or result.stdout.strip() or "unknown command failure"
    raise RuntimeError(f"{description} failed: {detail}")


def initialize_git_fixture(repo_root: Path) -> None:
    ensure_command_ok(run_git_command(repo_root, ["init", "-q"]), "git init")
    ensure_command_ok(run_git_command(repo_root, ["config", "user.email", "red-team@example.invalid"]), "git config user.email")
    ensure_command_ok(run_git_command(repo_root, ["config", "user.name", "Red Team Fixture"]), "git config user.name")
    ensure_command_ok(run_git_command(repo_root, ["add", "."]), "git add baseline")
    ensure_command_ok(run_git_command(repo_root, ["commit", "-q", "-m", "baseline"]), "git commit baseline")


def git_rev_parse(repo_root: Path, revision: str) -> str:
    result = run_git_command(repo_root, ["rev-parse", f"{revision}^{{commit}}"])
    ensure_command_ok(result, f"git rev-parse {revision}")
    return result.stdout.strip().splitlines()[0]


def compute_snapshot_sha256(paths: Sequence[str]) -> str:
    payload = "\n".join(sorted(paths))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@contextmanager
def github_pr_files_server(repository: str, pull_number: int, pages: Dict[int, List[dict]]):
    owner, repo = repository.split("/", 1)
    expected_path = f"/repos/{owner}/{repo}/pulls/{pull_number}/files"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != expected_path:
                body = b'{"message": "not found"}'
                self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            query = urllib.parse.parse_qs(parsed.query)
            try:
                page = int(query.get("page", ["1"])[0])
            except ValueError:
                page = 1
            body = json.dumps(pages.get(page, [])).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@contextmanager
def temporary_env(overrides: Dict[str, str]):
    original_values = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            os.environ[key] = value
        yield
    finally:
        for key, original in original_values.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original


def replace_task_id(text: str, source_task_id: str, target_task_id: str) -> str:
    return text.replace(source_task_id, target_task_id)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def prepare_temp_root(case_id: str) -> Path:
    LOCAL_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    case_root = LOCAL_TMP_ROOT / f"{case_id}-{uuid.uuid4().hex[:8]}"
    case_root.mkdir(parents=True, exist_ok=False)
    CREATED_TEMP_ROOTS.append(case_root)
    return case_root


def reset_temp_root_registry() -> None:
    CREATED_TEMP_ROOTS.clear()


def handle_remove_readonly(func: Callable[..., object], path: str, _exc_info: object) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    func(path)


def cleanup_temp_roots(paths: Iterable[Path], *, temp_root: Optional[Path] = None) -> List[str]:
    errors: List[str] = []
    root = temp_root or LOCAL_TMP_ROOT
    unique_paths = sorted({path for path in paths}, key=lambda path: str(path), reverse=True)
    for path in unique_paths:
        if not path.exists():
            continue
        try:
            shutil.rmtree(path, onerror=handle_remove_readonly)
        except OSError as exc:
            errors.append(f"Failed to remove temp fixture '{path}': {exc}")
    if root.exists():
        try:
            next(root.iterdir())
        except StopIteration:
            try:
                root.rmdir()
            except OSError as exc:
                errors.append(f"Failed to remove temp root '{root}': {exc}")
        except OSError as exc:
            errors.append(f"Failed to inspect temp root '{root}': {exc}")
    return errors


def copy_task_fixture(temp_root: Path, source_task_id: str, target_task_id: str, include_improvement: bool = True) -> Path:
    dest_artifacts = temp_root / "artifacts"
    for directory in ("tasks", "research", "plans", "code", "verify", "status", "decisions", "improvement"):
        (dest_artifacts / directory).mkdir(parents=True, exist_ok=True)

    for source_path in (REPO_ROOT / "artifacts").rglob(f"{source_task_id}*"):
        if source_path.is_dir():
            continue
        if not include_improvement and source_path.suffix == ".md" and source_path.parent.name == "improvement":
            continue
        relative = source_path.relative_to(REPO_ROOT / "artifacts")
        dest_name = relative.name.replace(source_task_id, target_task_id, 1)
        dest_path = dest_artifacts / relative.parent / dest_name
        ensure_parent(dest_path)
        if source_path.suffix == ".json":
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            if payload.get("task_id") == source_task_id:
                payload["task_id"] = target_task_id
            dest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            text = source_path.read_text(encoding="utf-8")
            dest_path.write_text(replace_task_id(text, source_task_id, target_task_id), encoding="utf-8")
    return dest_artifacts


def overwrite_verify_with_corpus_case(artifacts_root: Path, target_task_id: str, case_id: str) -> Path:
    case = lvc.load_corpus_case(case_id)
    verify_path = artifacts_root / "verify" / f"{target_task_id}.verify.md"
    verify_path.write_text(case.text.replace("TASK-LEGACY", target_task_id), encoding="utf-8")
    return verify_path


def contract_fixture_paths(contract_module) -> List[str]:
    paths = set(contract_module.EXACT_SYNC_FILES)
    paths.add(contract_module.SOURCE_REPO_SENTINEL)
    paths.update(contract_module.REQUIRED_PHRASES.keys())
    for mode in (contract_module.SOURCE_REPO_MODE, contract_module.DOWNSTREAM_REPO_MODE):
        paths.update(contract_module.README_CONTRACTS[mode].keys())
        paths.update(contract_module.OBSIDIAN_CONTRACTS[mode].keys())
    for relative in list(paths):
        if relative != contract_module.SOURCE_REPO_SENTINEL and not relative.startswith("template/"):
            paths.add(f"template/{relative}")
    return sorted(paths)


def copy_contract_fixture(temp_root: Path) -> None:
    contract_module = load_module(CONTRACT_GUARD, "guard_contract_validator_runtime")
    for relative in contract_fixture_paths(contract_module):
        source = REPO_ROOT / relative
        destination = temp_root / relative
        ensure_parent(destination)
        shutil.copy2(source, destination)


def blocked_sample_source() -> str:
    if (REPO_ROOT / "artifacts" / "tasks" / "TASK-902.task.md").exists():
        return "TASK-902"
    return "TASK-901"


def build_case_result(
    *,
    case_id: str,
    phase: str,
    title: str,
    expected: str,
    expected_exit_code: int,
    expected_output_fragment: str,
    result: subprocess.CompletedProcess[str],
    notes: str,
) -> CaseResult:
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    passed = result.returncode == expected_exit_code and expected_output_fragment in output
    return CaseResult(
        case_id=case_id,
        phase=phase,
        title=title,
        expected=expected,
        expected_exit_code=expected_exit_code,
        passed=passed,
        exit_code=result.returncode,
        evidence=expected_output_fragment,
        notes=notes or (output.splitlines()[0] if output else ""),
    )


def completed_process_from_output(args: Sequence[str], returncode: int, output: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=list(args), returncode=returncode, stdout=output, stderr="")


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
    args = [sys.executable, str(STATUS_GUARD), "--task-id", task_id, "--artifacts-root", str(artifacts_root)]
    if from_state and to_state:
        args.extend(["--from-state", from_state, "--to-state", to_state])
    if extra_args:
        args.extend(extra_args)
    result = run_command(args, env=extra_env) if extra_env else run_command(args)
    return build_case_result(
        case_id=case_id,
        phase="static" if case_id.startswith("RT-") else "live",
        title=title,
        expected=expected or ("pass" if expected_exit_code == 0 else "fail"),
        expected_exit_code=expected_exit_code,
        expected_output_fragment=expected_output_fragment,
        result=result,
        notes=notes,
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
    temp_root = prepare_temp_root(case_id)
    try:
        copy_contract_fixture(temp_root)
        mutation(temp_root)
        result = run_command([sys.executable, str(CONTRACT_GUARD), "--root", str(temp_root)])
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    return build_case_result(
        case_id=case_id,
        phase="static",
        title=title,
        expected="pass" if expected_exit_code == 0 else "fail",
        expected_exit_code=expected_exit_code,
        expected_output_fragment=expected_output_fragment,
        result=result,
        notes=notes,
    )


