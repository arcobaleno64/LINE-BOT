#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from workflow_constants import (
    ARTIFACT_TYPES,
    ASSURANCE_LEVELS,
    derive_verification_readiness,
    DECISION_CLASSES,
    DEFAULT_ASSURANCE_LEVEL,
    DEFAULT_PROJECT_ADAPTER,
    IMPROVEMENT_PROFILES,
    is_governance_decision_class,
    PROJECT_ADAPTERS,
    resolve_verification_policy,
    STRUCTURED_CHECKLIST_FIELDS as POLICY_STRUCTURED_CHECKLIST_FIELDS,
    validate_assurance_level_strict,
    warn_and_default_assurance_level,
    VERIFICATION_ITEM_RESULTS,
    VERIFICATION_REASON_CODES,
    VERIFICATION_READINESS_STATES,
    VERIFY_FLOOR_BASELINE_PATH,
    VERIFY_FLOOR_POLICY_HISTORICAL,
    VERIFY_FLOOR_POLICY_STRICT,
    WORKFLOW_STATES,
)

__version__ = "0.9.1"
TAIPEI_TZ = timezone(timedelta(hours=8))

STATE_ORDER = list(WORKFLOW_STATES)
VALID_STATES: Set[str] = set(STATE_ORDER)
LEGAL_TRANSITIONS: Dict[str, Set[str]] = {
    "drafted": {"researched", "planned", "blocked"},  # planned: lightweight mode (no research needed)
    "researched": {"planned", "blocked"},
    "planned": {"coding", "blocked"},
    "coding": {"testing", "verifying", "blocked"},
    "testing": {"verifying", "coding", "blocked"},
    "verifying": {"done", "coding", "blocked"},
    "done": set(),
    "blocked": {"drafted", "researched", "planned", "coding", "testing", "verifying"},
}
ARTIFACT_DIRS = {
    "task": "tasks",
    "research": "research",
    "plan": "plans",
    "code": "code",
    "test": "test",
    "verify": "verify",
    "decision": "decisions",
    "improvement": "improvement",
    "status": "status",
}
ARTIFACT_EXTENSIONS = {
    "task": ".task.md",
    "research": ".research.md",
    "plan": ".plan.md",
    "code": ".code.md",
    "test": ".test.md",
    "verify": ".verify.md",
    "decision": ".decision.md",
    "improvement": ".improvement.md",
    "status": ".status.json",
}
STATE_REQUIRED_ARTIFACTS = {
    "drafted": {"task", "status"},
    "researched": {"task", "research", "status"},
    "planned": {"task", "plan", "status"},
    "coding": {"task", "plan", "code", "status"},
    "testing": {"task", "plan", "code", "test", "status"},
    "verifying": {"task", "code", "status"},
    "done": {"task", "code", "verify", "status"},
    "blocked": {"task", "status"},
}
MARKERS = {
    "task": (
        "# Task:",
        "## Metadata",
        "Task ID:",
        "Artifact Type: task",
        ("## Objective", "## Description"),
        ("## Constraints", "## Non Goals", "## Authorized Production Surface"),
        "## Acceptance Criteria",
    ),
    "research": ("# Research:", "## Metadata", "Artifact Type: research", "## Research Questions", "## Confirmed Facts", "## Relevant References", "## Uncertain Items", "## Constraints For Implementation"),
    "plan": (
        "# Plan:",
        "## Metadata",
        "Artifact Type: plan",
        ("## Scope", "## Goal"),
        "## Files Likely Affected",
        ("## Proposed Changes", "## Approach"),
        ("## Validation Strategy", "## Premortem", "## Build Guarantee", "## TAO Trace"),
    ),
    "code": ("# Code Result:", "## Metadata", "Artifact Type: code", "## Files Changed", "## Summary Of Changes", "## Mapping To Plan"),
    "test": ("# Test Report:", "## Metadata", "Artifact Type: test", "## Test Scope", "## Commands Executed", "## Result Summary"),
    "verify": ("# Verification:", "## Metadata", "Artifact Type: verify", "## Acceptance Criteria Checklist", "## Pass Fail Result", "## Build Guarantee"),
    "decision": (
        ("# Decision Log:", "# Decision:"),
        "## Metadata",
        "Artifact Type: decision",
        ("## Issue", "## Context"),
        ("## Chosen Option", "## Decision"),
        ("## Reasoning", "## Consequences"),
    ),
    "improvement": ("# Process Improvement", "## Metadata", "Artifact Type: improvement", "Source Task:", "Trigger Type:", "## 1. What Happened", "## 2. Why It Was Not Prevented", "## 3. Failure Classification", "## 5. Preventive Action (System Level)", "## 6. Validation", "## 8. Final Rule", "## 9. Status"),
}


ARTIFACT_ALLOWED_STATUSES = {
    "task": {"drafted", "approved", "blocked", "done"},
    "research": {"in_progress", "ready", "blocked", "superseded"},
    "plan": {"drafted", "ready", "approved", "blocked", "superseded"},
    "code": {"in_progress", "ready", "blocked", "superseded"},
    "test": {"in_progress", "pass", "fail", "blocked", "superseded"},
    "verify": {"pass", "fail", "blocked", "superseded"},
    "decision": {"done"},
    "improvement": {"draft", "approved", "applied"},
}

TASK_ID_PATTERN = re.compile(r"^TASK(?:-LITE)?-\d{3,}$")
TAIPEI_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+08:00$")
CITATION_PATTERN = re.compile(
    r"(?:"
    r"https?://\S+"
    r"|`gh api [^`]+`"
    r"|`[^`\n]+\.(?:md|json|txt|py|ps1|csproj|ini|toml|yml|yaml|cfg|sh)[^`\n]*`"
    r"|[（(](?:[Ss]ource:\s*)?[^)）\n]*?[A-Za-z0-9_./\\-]+\.(?:md|json|txt|py|ps1|csproj|ini|toml|yml|yaml|cfg|sh)(?::\d+)?[^)）\n]*[)）]"
    r"|\b[A-Za-z0-9_./\\-]+\.(?:md|json|txt|py|ps1|csproj|ini|toml|yml|yaml|cfg|sh)(?::\d+)?\b"
    r")",
    re.IGNORECASE,
)
LIST_ITEM_PATTERN = re.compile(r"^(?:- |\d+\. )")
TASK_INLINE_FLAG_PATTERN = re.compile(r"^\s*(?:-\s*)?([A-Za-z_][A-Za-z0-9_\- ]*)\s*:\s*(.+?)\s*$")
GITHUB_REPO_REF_PATTERNS = (
    re.compile(r"https?://github\.com/([^/\s]+)/([^/\s`#?]+)/?", re.IGNORECASE),
    re.compile(r"https?://raw\.githubusercontent\.com/([^/\s]+)/([^/\s`#?]+)/", re.IGNORECASE),
)
FILE_PATH_TOKEN_PATTERN = re.compile(r"\b(?:[A-Za-z]:[\\/])?[A-Za-z0-9_.\-\\/]+\.[A-Za-z0-9]{1,10}\b")
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
PREMORTEM_REQUIRED_FIELDS = ("Risk:", "Trigger:", "Detection:", "Mitigation:", "Severity:")
PREMORTEM_BANNED_PHRASES = ("風險低", "應該沒問題", "可能有風險", "視情況而定", "再觀察", "注意一下", "需評估", "有待確認")
HIGH_RISK_KEYWORDS = ("security", "安全", "dependency", "依賴", "upstream pr", "upstream", "cross-repo", "cross repo", "跨 repo")
IGNORED_GIT_SCOPE_PATHS = {"obsidian/workspace.json", ".obsidian/workspace.json"}
DIFF_EVIDENCE_SUPPORTED_TYPES = {"commit-range", "github-pr"}
SCOPE_WAIVER_EXCEPTION_TYPE = "allow-scope-drift"
GITHUB_API_VERSION = "2022-11-28"
MAX_GITHUB_PR_FILES_PAGES = 30
MAX_ARTIFACT_FILE_BYTES = 512 * 1024
MAX_DIFF_EVIDENCE_REPLAY_BYTES = 128 * 1024
GITHUB_API_ALLOWED_HOSTS_ENV = "CONSILIUM_ALLOWED_GITHUB_API_HOSTS"
DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"
DEFAULT_GITHUB_API_ALLOWED_HOSTS = {"api.github.com"}
LEGACY_STATE_ALIASES = {
    "research_ready": "researched",
    "plan_ready": "planned",
    "code_ready": "coding",
    "verify_ready": "verifying",
}
RESEARCH_SOURCES_ENTRY_PATTERN = re.compile(
    r"^\[(\d+)\]\s+.+\..+(?:https?://\S+|[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]{1,10})\s+\(\d{4}-\d{2}-\d{2}\s+retrieved\)$"
)
RESEARCH_SOURCES_URL_PATTERN = re.compile(r"https?://\S+")
RESEARCH_SOURCES_PARTIAL_DATE_PATTERN = re.compile(r"\((\d{4}(?:-\d{2})?(?:-\d{2})?)\s+retrieved\)$")
MAPPING_TO_PLAN_ENTRY_PATTERN = re.compile(
    r'^- plan_item:\s*\d+\.\d+,\s*status:\s*(done|partial|skipped),\s*evidence:\s*"[^"\n]+"\s*$'
)
STRUCTURED_CHECKLIST_FIELDS = POLICY_STRUCTURED_CHECKLIST_FIELDS
PREMORTEM_MISSING_PATTERNS = (
    "## risks section not found",
    "section is empty or trivially dismissed",
)
RECONCILE_PROTECTED_FIELDS = {"Gate_E_passed", "Gate_E_evidence", "Gate_E_timestamp"}
OVERRIDE_STATUS_FLAG = "override_log_required"
DEFAULT_STATUS_OWNER = "Claude"
DEFAULT_STATUS_NEXT_AGENT = "Claude"
BLOCKED_STATUS_NEXT_AGENT = "User"
LIGHTWEIGHT_REQUIRED_ARTIFACTS = {"task", "code", "status"}
DECISION_GATE_PATTERN = re.compile(r"^Gate_[A-E]$")
NON_VERIFIED_RESULTS = {"unverified", "unverifiable", "deferred"}
DECISION_WAIVER_GATES = {
    "Gate_A": "A",
    "Gate_B": "B",
    "Gate_C": "C",
    "Gate_D": "D",
    "Gate_E": "E",
}
AUTO_CLASSIFY_FULL = "full"
AUTO_CLASSIFY_LIGHTWEIGHT = "lightweight"


@dataclass(frozen=True)
class PremortemPolicy:
    task_type: str
    keyword_regex: str
    min_risks: int
    min_critical: int


PREMORTEM_POLICIES: Tuple[PremortemPolicy, ...] = (
    PremortemPolicy("hotfix", r"\bhotfix\b|\bpatch\b", 1, 0),
    PremortemPolicy("research", r"\bresearch\b|\banalysis\b", 2, 1),
    PremortemPolicy("planning", r"\bplan\b|\bdesign\b", 3, 1),
    PremortemPolicy("code", "(default)", 3, 1),
)
PREMORTEM_POLICY_PATTERNS = {
    policy.task_type: re.compile(policy.keyword_regex, re.IGNORECASE)
    for policy in PREMORTEM_POLICIES
    if policy.keyword_regex != "(default)"
}


@dataclass
class ValidationResult:
    errors: List[str]
    warnings: List[str]
    active_waivers: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ScopeCheckResult:
    errors: List[str]
    waiver_candidate_errors: List[str]
    warnings: List[str]
    drift_files: Set[str]


@dataclass
class ValidationError:
    severity: str
    message: str


@dataclass
class AutoClassificationResult:
    validation_mode: str
    warnings: List[str]


class GuardError(Exception):
    pass


from guard_helpers.markers import *
from guard_helpers.parsers import *
from guard_helpers.io import *

def companion_artifact_path(path: Path, artifact_type: str, task_id: str) -> Path:
    artifacts_root = path.parent.parent
    return artifact_path(artifacts_root, task_id, artifact_type)


def resolve_artifact_profile(path: Path, task_id: str) -> Tuple[str, str]:
    status_path = companion_artifact_path(path, "status", task_id)
    task_path = companion_artifact_path(path, "task", task_id)
    status = load_json(status_path) if status_path.exists() else {}
    task_text = load_text(task_path) if task_path.exists() else ""
    return resolve_assurance_level(task_text, status), resolve_project_adapter(task_text, status)


def resolve_task_policy(
    task_text: str = "",
    status: Optional[dict] = None,
    assurance_level: Optional[str] = None,
    project_adapter: Optional[str] = None,
) -> Dict[str, object]:
    resolved_assurance = assurance_level or resolve_assurance_level(task_text, status)
    resolved_adapter = project_adapter or resolve_project_adapter(task_text, status)
    return resolve_verification_policy(resolved_assurance, resolved_adapter)


def plan_has_non_empty_risks(plan_text: str) -> bool:
    risks_text = extract_section(plan_text, "Risks")
    return bool(risks_text and risks_text.strip().lower() not in {"", "none", "n/a"})


def resolve_workspace_relative_path(repo_root: Path, raw_path: str) -> Tuple[Optional[str], Optional[Path], Optional[str]]:
    normalized = normalize_path_token(raw_path)
    if not normalized:
        return None, None, "path is empty"
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../") or "/../" in normalized:
        return None, None, "path must stay within repository root"
    candidate = repo_root / normalized
    try:
        resolved_root = repo_root.resolve()
        resolved_candidate = candidate.resolve()
    except OSError as exc:
        return None, None, str(exc)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        return None, None, "path escapes repository root"
    return normalized, resolved_candidate, None


def parse_repository_ref(value: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    parts = [part.strip() for part in value.split("/")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None, None, "Repository must use owner/repo format"
    if parts[0] in {".", ".."} or parts[1] in {".", ".."}:
        return None, None, "Repository owner/repo segments must be concrete names"
    return parts[0], parts[1], None


def get_allowed_github_api_hosts() -> Set[str]:
    hosts = set(DEFAULT_GITHUB_API_ALLOWED_HOSTS)
    raw_value = os.environ.get(GITHUB_API_ALLOWED_HOSTS_ENV, "")
    for token in raw_value.split(","):
        candidate = token.strip()
        if not candidate:
            continue
        if "://" not in candidate:
            candidate = f"https://{candidate}"
        parsed = urllib.parse.urlparse(candidate)
        hostname = (parsed.hostname or "").strip().lower()
        if hostname:
            hosts.add(hostname)
    return hosts


def normalize_api_base_url(raw_value: str) -> Tuple[Optional[str], Optional[str]]:
    value = raw_value.strip() or DEFAULT_GITHUB_API_BASE_URL
    value = value.rstrip("/")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None, "API Base URL must be an absolute http(s) URL"
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return None, "API Base URL must include a hostname"
    allowed_hosts = get_allowed_github_api_hosts()
    if hostname not in allowed_hosts:
        allowed_list = ", ".join(sorted(allowed_hosts))
        return None, (
            f"API Base URL host '{hostname}' is not allowed. "
            f"Allowed hosts: {allowed_list}. "
            f"Set {GITHUB_API_ALLOWED_HOSTS_ENV} to allow trusted GitHub Enterprise hosts."
        )
    return value, None


def summarize_remote_error_detail(raw_body: bytes, fallback: str) -> str:
    if raw_body:
        text = raw_body.decode("utf-8", errors="replace").strip()
        if text:
            return text[:200] + ("..." if len(text) > 200 else "")
    return fallback


def load_archive_snapshot(repo_root: Path, code_path: Path, evidence: Dict[str, str], snapshot_files: Set[str]) -> Tuple[Optional[Set[str]], Optional[str], Optional[str]]:
    raw_archive_path = evidence.get("archive path", "").strip()
    archive_sha256 = evidence.get("archive sha256", "").strip().lower()
    if bool(raw_archive_path) != bool(archive_sha256):
        return None, None, f"{code_path.name}: commit-range ## Diff Evidence requires Archive Path and Archive SHA256 together"
    if not raw_archive_path:
        return None, None, None
    if not re.fullmatch(r"[0-9a-f]{64}", archive_sha256):
        return None, None, f"{code_path.name}: Archive SHA256 must be a 64-character hexadecimal string"
    archive_rel, archive_path, path_error = resolve_workspace_relative_path(repo_root, raw_archive_path)
    if path_error or archive_rel is None or archive_path is None:
        return None, None, f"{code_path.name}: invalid Archive Path '{raw_archive_path}': {path_error}"
    try:
        archive_bytes = archive_path.read_bytes()
    except FileNotFoundError:
        return None, None, f"{code_path.name}: Archive Path '{archive_rel}' does not exist"
    except OSError as exc:
        return None, None, f"{code_path.name}: unable to read Archive Path '{archive_rel}': {exc}"
    if len(archive_bytes) > MAX_DIFF_EVIDENCE_REPLAY_BYTES:
        return None, None, (
            f"{code_path.name}: Archive Path '{archive_rel}' exceeds replay byte cap of {MAX_DIFF_EVIDENCE_REPLAY_BYTES} bytes"
        )
    actual_archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    if actual_archive_sha256 != archive_sha256:
        return None, None, (
            f"{code_path.name}: Archive SHA256 does not match archive file {archive_rel}. "
            f"expected={actual_archive_sha256} actual={archive_sha256}"
        )
    try:
        archive_text = archive_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, None, f"{code_path.name}: Archive Path '{archive_rel}' must be UTF-8 text: {exc}"
    archive_lines = archive_text.splitlines()
    if not archive_lines:
        return None, None, f"{code_path.name}: Archive Path '{archive_rel}' must contain at least one normalized file path"
    normalized_lines: List[str] = []
    seen: Set[str] = set()
    for index, raw_line in enumerate(archive_lines, start=1):
        if not raw_line.strip():
            return None, None, f"{code_path.name}: Archive Path '{archive_rel}' contains a blank line at line {index}"
        normalized = normalize_path_token(raw_line)
        if not normalized or normalized == ".." or normalized.startswith("../") or "/../" in normalized:
            return None, None, f"{code_path.name}: Archive Path '{archive_rel}' contains an invalid path at line {index}: {raw_line!r}"
        if normalized in seen:
            return None, None, f"{code_path.name}: Archive Path '{archive_rel}' contains a duplicate path at line {index}: {normalized}"
        seen.add(normalized)
        normalized_lines.append(normalized)
    if normalized_lines != sorted(normalized_lines):
        return None, None, f"{code_path.name}: Archive Path '{archive_rel}' must contain sorted normalized file paths"
    archive_files = set(normalized_lines)
    if archive_files != snapshot_files:
        return None, None, (
            f"{code_path.name}: Archive file {archive_rel} does not match Changed Files Snapshot. "
            f"snapshot={sorted(snapshot_files)} archive={sorted(archive_files)}"
        )
    return archive_files, archive_rel, None


def collect_github_pr_files(repository: str, pull_number: str, api_base_url: str) -> Tuple[Set[str], Optional[str]]:
    owner, repo, repo_error = parse_repository_ref(repository)
    if repo_error or owner is None or repo is None:
        return set(), repo_error
    if not pull_number.isdigit() or int(pull_number) <= 0:
        return set(), "PR Number must be a positive integer"
    base_url, base_error = normalize_api_base_url(api_base_url)
    if base_error or base_url is None:
        return set(), base_error
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"antigravity-guard-status-validator/{__version__}",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    changed_files: Set[str] = set()
    for page in range(1, MAX_GITHUB_PR_FILES_PAGES + 2):
        url = (
            f"{base_url}/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}"
            f"/pulls/{pull_number}/files?per_page=100&page={page}"
        )
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_body = response.read(MAX_DIFF_EVIDENCE_REPLAY_BYTES + 1)
        except urllib.error.HTTPError as exc:
            detail = summarize_remote_error_detail(exc.read(), exc.reason or "HTTP error")
            auth_hint = " Set GITHUB_TOKEN or GH_TOKEN when accessing private or rate-limited repositories." if exc.code in {401, 403, 404} and not token else ""
            return set(), f"HTTP {exc.code} from {url}: {detail}{auth_hint}"
        except urllib.error.URLError as exc:
            return set(), f"connection error while fetching {url}: {exc.reason}"
        if len(response_body) > MAX_DIFF_EVIDENCE_REPLAY_BYTES:
            return set(), f"provider response from {url} exceeds replay byte cap of {MAX_DIFF_EVIDENCE_REPLAY_BYTES} bytes"
        try:
            payload = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return set(), f"invalid JSON response from {url}: {exc}"
        if not isinstance(payload, list):
            return set(), f"unexpected non-list response from {url}"
        if page > MAX_GITHUB_PR_FILES_PAGES and payload:
            return set(), f"provider response exceeds GitHub PR files endpoint cap of {MAX_GITHUB_PR_FILES_PAGES * 100} files"
        if not payload:
            break
        for item in payload:
            if not isinstance(item, dict):
                return set(), f"provider response from {url} contains a non-object file entry"
            filename = item.get("filename")
            if not isinstance(filename, str) or not filename.strip():
                return set(), f"provider response from {url} contains a file entry without filename"
            normalized = normalize_path_token(filename)
            if not normalized:
                return set(), f"provider response from {url} contains an invalid filename {filename!r}"
            changed_files.add(normalized)
        if len(payload) < 100:
            break
    return changed_files, None


def compare_reconstructed_scope(plan_path: Path, code_path: Path, changed_files: Set[str], scope_label: str) -> ScopeCheckResult:
    errors: List[str] = []
    waiver_candidate_errors: List[str] = []
    warnings: List[str] = []
    drift_files: Set[str] = set()
    plan_text = load_text(plan_path)
    code_text = load_text(code_path)
    planned_files = extract_file_tokens(extract_section(plan_text, "Files Likely Affected"))
    declared_changed = extract_file_tokens(extract_section(code_text, "Files Changed"))
    undeclared_actual = sorted(changed_files - declared_changed)
    if undeclared_actual:
        waiver_candidate_errors.append(
            f"{code_path.name}: {scope_label} found diff files not listed in ## Files Changed: {undeclared_actual}"
        )
        drift_files.update(undeclared_actual)
    unplanned_actual = sorted(changed_files - planned_files)
    if unplanned_actual:
        waiver_candidate_errors.append(
            f"{plan_path.name}: {scope_label} found diff files not listed in ## Files Likely Affected: {unplanned_actual}"
        )
        drift_files.update(unplanned_actual)
    return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)


def detect_mixed_github_sources(text: str) -> List[str]:
    owners_by_repo: Dict[str, Set[str]] = {}
    for pattern in GITHUB_REPO_REF_PATTERNS:
        for owner, repo in pattern.findall(text):
            normalized_repo = repo.lower()
            owners_by_repo.setdefault(normalized_repo, set()).add(owner.lower())
    mixed: List[str] = []
    for repo, owners in sorted(owners_by_repo.items()):
        if len(owners) > 1:
            mixed.append(f"{repo}: {sorted(owners)}")
    return mixed


def detect_plan_code_scope_drift(plan_text: str, code_text: str) -> List[str]:
    planned_files = extract_file_tokens(extract_section(plan_text, "Files Likely Affected"))
    changed_files = extract_file_tokens(extract_section(code_text, "Files Changed"))
    if not planned_files or not changed_files:
        return []
    return sorted(changed_files - planned_files)


def parse_diff_evidence(code_text: str) -> Optional[Dict[str, str]]:
    section = extract_section(code_text, "Diff Evidence")
    if not section or section.strip().lower() == "none":
        return None
    return parse_key_value_section(section)


def detect_git_root(start: Path) -> Optional[Path]:
    resolved = start.resolve()
    for candidate in [resolved, *resolved.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def load_git_scope_context(artifacts_root: Path, task_id: str) -> Tuple[Optional[Path], Set[str], Set[str], List[str]]:
    repo_root = detect_git_root(artifacts_root)
    if not repo_root:
        return None, set(), set(), []
    actual_changed, warnings = collect_git_changed_files(repo_root)
    task_artifacts = task_artifact_relative_paths(artifacts_root, task_id, repo_root)
    return repo_root, actual_changed, task_artifacts, warnings


def collect_git_changed_files(repo_root: Path) -> Tuple[Set[str], List[str]]:
    warnings: List[str] = []
    changed: Set[str] = set()
    commands = [
        ["git", "-C", str(repo_root), "diff", "--name-only", "--cached"],
        ["git", "-C", str(repo_root), "diff", "--name-only"],
        ["git", "-C", str(repo_root), "ls-files", "--others", "--exclude-standard"],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        except FileNotFoundError:
            return set(), ["git-backed scope check skipped: git command not available"]
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
            warnings.append(f"git-backed scope check skipped in {repo_root}: {' '.join(command[3:])} failed: {detail}")
            return set(), warnings
        for raw_line in result.stdout.splitlines():
            normalized = normalize_path_token(raw_line)
            if normalized and normalized not in IGNORED_GIT_SCOPE_PATHS and not (repo_root / normalized).is_dir():
                changed.add(normalized)
    return changed, warnings


def collect_git_diff_range_files(repo_root: Path, base_ref: str, head_ref: str) -> Tuple[Set[str], Optional[str]]:
    command = ["git", "-C", str(repo_root), "diff", "--name-only", f"{base_ref}..{head_ref}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        return set(), "git command not available"
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        return set(), detail
    changed: Set[str] = set()
    for raw_line in result.stdout.splitlines():
        normalized = normalize_path_token(raw_line)
        if normalized and normalized not in IGNORED_GIT_SCOPE_PATHS and not (repo_root / normalized).is_dir():
            changed.add(normalized)
    return changed, None


def resolve_git_revision_commit(repo_root: Path, revision: str) -> Tuple[Optional[str], Optional[str]]:
    command = ["git", "-C", str(repo_root), "rev-parse", f"{revision}^{{commit}}"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError:
        return None, "git command not available"
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        return None, detail
    return result.stdout.strip().splitlines()[0], None


def task_artifact_relative_paths(artifacts_root: Path, task_id: str, repo_root: Path) -> Set[str]:
    paths: Set[str] = set()
    for artifact_type in ARTIFACT_DIRS:
        for path in find_artifact_paths(artifacts_root, task_id, artifact_type):
            try:
                relative = path.relative_to(repo_root)
            except ValueError:
                continue
            paths.add(normalize_path_token(str(relative)))
    return paths


def detect_git_backed_scope_drift(plan_path: Path, code_path: Path, actual_changed: Set[str], task_artifacts: Set[str]) -> ScopeCheckResult:
    errors: List[str] = []
    waiver_candidate_errors: List[str] = []
    warnings: List[str] = []
    drift_files: Set[str] = set()
    if not actual_changed or not task_artifacts.intersection(actual_changed):
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    plan_text = load_text(plan_path)
    code_text = load_text(code_path)
    planned_files = extract_file_tokens(extract_section(plan_text, "Files Likely Affected"))
    declared_changed = extract_file_tokens(extract_section(code_text, "Files Changed"))
    actual_scope_changed = {
        path
        for path in (actual_changed - task_artifacts)
        if not path.startswith("artifacts/") or path in declared_changed or path in planned_files
    }
    if not actual_scope_changed:
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    undeclared_actual = sorted(actual_scope_changed - declared_changed)
    if undeclared_actual:
        waiver_candidate_errors.append(
            f"{code_path.name}: git-backed scope check found actual changed files not listed in ## Files Changed: {undeclared_actual}"
        )
        drift_files.update(undeclared_actual)
    unplanned_actual = sorted(actual_scope_changed - planned_files)
    if unplanned_actual:
        waiver_candidate_errors.append(
            f"{plan_path.name}: git-backed scope check found actual changed files not listed in ## Files Likely Affected: {unplanned_actual}"
        )
        drift_files.update(unplanned_actual)
    return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)


def detect_historical_diff_scope_drift(repo_root: Optional[Path], plan_path: Path, code_path: Path) -> ScopeCheckResult:
    errors: List[str] = []
    waiver_candidate_errors: List[str] = []
    warnings: List[str] = []
    drift_files: Set[str] = set()
    code_text = load_text(code_path)
    evidence = parse_diff_evidence(code_text)
    if not evidence:
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    evidence_type = evidence.get("evidence type", "").strip().lower()
    if evidence_type not in DIFF_EVIDENCE_SUPPORTED_TYPES:
        errors.append(
            f"{code_path.name}: unsupported ## Diff Evidence type '{evidence_type or '<missing>'}'. Supported types: {sorted(DIFF_EVIDENCE_SUPPORTED_TYPES)}"
        )
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    snapshot_files = parse_csv_file_tokens(evidence.get("changed files snapshot", ""))
    snapshot_sha256 = evidence.get("snapshot sha256", "").strip().lower()
    if not snapshot_files or not snapshot_sha256:
        requirement = "Repository, PR Number, Changed Files Snapshot, and Snapshot SHA256" if evidence_type == "github-pr" else "Base Commit, Head Commit, Diff Command, Changed Files Snapshot, and Snapshot SHA256"
        errors.append(f"{code_path.name}: {evidence_type} ## Diff Evidence requires non-empty {requirement}")
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    expected_snapshot_hash = compute_snapshot_sha256(snapshot_files)
    if snapshot_sha256 != expected_snapshot_hash:
        errors.append(
            f"{code_path.name}: Snapshot SHA256 does not match Changed Files Snapshot. expected={expected_snapshot_hash} actual={snapshot_sha256 or '<missing>'}"
        )
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    if evidence_type == "github-pr":
        repository = evidence.get("repository", "").strip()
        pull_number = evidence.get("pr number", "").strip()
        api_base_url = evidence.get("api base url", "").strip()
        if not repository or not pull_number:
            errors.append(f"{code_path.name}: github-pr ## Diff Evidence requires non-empty Repository, PR Number, Changed Files Snapshot, and Snapshot SHA256")
            return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
        provider_files, provider_error = collect_github_pr_files(repository, pull_number, api_base_url)
        if provider_error:
            errors.append(f"{code_path.name}: github-pr evidence fetch failed for {repository} PR#{pull_number}: {provider_error}")
            return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
        if provider_files != snapshot_files:
            errors.append(
                f"{code_path.name}: Changed Files Snapshot does not match github-pr provider response. snapshot={sorted(snapshot_files)} provider={sorted(provider_files)}"
            )
            return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
        return compare_reconstructed_scope(plan_path, code_path, provider_files, "github-pr scope check")

    if not repo_root:
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    base_ref = evidence.get("base ref", "").strip()
    head_ref = evidence.get("head ref", "").strip()
    base_commit = evidence.get("base commit", "").strip()
    head_commit = evidence.get("head commit", "").strip()
    diff_command = evidence.get("diff command", "").strip()
    if not base_commit or not head_commit or not diff_command:
        errors.append(
            f"{code_path.name}: commit-range ## Diff Evidence requires non-empty Base Commit, Head Commit, Diff Command, Changed Files Snapshot, and Snapshot SHA256"
        )
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    if not COMMIT_SHA_PATTERN.match(base_commit) or not COMMIT_SHA_PATTERN.match(head_commit):
        errors.append(f"{code_path.name}: Base Commit and Head Commit must be full 40-character git commit SHAs")
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    archive_files, archive_rel, archive_error = load_archive_snapshot(repo_root, code_path, evidence, snapshot_files)
    if archive_error:
        errors.append(archive_error)
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    if base_ref:
        resolved_base, base_error = resolve_git_revision_commit(repo_root, base_ref)
        if base_error:
            warnings.append(f"{code_path.name}: Base Ref '{base_ref}' no longer resolves to a commit: {base_error}")
        elif resolved_base.lower() != base_commit.lower():
            warnings.append(
                f"{code_path.name}: Base Ref '{base_ref}' resolves to {resolved_base}, not pinned Base Commit {base_commit}"
            )
    if head_ref:
        resolved_head, head_error = resolve_git_revision_commit(repo_root, head_ref)
        if head_error:
            warnings.append(f"{code_path.name}: Head Ref '{head_ref}' no longer resolves to a commit: {head_error}")
        elif resolved_head.lower() != head_commit.lower():
            warnings.append(
                f"{code_path.name}: Head Ref '{head_ref}' resolves to {resolved_head}, not pinned Head Commit {head_commit}"
            )
    diff_changed, diff_error = collect_git_diff_range_files(repo_root, base_commit, head_commit)
    scope_label = "commit-range scope check"
    if diff_error:
        if archive_files is None or archive_rel is None:
            errors.append(f"{code_path.name}: commit-range diff replay failed for {base_commit}..{head_commit}: {diff_error}")
            return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
        warnings.append(
            f"{code_path.name}: commit-range diff replay failed for {base_commit}..{head_commit}; using archive fallback {archive_rel}: {diff_error}"
        )
        diff_changed = archive_files
        scope_label = "commit-range archive fallback"
    if diff_changed != snapshot_files:
        mismatch_source = f"archive fallback {archive_rel}" if scope_label == "commit-range archive fallback" and archive_rel else "replayed commit-range diff"
        errors.append(
            f"{code_path.name}: Changed Files Snapshot does not match {mismatch_source}. snapshot={sorted(snapshot_files)} replay={sorted(diff_changed)}"
        )
        return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)
    scope_result = compare_reconstructed_scope(plan_path, code_path, diff_changed, scope_label)
    warnings.extend(scope_result.warnings)
    waiver_candidate_errors.extend(scope_result.waiver_candidate_errors)
    drift_files.update(scope_result.drift_files)
    return ScopeCheckResult(errors, waiver_candidate_errors, warnings, drift_files)


def validate_scope_drift_waiver(artifacts_root: Path, task_id: str, drift_files: Set[str]) -> ValidationResult:
    if not drift_files:
        return ValidationResult([], [])
    decision_paths = find_artifact_paths(artifacts_root, task_id, "decision")
    if not decision_paths:
        return ValidationResult(
            [
                f"--allow-scope-drift requires a decision artifact with ## Guard Exception covering drift files: {sorted(drift_files)}"
            ],
            [],
        )
    for path in decision_paths:
        section = extract_section(load_text(path), "Guard Exception")
        if not section:
            continue
        fields = parse_key_value_section(section)
        if fields.get("exception type", "").strip().lower() != SCOPE_WAIVER_EXCEPTION_TYPE:
            continue
        waived_files = parse_csv_file_tokens(fields.get("scope files", ""))
        justification = fields.get("justification", "").strip()
        if justification and drift_files.issubset(waived_files):
            return ValidationResult([], [f"{path.name}: explicit allow-scope-drift waiver applied for {sorted(drift_files)}"])
    return ValidationResult(
        [
            f"--allow-scope-drift requires a decision artifact with ## Guard Exception / Exception Type: allow-scope-drift / Scope Files covering drift files: {sorted(drift_files)}"
        ],
        [],
    )


def validate_task_id(task_id: str) -> List[str]:
    return [] if TASK_ID_PATTERN.match(task_id) else [f"Invalid task id '{task_id}'. Expected format like TASK-001."]


def validate_taipei_timestamp(value: str, label: str) -> List[str]:
    return [] if TAIPEI_TIMESTAMP_PATTERN.match(str(value).strip()) else [f"{label} must be Asia/Taipei ISO 8601 with +08:00, got '{value}'"]


def resolve_status_state(status: dict) -> Optional[str]:
    raw_state = str(status.get("state", "")).strip()
    if raw_state:
        return raw_state
    raw_legacy_state = str(status.get("current_state", "")).strip()
    if not raw_legacy_state:
        return None
    return LEGACY_STATE_ALIASES.get(raw_legacy_state, raw_legacy_state)


def status_uses_legacy_schema(status: dict) -> bool:
    return "state" not in status and "current_state" in status


def append_auto_upgrade_log(status_path: Path, status: dict, reason: str) -> None:
    timestamp = current_taipei_timestamp()
    log_entries = status.setdefault("auto_upgrade_log", [])
    if not isinstance(log_entries, list):
        log_entries = []
        status["auto_upgrade_log"] = log_entries
    log_entries.append(
        {
            "timestamp": timestamp,
            "reason": reason,
            "from_mode": AUTO_CLASSIFY_LIGHTWEIGHT,
            "to_mode": AUTO_CLASSIFY_FULL,
        }
    )
    status["last_updated"] = timestamp
    write_json(status_path, status)


def resolve_validation_mode(artifacts_root: Path, task_id: str, auto_classify: bool) -> AutoClassificationResult:
    if not auto_classify or not TASK_ID_PATTERN.match(task_id):
        return AutoClassificationResult(AUTO_CLASSIFY_FULL, [])

    status_path = artifact_path(artifacts_root, task_id, "status")
    status = load_json(status_path)
    task_path = artifact_path(artifacts_root, task_id, "task")
    task_text = load_text(task_path)
    plan_path = artifact_path(artifacts_root, task_id, "plan")
    plan_exists = plan_path.exists()
    state = resolve_status_state(status)
    warnings: List[str] = []
    validation_mode = AUTO_CLASSIFY_FULL

    if task_requests_lightweight(task_text):
        validation_mode = AUTO_CLASSIFY_LIGHTWEIGHT
    elif not plan_exists and state in {"drafted", "researched"}:
        validation_mode = AUTO_CLASSIFY_LIGHTWEIGHT
        warnings.append(f"lightweight candidate: no plan artifact and state is {state}")

    upgrade_reasons: List[str] = []
    if validation_mode == AUTO_CLASSIFY_LIGHTWEIGHT:
        if task_declares_premortem(task_text):
            upgrade_reasons.append("task artifact declares premortem")
        if plan_exists and plan_has_non_empty_risks(load_text(plan_path)):
            upgrade_reasons.append("plan artifact contains non-empty ## Risks")
    if upgrade_reasons:
        reason = "; ".join(upgrade_reasons)
        append_auto_upgrade_log(status_path, status, reason)
        warnings.append(f"[AUTO-UPGRADE] lightweight classification escalated to full: {reason}")
        validation_mode = AUTO_CLASSIFY_FULL

    return AutoClassificationResult(validation_mode, warnings)


def research_citations_are_blocking(status: dict) -> bool:
    return True


def validate_research_citations(task_id: str, artifact_path: Path) -> List[ValidationError]:
    findings: List[ValidationError] = []
    section = extract_section(load_text(artifact_path), "Sources")
    if not section:
        return [ValidationError("CRITICAL", "missing required ## Sources section")]
    source_lines = [line.strip() for line in section.splitlines() if line.strip()]
    if not source_lines or source_lines == ["None"]:
        return [ValidationError("CRITICAL", "## Sources must contain at least 2 entries")]
    if len(source_lines) < 2:
        findings.append(ValidationError("MAJOR", "## Sources must contain at least 2 entries"))
    for line in source_lines:
        if RESEARCH_SOURCES_ENTRY_PATTERN.match(line):
            continue
        if RESEARCH_SOURCES_URL_PATTERN.search(line):
            if RESEARCH_SOURCES_PARTIAL_DATE_PATTERN.search(line) or "retrieved" in line:
                findings.append(
                    ValidationError(
                        "MINOR",
                        f"source entry must end with '(YYYY-MM-DD retrieved)': {line}",
                    )
                )
            else:
                findings.append(
                    ValidationError(
                        "MAJOR",
                        f"source entry must match '[N] Author/Org. \"Title.\" URL (YYYY-MM-DD retrieved)': {line}",
                    )
                )
            continue
        findings.append(
            ValidationError(
                "MAJOR",
                f"source entry must match '[N] Author/Org. \"Title.\" URL (YYYY-MM-DD retrieved)': {line}",
            )
        )
    return findings


def validate_status_schema(status: dict, expected_task_id: str) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    if status.get("task_id") != expected_task_id:
        errors.append(f"status.json task_id mismatch. Expected {expected_task_id}, got {status.get('task_id')}")
    state = resolve_status_state(status)
    if state not in VALID_STATES:
        errors.append(f"Invalid state: {state!r}")
    if status_uses_legacy_schema(status):
        warnings.append("legacy status schema detected; run reconcile to promote state/current_owner/next_agent profile fields")
        required_keys = {"task_id", "current_state", "owner", "last_updated"}
        missing = required_keys - set(status.keys())
        if missing:
            errors.append(f"status.json missing required keys: {sorted(missing)}")
        if not str(status.get("owner", "")).strip():
            errors.append("status.json field 'owner' must be non-empty")
        artifacts_value = status.get("artifacts")
        if artifacts_value is not None and not isinstance(artifacts_value, dict):
            errors.append("status.json field 'artifacts' must be an object when present")
        blockers = status.get("blockers", [])
        if state == "blocked":
            if not isinstance(blockers, list) or not any(str(item).strip() for item in blockers):
                errors.append("legacy blocked state requires non-empty blockers")
        elif isinstance(blockers, list) and any(str(item).strip() for item in blockers):
            warnings.append("blockers is non-empty while current_state is not blocked")
    else:
        required_keys = {
            "task_id",
            "state",
            "current_owner",
            "next_agent",
            "required_artifacts",
            "available_artifacts",
            "missing_artifacts",
            "blocked_reason",
            "last_updated",
        }
        missing = required_keys - set(status.keys())
        if missing:
            errors.append(f"status.json missing required keys: {sorted(missing)}")
        for key in ("required_artifacts", "available_artifacts", "missing_artifacts"):
            value = status.get(key)
            if not isinstance(value, list):
                errors.append(f"status.json field '{key}' must be a list")
                continue
            unknown = sorted(set(value) - set(ARTIFACT_TYPES))
            if unknown:
                errors.append(f"status.json field '{key}' contains unknown artifacts: {unknown}")

        assurance_raw = status.get("assurance_level", "")
        if assurance_raw in {"", None}:
            errors.append(
                f"status.json field 'assurance_level' is required but missing or empty. "
                f"Allowed values: {list(ASSURANCE_LEVELS)}."
            )
        else:
            assurance_level = str(assurance_raw).strip().lower()
            if assurance_level not in ASSURANCE_LEVELS:
                errors.append(
                    f"status.json field 'assurance_level' must be one of {list(ASSURANCE_LEVELS)}, "
                    f"got '{status.get('assurance_level')}'. "
                    "Unknown assurance_level is a schema error. "
                    "Use legacy compatibility mode only if explicitly authorized."
                )

        project_adapter_raw = status.get("project_adapter", "")
        if project_adapter_raw in {"", None}:
            warnings.append(f"status.json missing 'project_adapter'; defaulting to '{DEFAULT_PROJECT_ADAPTER}' until reconcile")
        else:
            project_adapter = str(project_adapter_raw).strip().lower()
            if project_adapter not in PROJECT_ADAPTERS:
                errors.append(
                    f"status.json field 'project_adapter' must be one of {list(PROJECT_ADAPTERS)}, got '{status.get('project_adapter')}'"
                )

        open_debts = status.get("open_verification_debts")
        if open_debts is None:
            warnings.append("status.json missing 'open_verification_debts'; defaulting to [] until reconcile")
        elif not isinstance(open_debts, list):
            errors.append("status.json field 'open_verification_debts' must be a list")
        expected_readiness = derive_verification_readiness(
            status.get("assurance_level", DEFAULT_ASSURANCE_LEVEL),
            status.get("project_adapter", DEFAULT_PROJECT_ADAPTER),
            state,
            open_debts if isinstance(open_debts, list) else [],
        )
        verification_readiness = status.get("verification_readiness")
        if verification_readiness in {"", None}:
            warnings.append(
                "status.json missing 'verification_readiness'; "
                f"defaulting to '{expected_readiness}' until reconcile"
            )
        else:
            readiness_value = str(verification_readiness).strip().lower()
            if readiness_value not in VERIFICATION_READINESS_STATES:
                errors.append(
                    "status.json field 'verification_readiness' must be one of "
                    f"{list(VERIFICATION_READINESS_STATES)}, got '{verification_readiness}'"
                )
            elif readiness_value != expected_readiness:
                warnings.append(
                    "verification_readiness mismatch. "
                    f"status.json={readiness_value} computed={expected_readiness}"
                )

        if state == "blocked" and not str(status.get("blocked_reason", "")).strip():
            errors.append("blocked state requires non-empty blocked_reason")
        if state != "blocked" and str(status.get("blocked_reason", "")).strip():
            warnings.append("blocked_reason is non-empty while state is not blocked")
        decision_waivers = status.get("decision_waivers")
        if decision_waivers is not None:
            if not isinstance(decision_waivers, list):
                errors.append("status.json field 'decision_waivers' must be a list")
            else:
                now = datetime.now(TAIPEI_TZ)
                required_waiver_fields = ("gate", "reason", "approver", "expires")
                for index, entry in enumerate(decision_waivers, start=1):
                    if not isinstance(entry, dict):
                        errors.append(f"status.json decision_waivers[{index}] must be an object")
                        continue
                    missing_fields = [
                        field_name
                        for field_name in required_waiver_fields
                        if not str(entry.get(field_name, "")).strip()
                    ]
                    if missing_fields:
                        errors.append(
                            f"status.json decision_waivers[{index}] missing required fields: {missing_fields}"
                        )
                        continue
                    gate = str(entry.get("gate", "")).strip()
                    if gate not in DECISION_WAIVER_GATES:
                        errors.append(
                            f"status.json decision_waivers[{index}] gate must be one of {sorted(DECISION_WAIVER_GATES)}, got '{gate}'"
                        )
                    expires = str(entry.get("expires", "")).strip()
                    errors.extend(
                        validate_taipei_timestamp(expires, f"status.json decision_waivers[{index}] expires")
                    )
                    expires_dt = parse_taipei_datetime(expires)
                    if expires_dt is not None and expires_dt <= now:
                        errors.append(
                            f"status.json decision_waivers[{index}] waiver expired for {gate} at {expires}"
                        )
        auto_upgrade_log = status.get("auto_upgrade_log")
        if auto_upgrade_log is not None:
            if not isinstance(auto_upgrade_log, list):
                errors.append("status.json field 'auto_upgrade_log' must be a list")
            else:
                for index, entry in enumerate(auto_upgrade_log, start=1):
                    if not isinstance(entry, dict):
                        errors.append(f"status.json auto_upgrade_log[{index}] must be an object")
                        continue
                    for field_name in ("timestamp", "reason", "from_mode", "to_mode"):
                        if not str(entry.get(field_name, "")).strip():
                            errors.append(
                                f"status.json auto_upgrade_log[{index}] missing required field '{field_name}'"
                            )
                    timestamp = str(entry.get("timestamp", "")).strip()
                    if timestamp:
                        errors.extend(
                            validate_taipei_timestamp(
                                timestamp,
                                f"status.json auto_upgrade_log[{index}] timestamp",
                            )
                        )
    errors.extend(validate_taipei_timestamp(status.get("last_updated", ""), "status.json last_updated"))
    return ValidationResult(errors, warnings)


def validate_research_artifact(task_id: str, text: str, path: Path) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    if "## Recommendation" in text:
        errors.append(f"{path.name}: research artifact must be fact-only and must not contain ## Recommendation")
    confirmed_items = parse_list_items(extract_section(text, "Confirmed Facts"))
    if not confirmed_items:
        errors.append(f"{path.name}: ## Confirmed Facts must contain at least one concrete claim")
    for item in confirmed_items:
        if "UNVERIFIED:" in item:
            errors.append(f"{path.name}: UNVERIFIED item found in ## Confirmed Facts")
        if not CITATION_PATTERN.search(item):
            errors.append(f"{path.name}: each Confirmed Facts item must include an inline citation")
    for item in parse_list_items(extract_section(text, "Uncertain Items")):
        if not item.startswith("UNVERIFIED:"):
            errors.append(f"{path.name}: each Uncertain Items entry must start with UNVERIFIED:")
    constraints = extract_section(text, "Constraints For Implementation")
    if not constraints or constraints.lower() == "none":
        errors.append(f"{path.name}: ## Constraints For Implementation must not be empty")
    status_path = artifact_path(path.parents[1], task_id, "status")
    status_payload = load_json(status_path)
    citation_findings = validate_research_citations(task_id, path)
    target = errors if research_citations_are_blocking(status_payload) else warnings
    for finding in citation_findings:
        target.append(f"{path.name}: [{finding.severity}] {finding.message}")
    for mixed_entry in detect_mixed_github_sources(text):
        warnings.append(
            f"{path.name}: possible mixed truth source detected for repo '{mixed_entry}' (upstream/fork may be mixed)"
        )
    return ValidationResult(errors, warnings)


def validate_improvement_artifact(text: str, path: Path, task_id: str) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    source_match = re.search(r"^- Source Task:\s*(.+)$", text, re.MULTILINE)
    if not source_match or not source_match.group(1).strip():
        errors.append(f"{path.name}: missing non-empty Source Task field")
    elif task_id not in source_match.group(1):
        errors.append(f"{path.name}: Source Task must reference {task_id}")
    trigger_match = re.search(r"^- Trigger Type:\s*(.+)$", text, re.MULTILINE)
    if not trigger_match or trigger_match.group(1).strip() not in {"failure", "blocked", "inefficiency", "guard miss"}:
        errors.append(f"{path.name}: Trigger Type must be one of failure / blocked / inefficiency / guard miss")
    profile_match = re.search(r"^- Improvement Profile:\s*(.+)$", text, re.MULTILINE)
    if profile_match:
        profile = profile_match.group(1).strip().lower()
        if profile not in IMPROVEMENT_PROFILES:
            errors.append(f"{path.name}: Improvement Profile must be one of {list(IMPROVEMENT_PROFILES)}")
    else:
        warnings.append(f"{path.name}: missing Improvement Profile; inferred from Trigger Type for backward compatibility")
    for heading in ("5. Preventive Action (System Level)", "6. Validation", "8. Final Rule", "9. Status"):
        value = extract_section(text, heading)
        if not value or value.lower() == "none":
            errors.append(f"{path.name}: ## {heading} must not be empty")
    return ValidationResult(errors, warnings)


def _extract_v2_frontmatter_decision_class(text: str) -> str:
    """Return decision_class from YAML frontmatter at the top of a v2 decision
    artifact, or '' when no frontmatter or no decision_class line is found.

    See docs/artifact_schema.md §5.13 for the v2 governance extension.
    """
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    if end < 0:
        return ""
    frontmatter = text[4:end]
    match = re.search(r"^decision_class:\s*(.+)$", frontmatter, re.MULTILINE)
    return match.group(1).strip() if match else ""


def validate_decision_artifact(text: str, path: Path) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    decision_class = extract_single_line_section(text, "Decision Class")
    if not decision_class:
        decision_class = _extract_v2_frontmatter_decision_class(text)
    is_governance = is_governance_decision_class(decision_class) if decision_class else False
    if decision_class:
        if decision_class.lower() not in DECISION_CLASSES and not is_governance:
            errors.append(
                f"{path.name}: Decision Class must be one of {list(DECISION_CLASSES)} "
                f"or a governance-* family value (see docs/artifact_schema.md §5.13)"
            )
    else:
        warnings.append(f"{path.name}: missing ## Decision Class; legacy decision artifact kept for compatibility")
    affected_gate = extract_single_line_section(text, "Affected Gate")
    if affected_gate:
        if is_governance:
            # v2 governance decisions allow free-form Affected Gate (including 'None' for snapshot-only records).
            pass
        elif not DECISION_GATE_PATTERN.match(affected_gate):
            errors.append(f"{path.name}: Affected Gate must use Gate_A..Gate_E format")
    elif decision_class and not is_governance:
        warnings.append(f"{path.name}: missing ## Affected Gate")
    expiry = extract_single_line_section(text, "Expiry")
    if expiry and expiry.strip().lower() not in {"none", "n/a"}:
        if is_governance:
            # v2 governance decisions allow commit-anchored or plan-version-anchored Expiry prose.
            pass
        else:
            errors.extend(validate_taipei_timestamp(expiry, f"{path.name} Expiry"))
    linked_artifacts = extract_section(text, "Linked Artifacts")
    if decision_class and not linked_artifacts:
        # v2 governance decisions may track linked artifacts under ## Evidence Refs
        # or ## Follow Up instead of ## Linked Artifacts. See docs/artifact_schema.md §5.13.
        if is_governance and (extract_section(text, "Evidence Refs") or extract_section(text, "Follow Up")):
            pass
        else:
            warnings.append(f"{path.name}: missing ## Linked Artifacts")
    return ValidationResult(errors, warnings)


def validate_code_mapping_to_plan(text: str, path: Path) -> ValidationResult:
    section = extract_section(text, "Mapping To Plan")
    if not section:
        return ValidationResult([], [])
    bullet_lines = [line.strip() for line in section.splitlines() if line.strip().startswith("- ")]
    if not any(line.startswith("- plan_item:") for line in bullet_lines):
        return ValidationResult([], [])
    warnings: List[str] = []
    for line in bullet_lines:
        if MAPPING_TO_PLAN_ENTRY_PATTERN.match(line):
            continue
        warnings.append(
            f"{path.name}: Mapping To Plan entry must match "
            "\"- plan_item: {N.N}, status: done|partial|skipped, evidence: \\\"...\\\"\": "
            f"{line}"
        )
    return ValidationResult([], warnings)


def _split_inline_checklist_fields(value: str) -> Dict[str, str]:
    """Split 'first_value, key2: value2, key3: value3' into separate fields.

    Used for v2 verify artifacts that pack multiple checklist fields onto one
    line (e.g. '- result: verified, reviewer: arcobaleno, timestamp: ...').
    Recognises only fields named in POLICY_STRUCTURED_CHECKLIST_FIELDS so that
    timestamp values containing ':' are not misparsed.
    """
    field_alt = "|".join(re.escape(f) for f in POLICY_STRUCTURED_CHECKLIST_FIELDS)
    pattern = re.compile(rf",\s*({field_alt})\s*:\s*", re.IGNORECASE)
    matches = list(pattern.finditer(value))
    if not matches:
        return {}
    parsed: Dict[str, str] = {"__first__": value[:matches[0].start()].strip()}
    for index, match in enumerate(matches):
        key = match.group(1).lower()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(value)
        parsed[key] = value[match.end():end].strip()
    return parsed


def parse_structured_checklist_fields(block_text: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    ac_inline = re.compile(r"^- \[[ x]\]\s+(\S+):\s*(.*)$")
    for raw_line in block_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        ac_match = ac_inline.match(line)
        if ac_match:
            criterion_text = ac_match.group(2).strip()
            if criterion_text:
                fields.setdefault("criterion", criterion_text)
                fields.setdefault("__inline_criterion__", "true")
            continue
        match = re.match(r"^- \*\*([^*]+)\*\*:\s*(.+)$", line)
        if not match:
            match = re.match(r"^- ([^:]+):\s*(.+)$", line)
        if not match:
            continue
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        inline = _split_inline_checklist_fields(value) if key in POLICY_STRUCTURED_CHECKLIST_FIELDS else {}
        if inline:
            fields[key] = inline.pop("__first__", value)
            for sub_key, sub_value in inline.items():
                fields.setdefault(sub_key, sub_value)
        else:
            fields[key] = value
    return fields


def parse_verify_checklist_items(section_text: str) -> List[Dict[str, str]]:
    """Split a verify ## Acceptance Criteria Checklist section into structured items.

    The preferred boundary is a checklist item header line, line-anchored, of
    the form '- [ ] AC-N:' or '- [x] AC-N:' (or any '- [ ] ID:' style). This
    correctly groups multi-paragraph evidence values that v2 governance verify
    artifacts produce. When no such header is present, the splitter preserves
    the v1 blank-line-boundary semantics so older verify artifacts continue
    to parse unchanged.

    See docs/artifact_schema.md §5.13 for the v2 multi-paragraph evidence rule.
    """
    items: List[Dict[str, str]] = []
    if not section_text:
        return items
    item_start = re.compile(r"^- \[[ x]\]\s+\S+:", re.MULTILINE)
    starts = [m.start() for m in item_start.finditer(section_text)]
    if starts:
        blocks: List[str] = []
        for index, start in enumerate(starts):
            end = starts[index + 1] if index + 1 < len(starts) else len(section_text)
            block = section_text[start:end].strip()
            if block:
                blocks.append(block)
    else:
        blocks = [block.strip() for block in re.split(r"\n\s*\n", section_text) if block.strip()]
    for block in blocks:
        fields = parse_structured_checklist_fields(block)
        if not fields:
            continue
        if not set(fields).intersection({"criterion", "method", "reviewer", "timestamp"}):
            continue
        items.append(fields)
    return items


def collect_verify_contract(
    text: str,
    assurance_level: str = DEFAULT_ASSURANCE_LEVEL,
    project_adapter: str = DEFAULT_PROJECT_ADAPTER,
    state: str = "done",
) -> Dict[str, object]:
    policy = resolve_verification_policy(assurance_level, project_adapter)
    section = extract_section(text, "Acceptance Criteria Checklist")
    items = parse_verify_checklist_items(section)
    open_debts: List[str] = []
    for fields in items:
        result_value = str(fields.get("result", "")).strip().lower()
        criterion = str(fields.get("criterion", "")).strip() or "<unnamed criterion>"
        if result_value in policy["status_debt_results"]:
            open_debts.append(f"{result_value}: {criterion}")
    declared_maturity = extract_single_line_section(text, "Overall Maturity").strip().lower()
    return {
        "items": items,
        "open_verification_debts": open_debts,
        "computed_readiness": derive_verification_readiness(
            assurance_level,
            project_adapter,
            state,
            open_debts,
        ),
        "declared_maturity": declared_maturity,
        "pass_fail_result": extract_single_line_section(text, "Pass Fail Result").strip().lower(),
    }


def validate_verify_checklist_schema(
    text: str,
    path: Path,
    assurance_level: str = DEFAULT_ASSURANCE_LEVEL,
    project_adapter: str = DEFAULT_PROJECT_ADAPTER,
) -> ValidationResult:
    policy = resolve_verification_policy(assurance_level, project_adapter)
    section = extract_section(text, "Acceptance Criteria Checklist")
    if not section:
        return ValidationResult([], [])
    errors: List[str] = []
    warnings: List[str] = []
    verify_contract = collect_verify_contract(text, assurance_level, project_adapter)
    checklist_items = verify_contract["items"]
    structured_count = len(checklist_items)
    required_fields = set(policy["verify_required_fields"])
    required_sections = set(policy["verify_required_sections"])
    allowed_results = set(policy["allowed_results"])
    disallowed_results = set(policy["disallowed_results"])
    allowed_reason_codes = set(policy["allowed_reason_codes"])
    missing_target = errors if assurance_level in {"mvp", "production"} else warnings

    for fields in checklist_items:
        item_label = fields.get("criterion") or fields.get("method") or "<unnamed criterion>"
        # v2 inline-light AC items carry the criterion on the '- [x] AC-N:' header
        # itself; the criterion line is the evidence anchor and method/evidence
        # are optional supplements rather than required separate lines. Items
        # that don't use the AC-inline form continue to require the full
        # configured field set. See docs/artifact_schema.md §5.13.
        is_inline_light = fields.get("__inline_criterion__") == "true"
        effective_required_fields = (
            required_fields - {"method", "evidence"} if is_inline_light else required_fields
        )
        for field in sorted(effective_required_fields):
            if not fields.get(field):
                missing_target.append(
                    f"{path.name}: Acceptance Criteria Checklist structured item '{item_label}' missing {field} field"
                )
        result_value = str(fields.get("result", "")).strip().lower()
        if result_value and result_value not in allowed_results:
            errors.append(
                f"{path.name}: Acceptance Criteria Checklist structured item '{item_label}' result must be one of {list(VERIFICATION_ITEM_RESULTS)}"
            )
        if result_value in disallowed_results:
            errors.append(
                f"{path.name}: Acceptance Criteria Checklist structured item '{item_label}' result '{result_value}' is not allowed for assurance level '{policy['assurance_level']}'"
            )
        if result_value in NON_VERIFIED_RESULTS and not (fields.get("decision_ref") or fields.get("reason_code")):
            target = errors if assurance_level in {"mvp", "production"} else warnings
            target.append(
                f"{path.name}: Acceptance Criteria Checklist structured item '{item_label}' with result '{result_value}' requires decision_ref or reason_code"
            )
        reason_code = str(fields.get("reason_code", "")).strip().upper()
        if reason_code and reason_code not in allowed_reason_codes:
            errors.append(
                f"{path.name}: Acceptance Criteria Checklist structured item '{item_label}' reason_code must be one of {sorted(allowed_reason_codes or set(VERIFICATION_REASON_CODES))}"
            )
        timestamp_value = fields.get("timestamp")
        if timestamp_value:
            for error in validate_taipei_timestamp(timestamp_value, f"{path.name} checklist timestamp"):
                target = errors if assurance_level == "production" else warnings
                target.append(f"{path.name}: Acceptance Criteria Checklist structured item '{item_label}' has invalid timestamp: {error}")

    if structured_count == 0:
        target = errors if assurance_level in {"mvp", "production"} else warnings
        target.append(
            f"{path.name}: Acceptance Criteria Checklist requires at least one structured checklist item"
        )

    section_checks = {
        "Verification Summary": bool(extract_section(text, "Verification Summary")),
        "Acceptance Criteria Checklist": bool(section),
        "Overall Maturity": bool(extract_single_line_section(text, "Overall Maturity")),
        "Deferred Items": bool(extract_section(text, "Deferred Items")),
        "Decision Refs": bool(extract_section(text, "Decision Refs")),
        "Evidence Refs": bool(extract_section(text, "Evidence Refs")),
        "Pass Fail Result": bool(re.search(r"## Pass Fail Result\s+\n?\s*(pass|fail)\b", text, re.IGNORECASE)),
        "Build Guarantee": bool(extract_section(text, "Build Guarantee")),
    }
    for section_name in sorted(required_sections):
        if section_checks.get(section_name):
            continue
        target = errors if assurance_level in {"mvp", "production"} else warnings
        target.append(f"{path.name}: missing ## {section_name} for assurance level '{policy['assurance_level']}'")

    maturity_value = extract_single_line_section(text, "Overall Maturity").lower()
    if maturity_value and maturity_value not in VERIFICATION_READINESS_STATES:
        errors.append(
            f"{path.name}: Overall Maturity must be one of {list(VERIFICATION_READINESS_STATES)}"
        )
    elif maturity_value and maturity_value != verify_contract["computed_readiness"]:
        warnings.append(
            f"{path.name}: Overall Maturity mismatch. declared={maturity_value} computed={verify_contract['computed_readiness']}"
        )
    pass_fail_result = verify_contract["pass_fail_result"]
    if pass_fail_result == "pass" and verify_contract["open_verification_debts"]:
        errors.append(
            f"{path.name}: Pass Fail Result cannot be 'pass' while checklist contains open verification debts"
        )
    return ValidationResult(errors, warnings)


def validate_markdown_artifact(path: Path, artifact_type: str, task_id: str) -> ValidationResult:
    text = load_text(path)
    errors: List[str] = []
    warnings: List[str] = []
    assurance_level = DEFAULT_ASSURANCE_LEVEL
    project_adapter = DEFAULT_PROJECT_ADAPTER
    if artifact_type in {"plan", "verify", "decision", "improvement"}:
        assurance_level, project_adapter = resolve_artifact_profile(path, task_id)
    elif artifact_type == "task":
        assurance_level = resolve_assurance_level(text)
        project_adapter = resolve_project_adapter(text)
        _task_flags_for_assurance = extract_task_inline_flags(text)
        _raw_task_assurance = (
            _task_flags_for_assurance.get("assurance_level")
            or extract_single_line_section(text, "Assurance Level")
        )
    missing_markers = _required_markers_missing(text, MARKERS[artifact_type])
    if missing_markers:
        errors.append(f"{path.name} missing required markers: {missing_markers}")
    if f"Task ID: {task_id}" not in text:
        errors.append(f"{path.name} missing exact task id marker 'Task ID: {task_id}'")
    owner_match = re.search(r"^- Owner:\s*(.+)$", text, re.MULTILINE)
    if not owner_match or not owner_match.group(1).strip():
        errors.append(f"{path.name} missing non-empty Owner field")
    status_match = re.search(r"^- Status:\s*(.+)$", text, re.MULTILINE)
    if not status_match or not status_match.group(1).strip():
        errors.append(f"{path.name} missing non-empty Status field")
    else:
        status_value = status_match.group(1).strip()
        if status_value not in ARTIFACT_ALLOWED_STATUSES.get(artifact_type, set()):
            errors.append(f"{path.name} has invalid Status '{status_value}' for artifact type '{artifact_type}'")
    updated_match = re.search(r"^- Last Updated:\s*(.+)$", text, re.MULTILINE)
    if not updated_match or not updated_match.group(1).strip():
        errors.append(f"{path.name} missing non-empty Last Updated field")
    else:
        errors.extend(validate_taipei_timestamp(updated_match.group(1).strip(), f"{path.name} Last Updated"))
    if artifact_type == "plan" and not _is_v2_plan(text) and not re.search(r"## Ready For Coding\s+\n?\s*(yes|no)\b", text, re.IGNORECASE):
        errors.append(f"{path.name} does not clearly declare Ready For Coding as yes/no")
    if artifact_type == "verify" and not re.search(r"## Pass Fail Result\s+\n?\s*(pass|fail)\b", text, re.IGNORECASE):
        errors.append(f"{path.name} does not clearly declare Pass Fail Result as pass/fail")
    if artifact_type == "task":
        if "## Assurance Level" not in text:
            errors.append(f"{path.name}: missing ## Assurance Level section; assurance_level must be declared explicitly.")
        elif _raw_task_assurance and str(_raw_task_assurance).strip().lower() not in ASSURANCE_LEVELS:
            errors.append(
                f"{path.name}: Assurance Level '{_raw_task_assurance}' is not a valid assurance level. "
                f"Allowed values: {list(ASSURANCE_LEVELS)}."
            )
        if "## Project Adapter" not in text:
            warnings.append(f"{path.name}: missing ## Project Adapter; defaulting to '{project_adapter}'")
        if project_adapter not in PROJECT_ADAPTERS:
            errors.append(f"{path.name}: invalid Project Adapter '{project_adapter}'")
        _status_path_for_mismatch = companion_artifact_path(path, "status", task_id)
        if _status_path_for_mismatch.exists():
            try:
                _status_data_for_mismatch = load_json(_status_path_for_mismatch)
                _status_assurance_val = str(_status_data_for_mismatch.get("assurance_level", "")).strip().lower()
                _task_assurance_val = str(_raw_task_assurance or "").strip().lower()
                if _status_assurance_val and _task_assurance_val and _status_assurance_val != _task_assurance_val:
                    errors.append(
                        f"{path.name}: assurance_level mismatch: task.md declares '{_task_assurance_val}' "
                        f"but status.json declares '{_status_assurance_val}'. Both must match."
                    )
            except GuardError:
                pass
    if (
        artifact_type == "plan"
        and assurance_level in {"mvp", "production"}
        and "## Verification Obligations" not in text
        and not _is_v2_plan(text)
    ):
        errors.append(f"{path.name}: missing ## Verification Obligations for assurance level '{assurance_level}'")
    if artifact_type == "research":
        result = validate_research_artifact(task_id, text, path)
        errors.extend(result.errors)
        warnings.extend(result.warnings)
    if artifact_type == "code":
        result = validate_code_mapping_to_plan(text, path)
        warnings.extend(result.warnings)
    if artifact_type == "verify":
        result = validate_verify_checklist_schema(
            text,
            path,
            assurance_level=assurance_level,
            project_adapter=project_adapter,
        )
        errors.extend(result.errors)
        warnings.extend(result.warnings)
    if artifact_type == "decision":
        result = validate_decision_artifact(text, path)
        errors.extend(result.errors)
        warnings.extend(result.warnings)
    if artifact_type == "improvement":
        result = validate_improvement_artifact(text, path, task_id)
        errors.extend(result.errors)
        warnings.extend(result.warnings)
    return ValidationResult(errors, warnings)


def verify_result_is_pass(verify_path: Path) -> bool:
    match = re.search(r"## Pass Fail Result\s+\n?\s*(pass|fail)\b", load_text(verify_path), re.IGNORECASE)
    return bool(match and match.group(1).lower() == "pass")


def plan_ready_for_coding(plan_path: Path) -> bool:
    match = re.search(r"## Ready For Coding\s+\n?\s*(yes|no)\b", load_text(plan_path), re.IGNORECASE)
    return bool(match and match.group(1).lower() == "yes")


def extract_task_title(task_path: Optional[Path]) -> str:
    if not task_path or not task_path.exists():
        return ""
    first_line = load_text(task_path).splitlines()[0].strip()
    match = re.match(r"^#\s*Task:\s*(.+)$", first_line)
    return match.group(1).strip() if match else ""


def classify_premortem_policy(task_path: Optional[Path]) -> PremortemPolicy:
    task_title = extract_task_title(task_path)
    for policy in PREMORTEM_POLICIES:
        if policy.keyword_regex == "(default)":
            continue
        pattern = PREMORTEM_POLICY_PATTERNS[policy.task_type]
        if pattern.search(task_title):
            return policy
    return PREMORTEM_POLICIES[-1]


def task_is_high_risk(task_path: Optional[Path], plan_text: str) -> bool:
    task_text = load_text(task_path) if task_path and task_path.exists() else ""
    haystack = f"{task_text}\n{plan_text}".lower()
    return any(keyword in haystack for keyword in HIGH_RISK_KEYWORDS)


def validate_premortem(plan_path: Path, task_path: Optional[Path]) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    text = load_text(plan_path)
    risks_text = extract_section(text, "Risks")
    if not risks_text:
        errors.append(f"{plan_path.name}: premortem check failed — ## Risks section not found")
        return ValidationResult(errors, warnings)
    if risks_text.lower() in ("none", "n/a", "low risk", ""):
        errors.append(f"{plan_path.name}: premortem check failed — ## Risks section is empty or trivially dismissed")
        return ValidationResult(errors, warnings)
    policy = classify_premortem_policy(task_path)
    risk_count = len(set(re.findall(r"\bR(\d+)\b", risks_text)))
    if risk_count < policy.min_risks:
        errors.append(
            f"{plan_path.name}: premortem task_type='{policy.task_type}' requires at least "
            f"{policy.min_risks} numbered risks (R1, R2, ...), found {risk_count}"
        )
    for field in PREMORTEM_REQUIRED_FIELDS:
        if field not in risks_text:
            errors.append(f"{plan_path.name}: premortem missing required field '{field}'")
    severity_values = re.findall(r"Severity:\s*(.+)", risks_text)
    for severity in severity_values:
        if severity.strip().lower() not in ("blocking", "non-blocking"):
            errors.append(f"{plan_path.name}: premortem Severity must be 'blocking' or 'non-blocking', got '{severity.strip()}'")
    blocking_count = sum(1 for value in severity_values if value.strip().lower() == "blocking")
    if blocking_count < policy.min_critical:
        errors.append(
            f"{plan_path.name}: premortem task_type='{policy.task_type}' requires at least "
            f"{policy.min_critical} blocking risks, found {blocking_count}"
        )
    elif policy.min_critical == 0 and blocking_count == 0 and task_is_high_risk(task_path, text):
        warnings.append(f"{plan_path.name}: high-risk signals detected but task_type='{policy.task_type}' does not require blocking risk")
    for phrase in PREMORTEM_BANNED_PHRASES:
        if phrase in risks_text:
            warnings.append(f"{plan_path.name}: premortem contains potentially vague phrase '{phrase}' — ensure it has concrete trigger/detection/mitigation")
    return ValidationResult(errors, warnings)


def compute_existing_artifacts(artifacts_root: Path, task_id: str) -> Set[str]:
    return {artifact_type for artifact_type in ARTIFACT_DIRS if find_artifact_paths(artifacts_root, task_id, artifact_type)}


def state_required_artifacts(
    state: str,
    existing: Set[str],
    assurance_level: str = DEFAULT_ASSURANCE_LEVEL,
    project_adapter: str = DEFAULT_PROJECT_ADAPTER,
    validation_mode: str = AUTO_CLASSIFY_FULL,
) -> Set[str]:
    if assurance_level in {AUTO_CLASSIFY_FULL, AUTO_CLASSIFY_LIGHTWEIGHT} and project_adapter == DEFAULT_PROJECT_ADAPTER:
        assurance_level = DEFAULT_ASSURANCE_LEVEL
    policy = resolve_verification_policy(assurance_level, project_adapter)
    return set(policy["required_artifacts_by_state"].get(state, set()))


def infer_state_from_artifacts(
    existing: Set[str],
    assurance_level: str = DEFAULT_ASSURANCE_LEVEL,
    project_adapter: str = DEFAULT_PROJECT_ADAPTER,
    validation_mode: str = AUTO_CLASSIFY_FULL,
) -> str:
    for candidate in reversed(STATE_ORDER):
        if candidate == "blocked":
            continue
        if state_required_artifacts(
            candidate,
            existing,
            assurance_level=assurance_level,
            project_adapter=project_adapter,
            validation_mode=validation_mode,
        ).issubset(existing):
            return candidate
    return "drafted"


def default_next_agent_for_state(state: str) -> str:
    return BLOCKED_STATUS_NEXT_AGENT if state == "blocked" else DEFAULT_STATUS_NEXT_AGENT


def build_reconcile_defaults(artifacts_root: Path, task_id: str, status: dict) -> Tuple[Dict[str, object], List[str]]:
    existing = compute_existing_artifacts(artifacts_root, task_id)
    task_path = artifact_path(artifacts_root, task_id, "task")
    task_text = load_text(task_path) if task_path.exists() else ""
    assurance_level = resolve_assurance_level(task_text, status)
    project_adapter = resolve_project_adapter(task_text, status)
    inferred_state = infer_state_from_artifacts(existing, assurance_level=assurance_level, project_adapter=project_adapter)
    warnings: List[str] = []
    defaults: Dict[str, object] = {
        "task_id": task_id,
        "available_artifacts": sorted(existing),
        "last_updated": current_taipei_timestamp(),
        "assurance_level": assurance_level,
        "project_adapter": project_adapter,
        "open_verification_debts": [],
        "verification_readiness": derive_verification_readiness(assurance_level, project_adapter, inferred_state, []),
    }
    verify_path = artifact_path(artifacts_root, task_id, "verify")
    if verify_path.exists():
        verify_contract = collect_verify_contract(
            load_text(verify_path),
            assurance_level=assurance_level,
            project_adapter=project_adapter,
            state=inferred_state,
        )
        defaults["open_verification_debts"] = verify_contract["open_verification_debts"]
        defaults["verification_readiness"] = verify_contract["computed_readiness"]
    current_state = resolve_status_state(status)
    effective_state = inferred_state
    if current_state:
        if current_state not in VALID_STATES:
            warnings.append(
                f"reconcile: status.json field 'state' has invalid value '{current_state}' while artifacts imply '{inferred_state}'"
            )
            effective_state = inferred_state
        elif current_state != inferred_state:
            warnings.append(
                f"reconcile: state conflict detected. status.json='{current_state}' but artifacts imply '{inferred_state}'"
            )
            effective_state = None
        else:
            effective_state = current_state
    defaults["state"] = inferred_state
    if effective_state:
        required = sorted(
            state_required_artifacts(
                effective_state,
                existing,
                assurance_level=assurance_level,
                project_adapter=project_adapter,
            )
        )
        defaults["required_artifacts"] = required
        defaults["missing_artifacts"] = sorted(set(required) - existing)
        defaults["blocked_reason"] = "" if effective_state != "blocked" else "blocked_reason required"
        defaults["current_owner"] = DEFAULT_STATUS_OWNER
        defaults["next_agent"] = default_next_agent_for_state(effective_state)
    return defaults, warnings


def reconcile_status_file(artifacts_root: Path, task_id: str, apply: bool = True) -> ValidationResult:
    status_path = artifact_path(artifacts_root, task_id, "status")
    status = load_json(status_path)
    defaults, warnings = build_reconcile_defaults(artifacts_root, task_id, status)
    before = dict(status)
    after = dict(status)
    changes: List[Tuple[str, object, object]] = []
    for key, value in defaults.items():
        if key in RECONCILE_PROTECTED_FIELDS:
            continue
        if key not in after:
            after[key] = value
            changes.append((key, None, value))
    if apply and changes:
        status_path.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if changes and apply:
        print("[RECONCILE] Applied missing status fields")
    elif changes:
        print("[RECONCILE] Missing status fields detected (dry-run)")
    else:
        print("[RECONCILE] No missing fields to add")
    if changes:
        for key, old_value, new_value in changes:
            print(
                f"[DIFF] {key}: before={json.dumps(old_value, ensure_ascii=False)} "
                f"after={json.dumps(new_value, ensure_ascii=False)}"
            )
    if before.keys() != after.keys():
        print(f"[RECONCILE] before_fields={sorted(before.keys())}")
        print(f"[RECONCILE] after_fields={sorted(after.keys())}")
    validation = validate_all(artifacts_root, task_id)
    validation.warnings = warnings + validation.warnings
    return validation


def reconcile_status(artifacts_root: Path, task_id: str) -> ValidationResult:
    return reconcile_status_file(artifacts_root, task_id, apply=True)


_HISTORICAL_EXCEPTION_ALLOWLIST: frozenset[str] = frozenset({"TASK-964"})
_HISTORICAL_ACCEPTED_MISSING: frozenset[str] = frozenset({"plan", "test"})
def load_verify_floor_baseline(baseline_path: Path) -> Optional[dict]:
    """Load verify-floor-baseline.v3.4.json. Returns None if file not found."""
    if not baseline_path.exists():
        return None
    return load_json(baseline_path)


def classify_verify_floor_policy(verify_path: Path, baseline: dict) -> str:
    """Classify verify artifact floor policy against the baseline.

    Returns VERIFY_FLOOR_POLICY_HISTORICAL ('advisory_until_6d') when the file
    is in the baseline with a matching sha256.  Returns VERIFY_FLOOR_POLICY_STRICT
    ('strict') when the file is absent from the baseline (new) or its sha256
    differs from the recorded value (modified after baseline).
    """
    posix = verify_path.as_posix()
    for entry in baseline.get("baseline_verify_files", []):
        entry_path = entry.get("path", "")
        if posix == entry_path or posix.endswith("/" + entry_path):
            content = read_bounded_file(verify_path, missing_label=None, too_large_label="Verify file too large")
            if content is None:
                return VERIFY_FLOOR_POLICY_STRICT
            return (
                VERIFY_FLOOR_POLICY_HISTORICAL
                if hashlib.sha256(content).hexdigest() == entry.get("sha256")
                else VERIFY_FLOOR_POLICY_STRICT
            )
    return VERIFY_FLOOR_POLICY_STRICT


_HISTORICAL_VERIFY_REQUIRED_PHRASES: tuple[str, ...] = (
    "historical limited evidence",
    "right-answer-for-wrong-reason",
    "production canonical drill",
    "task-1010",
)


def is_historical_limited_evidence_exception(
    task_id: str,
    status: dict,
    missing_required: List[str],
    verify_path: Path,
) -> bool:
    """
    Narrow exception for historical limited-evidence tasks only.
    All conditions must hold; failure of any condition returns False (strict by default).
    Must NOT be used to bypass missing-artifact checks for ordinary mvp/production tasks.
    """
    if task_id not in _HISTORICAL_EXCEPTION_ALLOWLIST:
        return False
    if str(status.get("assurance_level", "")).strip().lower() != "mvp":
        return False
    if str(status.get("verification_readiness", "")).strip().lower() != "mvp":
        return False
    if not status.get("historical_limited_evidence"):
        return False
    if status.get("missing_artifacts_policy") != "historical_limited_evidence_exception":
        return False
    if not set(missing_required).issubset(_HISTORICAL_ACCEPTED_MISSING):
        return False
    if not verify_path.exists():
        return False
    try:
        verify_text = verify_path.read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return all(phrase in verify_text for phrase in _HISTORICAL_VERIFY_REQUIRED_PHRASES)


_STRICT_FLOOR_COMMIT_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_STRICT_FLOOR_URL_RE = re.compile(r"https?://\S+")
_STRICT_FLOOR_CMD_RE = re.compile(r"`[^`\n]+`")
_STRICT_FLOOR_STATUS_RE = re.compile(r"\[(?:OK|PASS|FAIL)\]", re.IGNORECASE)
_STRICT_FLOOR_FILEPATH_RE = re.compile(r"artifacts/[^\s,;\"']+\.[a-z]{2,6}")
_STRICT_FLOOR_VALID_RESULTS = frozenset({"verified", "deferred", "unverifiable"})
_STRICT_FLOOR_CONCRETE_ER_RE = re.compile(
    r"(?:"
    r"(?:artifacts|\.github)/[^\s,;\"'<>()\n]+"
    r"|`[^`\n]+`"
    r"|command:\s*\S+"
    r"|\b[0-9a-f]{7,40}\b"
    r")",
    re.IGNORECASE,
)


def has_concrete_evidence_ref(er_text: str) -> bool:
    """Return True if the Evidence Refs section contains at least one concrete reference token.

    Concrete tokens: repo file path (artifacts/ or .github/), backtick-quoted command,
    command: prefix, or commit hash (7-40 hex chars).
    Narrative-only text such as 'Reviewed by governance process.' returns False.
    """
    return bool(_STRICT_FLOOR_CONCRETE_ER_RE.search(er_text))


def _check_strict_verify_floor(verify_path: Path, task_id: str) -> List[str]:
    """Strict floor checks for a post-baseline verify artifact (TASK-1015 enforcement)."""
    errors: List[str] = []
    try:
        text = verify_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"cannot read verify artifact: {exc}"]
    bg = extract_section(text, "Build Guarantee")
    if not bg:
        errors.append("missing or empty ## Build Guarantee section")
    else:
        has_concrete = (
            bool(_STRICT_FLOOR_COMMIT_RE.search(bg))
            or bool(_STRICT_FLOOR_URL_RE.search(bg))
            or bool(_STRICT_FLOOR_CMD_RE.search(bg))
            or bool(_STRICT_FLOOR_STATUS_RE.search(bg))
            or bool(_STRICT_FLOOR_FILEPATH_RE.search(bg))
        )
        if not has_concrete:
            errors.append(
                "## Build Guarantee is narrative-only (no commit hash, CI URL, or command evidence)"
            )
    er = extract_section(text, "Evidence Refs")
    if not er:
        errors.append("missing ## Evidence Refs section")
    elif er.strip().lower() in {"none", "n/a", "none.", "-", "—"}:
        errors.append("Evidence Refs: None is not acceptable for strict floor")
    elif not has_concrete_evidence_ref(er):
        errors.append(
            "Evidence Refs is narrative-only: must contain at least one concrete reference "
            "(repo file path, backtick command, commit hash)"
        )
    checklist_section = extract_section(text, "Acceptance Criteria Checklist")
    if checklist_section:
        items = parse_verify_checklist_items(checklist_section)
        for fields in items:
            result_val = str(fields.get("result", "")).strip().lower()
            item_label = str(fields.get("criterion") or fields.get("method") or "<unnamed>")[:60]
            if not result_val:
                errors.append(f"checklist item missing 'result:' field: {item_label}")
            elif result_val not in _STRICT_FLOOR_VALID_RESULTS:
                errors.append(
                    f"checklist item result '{result_val}' not in "
                    f"{{verified, deferred, unverifiable}}: {item_label}"
                )
    return errors


def run_verify_floor_enforce(repo_root: Path) -> int:
    """Full repo verify floor enforcement — Prompt 6d / TASK-1015."""
    baseline_path = repo_root / VERIFY_FLOOR_BASELINE_PATH
    baseline = load_verify_floor_baseline(baseline_path)
    if baseline is None:
        print(f"[FAIL] verify-floor-baseline not found at {baseline_path}", file=sys.stderr)
        return 1
    verify_dir = repo_root / "artifacts" / "verify"
    all_verify_files = sorted(verify_dir.glob("TASK-*.verify.md"))
    baseline_entries = baseline.get("baseline_verify_files", [])
    baseline_map: Dict[str, dict] = {}
    for entry in baseline_entries:
        basename = entry.get("path", "").rsplit("/", 1)[-1]
        baseline_map[basename] = entry
    baseline_unchanged: List[Tuple[Path, str]] = []
    historical_exception: List[Tuple[Path, str]] = []
    post_baseline_new: List[Tuple[Path, str]] = []
    post_baseline_modified: List[Tuple[Path, str]] = []
    for p in all_verify_files:
        task_id = p.name.replace(".verify.md", "")
        entry = baseline_map.get(p.name)
        if entry is None:
            post_baseline_new.append((p, task_id))
        else:
            raw = read_bounded_file(p, missing_label=None, too_large_label="TOO_LARGE")
            actual_sha = hashlib.sha256(raw).hexdigest() if raw is not None else ""
            if actual_sha == entry.get("sha256", ""):
                if entry.get("baseline_known_debt") == "limited_evidence":
                    historical_exception.append((p, task_id))
                else:
                    baseline_unchanged.append((p, task_id))
            else:
                post_baseline_modified.append((p, task_id))
    print("[INFO] Full repo verify floor enforcement (Prompt 6d / TASK-1015)")
    print(f"[INFO] Baseline: {VERIFY_FLOOR_BASELINE_PATH} ({len(baseline_entries)} entries)")
    print(f"\n[INFO] === Baseline entries — advisory_until_6d ({len(baseline_unchanged)}) ===")
    for _, tid in baseline_unchanged:
        print(f"[INFO]   {tid}: baseline unchanged (advisory)")
    print(f"\n[INFO] === Historical limited evidence exceptions ({len(historical_exception)}) ===")
    for _, tid in historical_exception:
        print(f"[INFO]   {tid}: baseline_known_debt=limited_evidence — advisory, not production evidence")
    print(f"\n[INFO] === Post-baseline new — strict ({len(post_baseline_new)}) ===")
    for _, tid in post_baseline_new:
        print(f"[INFO]   {tid}: POST-BASELINE-NEW -> strict enforcement applies")
    print(f"\n[INFO] === Post-baseline modified — strict ({len(post_baseline_modified)}) ===")
    if not post_baseline_modified:
        print("[INFO]   (none)")
    else:
        for _, tid in post_baseline_modified:
            print(f"[INFO]   {tid}: POST-BASELINE-MODIFIED -> strict enforcement applies")
    strict_targets = post_baseline_new + post_baseline_modified
    print(f"\n[INFO] === Strict enforcement results ({len(strict_targets)} artifacts) ===")
    failures: List[Tuple[str, List[str]]] = []
    for p, task_id in strict_targets:
        check_errors = _check_strict_verify_floor(p, task_id)
        if check_errors:
            failures.append((task_id, check_errors))
            for err in check_errors:
                print(f"[FAIL] {task_id}: {err}")
        else:
            print(f"[OK]   {task_id}: strict floor PASSED")
    print(f"\n[INFO] === Summary ===")
    print(f"[INFO] Total verify artifacts scanned: {len(all_verify_files)}")
    print(f"[INFO] Baseline unchanged (advisory): {len(baseline_unchanged)}")
    print(f"[INFO] Historical limited evidence exceptions: {len(historical_exception)} ({[t for _, t in historical_exception]})")
    print(f"[INFO] Post-baseline new (strict): {len(post_baseline_new)} ({[t for _, t in post_baseline_new]})")
    print(f"[INFO] Post-baseline modified (strict): {len(post_baseline_modified)}")
    print(f"[INFO] Strict failures: {len(failures)}")
    if failures:
        print(f"\n[FAIL] Verify floor enforcement FAILED — {len(failures)} artifact(s) did not meet strict floor")
        return 1
    print(f"\n[OK] Verify floor enforcement passed — all post-baseline verify artifacts meet strict floor")
    return 0


def validate_artifact_presence(
    artifacts_root: Path,
    task_id: str,
    state: str,
    status: dict,
    strict_scope: bool = False,
    validation_mode: str = AUTO_CLASSIFY_FULL,
) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    existing = compute_existing_artifacts(artifacts_root, task_id)
    task_path = artifact_path(artifacts_root, task_id, "task")
    task_text = load_text(task_path) if task_path.exists() else ""
    assurance_level = resolve_assurance_level(task_text, status)
    project_adapter = resolve_project_adapter(task_text, status)
    required = state_required_artifacts(
        state,
        existing,
        assurance_level=assurance_level,
        project_adapter=project_adapter,
        validation_mode=validation_mode,
    )
    missing_required = sorted(required - existing)
    if missing_required:
        verify_path = artifact_path(artifacts_root, task_id, "verify")
        if is_historical_limited_evidence_exception(task_id, status, missing_required, verify_path):
            warnings.append(
                f"Historical limited evidence exception (narrow): missing artifacts {missing_required} "
                f"acknowledged for task_id='{task_id}' only; this exception does not apply to other tasks"
            )
        else:
            errors.append(f"Missing required artifacts for state '{state}': {missing_required}")
    if not status_uses_legacy_schema(status):
        status_available = set(status.get("available_artifacts", []))
        status_missing = set(status.get("missing_artifacts", []))
        status_required = set(status.get("required_artifacts", []))
        if status_available != existing:
            warnings.append(f"available_artifacts mismatch. status.json={sorted(status_available)} actual={sorted(existing)}")
        if status_required != required:
            warnings.append(f"required_artifacts mismatch. status.json={sorted(status_required)} computed={sorted(required)}")
        computed_missing = required - existing
        if status_missing != computed_missing:
            warnings.append(f"missing_artifacts mismatch. status.json={sorted(status_missing)} computed={sorted(computed_missing)}")
    artifact_types_to_validate = existing - {"status"}
    for artifact_type in sorted(set(artifact_types_to_validate) & existing):
        for path in find_artifact_paths(artifacts_root, task_id, artifact_type):
            result = validate_markdown_artifact(path, artifact_type, task_id)
            errors.extend(result.errors)
            warnings.extend(result.warnings)
    if "verify" in existing:
        verify_path = artifact_path(artifacts_root, task_id, "verify")
        verify_contract = collect_verify_contract(
            load_text(verify_path),
            assurance_level=assurance_level,
            project_adapter=project_adapter,
            state=state,
        )
        status_debts = status.get("open_verification_debts", [])
        if isinstance(status_debts, list):
            expected_debts = verify_contract["open_verification_debts"]
            if status_debts != expected_debts:
                warnings.append(
                    "open_verification_debts mismatch. "
                    f"status.json={status_debts} computed={expected_debts}"
                )
        status_readiness = str(status.get("verification_readiness", "")).strip().lower()
        expected_readiness = str(verify_contract["computed_readiness"])
        if status_readiness and status_readiness != expected_readiness:
            warnings.append(
                "verification_readiness mismatch against verify artifact. "
                f"status.json={status_readiness} verify={expected_readiness}"
            )
    if state in {"coding", "testing", "verifying", "done"}:
        plan_path = artifact_path(artifacts_root, task_id, "plan")
        task_path = artifact_path(artifacts_root, task_id, "task")
        if plan_path.exists() and not _is_v2_plan(load_text(plan_path)) and not plan_ready_for_coding(plan_path):
            errors.append(f"Plan artifact is not Ready For Coding = yes: {plan_path.name}")
        if plan_path.exists():
            premortem_result = validate_premortem(plan_path, task_path if task_path.exists() else None)
            if state == "coding":
                errors.extend(premortem_result.errors)
            else:
                warnings.extend(premortem_result.errors)
            warnings.extend(premortem_result.warnings)
        code_path = artifact_path(artifacts_root, task_id, "code")
        if plan_path.exists() and code_path.exists():
            scope_drift_files: Set[str] = set()
            drift_files = detect_plan_code_scope_drift(load_text(plan_path), load_text(code_path))
            if drift_files:
                scope_drift_files.update(drift_files)
                scope_message = (
                    f"{code_path.name}: files changed not listed in {plan_path.name} "
                    f"## Files Likely Affected: {drift_files}"
                )
                if strict_scope:
                    errors.append(scope_message)
                else:
                    warnings.append(scope_message)
            repo_root, actual_changed, task_artifacts, git_context_warnings = load_git_scope_context(artifacts_root, task_id)
            warnings.extend(git_context_warnings)
            if state != "done" and task_artifacts.intersection(actual_changed):
                git_scope_result = detect_git_backed_scope_drift(plan_path, code_path, actual_changed, task_artifacts)
                scope_drift_files.update(git_scope_result.drift_files)
                errors.extend(git_scope_result.errors)
                if strict_scope:
                    errors.extend(git_scope_result.waiver_candidate_errors)
                else:
                    warnings.extend(git_scope_result.waiver_candidate_errors)
                warnings.extend(git_scope_result.warnings)
            else:
                history_scope_result = detect_historical_diff_scope_drift(repo_root, plan_path, code_path)
                scope_drift_files.update(history_scope_result.drift_files)
                errors.extend(history_scope_result.errors)
                if strict_scope:
                    errors.extend(history_scope_result.waiver_candidate_errors)
                else:
                    warnings.extend(history_scope_result.waiver_candidate_errors)
                warnings.extend(history_scope_result.warnings)
            if not strict_scope and scope_drift_files:
                waiver_result = validate_scope_drift_waiver(artifacts_root, task_id, scope_drift_files)
                errors.extend(waiver_result.errors)
                warnings.extend(waiver_result.warnings)
    if state == "done":
        verify_path = artifact_path(artifacts_root, task_id, "verify")
        if verify_path.exists() and not verify_result_is_pass(verify_path):
            errors.append("done state requires verify artifact with Pass Fail Result = pass")
    return ValidationResult(errors, warnings)


def validate_transition(from_state: str, to_state: str, artifacts_root: Optional[Path] = None, task_id: Optional[str] = None) -> ValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    if from_state not in VALID_STATES:
        return ValidationResult([f"Unknown from_state: {from_state}"], warnings)
    if to_state not in VALID_STATES:
        return ValidationResult([f"Unknown to_state: {to_state}"], warnings)
    if to_state not in LEGAL_TRANSITIONS.get(from_state, set()):
        errors.append(f"Illegal state transition: {from_state} -> {to_state}")
    if from_state == "blocked" and to_state != "blocked" and artifacts_root and task_id:
        improvement_paths = find_artifact_paths(artifacts_root, task_id, "improvement")
        if not improvement_paths:
            errors.append(f"Gate E (PDCA): resuming from blocked requires an improvement artifact for {task_id} in artifacts/improvement/")
            return ValidationResult(errors, warnings)
        applied_found = False
        for path in improvement_paths:
            result = validate_markdown_artifact(path, "improvement", task_id)
            errors.extend(result.errors)
            warnings.extend(result.warnings)
            text = load_text(path)
            status_match = re.search(r"^- Status:\s*(.+)$", text, re.MULTILINE)
            if improvement_profile(text) == "gate-e" and status_match and status_match.group(1).strip() == "applied":
                applied_found = True
        if not applied_found:
            errors.append(f"Gate E (PDCA): resuming from blocked requires an improvement artifact with Status: applied for {task_id}")
    return ValidationResult(errors, warnings)


def validate_all(
    artifacts_root: Path,
    task_id: str,
    strict_scope: bool = False,
    validation_mode: str = AUTO_CLASSIFY_FULL,
) -> ValidationResult:
    errors: List[str] = validate_task_id(task_id)
    warnings: List[str] = []
    if errors:
        return ValidationResult(errors, warnings)
    status = load_json(artifact_path(artifacts_root, task_id, "status"))
    schema_result = validate_status_schema(status, task_id)
    errors.extend(schema_result.errors)
    warnings.extend(schema_result.warnings)
    state = resolve_status_state(status)
    if state in VALID_STATES:
        presence_result = validate_artifact_presence(
            artifacts_root,
            task_id,
            state,
            status,
            strict_scope=strict_scope,
            validation_mode=validation_mode,
        )
        errors.extend(presence_result.errors)
        warnings.extend(presence_result.warnings)
    return ValidationResult(errors, warnings)


def parse_missing_required_artifacts(error: str) -> Set[str]:
    if "Missing required artifacts for state" not in error:
        return set()
    tail = error.split(":", 1)[-1]
    return {match.strip() for match in re.findall(r"'([^']+)'", tail)}


def classify_decision_waiver_gate(error: str) -> Optional[str]:
    lowered = error.lower()
    if "waiver expired" in lowered:
        return None
    if error.startswith("Target state '"):
        return "__META__"
    missing_artifacts = parse_missing_required_artifacts(error)
    if missing_artifacts:
        gates = {
            gate
            for artifact_name, gate in {
                "research": "Gate_A",
                "plan": "Gate_B",
                "code": "Gate_C",
                "verify": "Gate_D",
            }.items()
            if artifact_name in missing_artifacts
        }
        return next(iter(gates)) if len(gates) == 1 else None
    if "requires an improvement artifact" in lowered or "gate e (pdca)" in lowered:
        return "Gate_E"
    if "done state requires verify artifact" in lowered or ".verify.md" in error:
        return "Gate_D"
    if "plan artifact is not ready for coding" in lowered or ".plan.md" in error:
        return "Gate_B"
    if ".code.md" in error:
        return "Gate_C"
    if ".research.md" in error or "research artifact" in lowered:
        return "Gate_A"
    return None


def active_decision_waivers(status: dict) -> Dict[str, dict]:
    active: Dict[str, dict] = {}
    now = datetime.now(TAIPEI_TZ)
    decision_waivers = status.get("decision_waivers", [])
    if not isinstance(decision_waivers, list):
        return active
    for entry in decision_waivers:
        if not isinstance(entry, dict):
            continue
        gate = str(entry.get("gate", "")).strip()
        expires = parse_taipei_datetime(str(entry.get("expires", "")).strip())
        if gate in DECISION_WAIVER_GATES and expires is not None and expires > now:
            active[gate] = entry
    return active


def improvement_profile(text: str) -> str:
    match = re.search(r"^- Improvement Profile:\s*(.+)$", text, re.MULTILINE)
    if match:
        candidate = match.group(1).strip().lower()
        if candidate in IMPROVEMENT_PROFILES:
            return candidate
    trigger_match = re.search(r"^- Trigger Type:\s*(.+)$", text, re.MULTILINE)
    trigger = trigger_match.group(1).strip().lower() if trigger_match else ""
    return "gate-e" if trigger in {"failure", "blocked"} else "retrospective"


def apply_decision_waivers(result: ValidationResult, status: dict) -> ValidationResult:
    waivers = active_decision_waivers(status)
    if not waivers or not result.errors:
        return result

    remaining_errors: List[str] = []
    meta_errors: List[str] = []
    waived_gate_letters: List[str] = []
    used_gates: Set[str] = set()

    for error in result.errors:
        gate = classify_decision_waiver_gate(error)
        if gate == "__META__":
            meta_errors.append(error)
            continue
        if gate and gate in waivers:
            used_gates.add(gate)
            continue
        remaining_errors.append(error)

    if remaining_errors:
        return ValidationResult(remaining_errors + meta_errors, list(result.warnings), list(result.active_waivers))

    for gate in sorted(used_gates):
        waived_gate_letters.append(DECISION_WAIVER_GATES[gate])
    return ValidationResult([], list(result.warnings), sorted(set(result.active_waivers + waived_gate_letters)))


def categorize_override_error(message: str) -> str:
    lowered = message.lower()
    if "override log missing" in lowered:
        return "override_log_missing"
    if ": premortem" in lowered or lowered.startswith("premortem"):
        if any(pattern in lowered for pattern in PREMORTEM_MISSING_PATTERNS):
            return "premortem_missing"
        return "premortem"
    return "critical"


def ensure_override_log_not_missing(artifacts_root: Path, task_id: str) -> None:
    status = load_json(artifact_path(artifacts_root, task_id, "status"))
    if not status.get(OVERRIDE_STATUS_FLAG):
        return
    path = override_log_path(artifacts_root, task_id)
    if not path.exists():
        raise GuardError(f"{task_id}: override log missing ({path.name})")
    load_override_log(path)


def append_override_record(artifacts_root: Path, task_id: str, reason: str, approver: str, overridden_errors: List[str]) -> None:
    path = override_log_path(artifacts_root, task_id)
    log_entries = load_override_log(path)
    log_entries.append(
        {
            "timestamp": current_taipei_timestamp(),
            "reason": reason,
            "approver": approver,
            "overridden_errors": overridden_errors,
        }
    )
    path.write_text(json.dumps(log_entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    status_path = artifact_path(artifacts_root, task_id, "status")
    status = load_json(status_path)
    status[OVERRIDE_STATUS_FLAG] = True
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def apply_override(result: ValidationResult, artifacts_root: Path, task_id: str, reason: str, approver: str) -> ValidationResult:
    warnings = list(result.warnings)
    errors: List[str] = []
    overridden_errors: List[str] = []
    for error in result.errors:
        category = categorize_override_error(error)
        if category in {"premortem_missing", "override_log_missing"}:
            errors.append(error)
            continue
        if category == "premortem":
            warnings.append(f"[OVERRIDE PREMORTEM WARNING] {error}")
            continue
        warnings.append(f"[OVERRIDDEN] {error}")
        overridden_errors.append(error)
    if errors:
        return ValidationResult(errors, warnings)
    append_override_record(artifacts_root, task_id, reason, approver, overridden_errors)
    return ValidationResult([], warnings)


def write_transition(
    artifacts_root: Path,
    task_id: str,
    from_state: str,
    to_state: str,
    strict_scope: bool = False,
    validation_mode: str = AUTO_CLASSIFY_FULL,
) -> ValidationResult:
    transition_result = validate_transition(from_state, to_state, artifacts_root, task_id)
    if transition_result.errors:
        return transition_result
    status_path = artifact_path(artifacts_root, task_id, "status")
    status = load_json(status_path)
    current_state = resolve_status_state(status)
    if current_state != from_state:
        return ValidationResult([f"Refusing transition because status.json state is {current_state}, not expected {from_state}"], [])
    full_result = validate_all(artifacts_root, task_id, strict_scope=strict_scope, validation_mode=validation_mode)
    if full_result.errors:
        return full_result
    target_presence = validate_artifact_presence(
        artifacts_root,
        task_id,
        to_state,
        status,
        strict_scope=strict_scope,
        validation_mode=validation_mode,
    )
    if target_presence.errors:
        return ValidationResult([f"Target state '{to_state}' requirements are not yet satisfied.", *target_presence.errors], target_presence.warnings)
    existing = compute_existing_artifacts(artifacts_root, task_id)
    task_path = artifact_path(artifacts_root, task_id, "task")
    task_text = load_text(task_path) if task_path.exists() else ""
    assurance_level = resolve_assurance_level(task_text, status)
    project_adapter = resolve_project_adapter(task_text, status)
    required = state_required_artifacts(
        to_state,
        existing,
        assurance_level=assurance_level,
        project_adapter=project_adapter,
        validation_mode=validation_mode,
    )
    status["state"] = to_state
    status["assurance_level"] = assurance_level
    status["project_adapter"] = project_adapter
    status["required_artifacts"] = sorted(required)
    status["available_artifacts"] = sorted(existing)
    status["missing_artifacts"] = sorted(required - existing)
    if to_state != "blocked":
        status["blocked_reason"] = ""
    # Auto-populate Gate_E when transitioning to "done" with improvement artifact
    if to_state == "done" and "improvement" in existing:
        improvement_paths = find_artifact_paths(artifacts_root, task_id, "improvement")
        for imp_path in improvement_paths:
            imp_text = load_text(imp_path)
            if improvement_profile(imp_text) == "gate-e" and ("Status: applied" in imp_text or "Status:applied" in imp_text):
                gate_e_timestamp = current_taipei_timestamp()
                status["Gate_E_passed"] = True
                status["Gate_E_evidence"] = [
                    f"artifacts/improvement/{imp_path.name}",
                    *[f"artifacts/decisions/{d.name}" for d in find_artifact_paths(artifacts_root, task_id, "decision")]
                ]
                status["Gate_E_timestamp"] = gate_e_timestamp
                break
        else:
            # No applied improvement found, mark Gate_E as not passed if it was blocked
            if from_state == "blocked":
                status["Gate_E_passed"] = False
                status["Gate_E_evidence"] = []
    write_json(status_path, status)
    return ValidationResult([], transition_result.warnings + full_result.warnings + target_presence.warnings)


def print_result(result: ValidationResult, override_active: bool = False) -> None:
    if override_active:
        print("[OVERRIDE ACTIVE]")
    for gate in result.active_waivers:
        print(f"[WAIVER ACTIVE gate={gate}]")
    print("[OK] Validation passed" if result.ok else "[ERROR] Validation failed")
    for warning in result.warnings:
        print(f"[WARN] {warning}")
    for error in result.errors:
        print(f"[FAIL] {error}")


def check_tao_trace(artifacts_root: Path, task_id: str) -> List[str]:
    """Check whether a high-risk task has ## TAO Trace in code/verify artifacts.

    Reads risk_classification.csv to determine if the task is high-risk.
    Returns a list of warning strings (empty if OK or task is low-risk).
    """
    import csv as csv_mod

    warnings: List[str] = []
    registry_dir = artifacts_root / "registry"
    csv_path = registry_dir / "risk_classification.csv"

    if not csv_path.exists():
        warnings.append(f"{task_id}: risk_classification.csv not found; cannot determine risk level for TAO check")
        return warnings

    # Load classification
    risk_level = None
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv_mod.DictReader(f)
        for row in reader:
            if row.get("task_id") == task_id:
                risk_level = row.get("risk_level", "unknown")
                break

    if risk_level is None:
        warnings.append(f"{task_id}: not found in risk_classification.csv; skipping TAO check")
        return warnings

    if risk_level != "high-risk":
        # Low-risk tasks do not require TAO Trace
        return warnings

    # Check code artifact
    code_path = artifact_path(artifacts_root, task_id, "code")
    if code_path.exists():
        code_text = load_text(code_path)
        if "## TAO Trace" not in code_text:
            warnings.append(f"{task_id}: TAO Trace expected for risk>=3 task but missing in code artifact")

    # Check verify artifact
    verify_path = artifact_path(artifacts_root, task_id, "verify")
    if verify_path.exists():
        verify_text = load_text(verify_path)
        if "## TAO Trace" not in verify_text:
            warnings.append(f"{task_id}: TAO Trace expected for risk>=3 task but missing in verify artifact")

    return warnings


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate artifact workflow status and transitions.")
    parser.add_argument("--task-id", "--task", dest="task_id", required=False, default=None, help="Task id, for example TASK-001")
    parser.add_argument("--artifacts-root", default="./artifacts", help="Artifacts root directory. Default: ./artifacts")
    parser.add_argument("--from-state", help="Validate a proposed transition from this state")
    parser.add_argument("--to-state", help="Validate a proposed transition to this state")
    parser.add_argument("--write-transition", nargs=2, metavar=("FROM_STATE", "TO_STATE"), help="Validate and write the transition into status.json if allowed")
    parser.add_argument(
        "--strict-scope",
        action="store_true",
        help="Legacy compatibility flag. Scope checks are strict by default unless --allow-scope-drift is provided.",
    )
    parser.add_argument(
        "--allow-scope-drift",
        action="store_true",
        help="Allow plan/code scope drift, including git-backed or historical diff evidence checks, as warning only when an explicit decision waiver exists. Default behavior treats drift as failure.",
    )
    parser.add_argument(
        "--auto-classify",
        action="store_true",
        help="Auto-classify lightweight vs full validation mode from task/status artifacts before validation.",
    )
    parser.add_argument("--override", help="Human-approved override reason. Must be used with --override-approver.")
    parser.add_argument("--override-approver", help="Human approver for --override. Must be used with --override.")
    parser.add_argument("--reconcile", action="store_true", help="Backfill missing status.json fields from task artifacts without overwriting existing values.")
    parser.add_argument(
        "--check-tao",
        action="store_true",
        help="Check whether high-risk tasks (per risk_classification.csv) contain ## TAO Trace in code/verify artifacts. Warning-only, does not affect exit code.",
    )
    parser.add_argument(
        "--verify-floor-dry-run",
        action="store_true",
        help=(
            "Dry-run verify floor policy classification for the task's verify artifact. "
            "Reports whether the verify is 'advisory_until_6d' (historical baseline, unchanged) "
            "or 'strict' (new or modified after baseline). Never fails; always exits 0. "
            "Full enforcement is deferred to Prompt 6d / TASK-1015."
        ),
    )
    parser.add_argument(
        "--verify-floor-enforce",
        action="store_true",
        help=(
            "Full repo verify floor enforcement (Prompt 6d / TASK-1015). "
            "Scans all artifacts/verify/TASK-*.verify.md, classifies each artifact "
            "by its baseline relationship, and applies strict floor checks to all "
            "post-baseline new/modified verify artifacts. Does not require --task-id. "
            "Use --root to specify the project root (default: parent of --artifacts-root)."
        ),
    )
    parser.add_argument(
        "--root",
        dest="repo_root",
        default=None,
        help="Project root directory for --verify-floor-enforce. Default: parent of --artifacts-root.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    artifacts_root = Path(args.artifacts_root).resolve()
    if args.verify_floor_enforce:
        repo_root = Path(args.repo_root).resolve() if args.repo_root else artifacts_root.parent
        return run_verify_floor_enforce(repo_root)
    if args.task_id is None:
        print("[FAIL] --task-id is required", file=sys.stderr)
        return 2
    if args.strict_scope and args.allow_scope_drift:
        print("[FAIL] --strict-scope and --allow-scope-drift cannot be used together", file=sys.stderr)
        return 2
    if bool(args.override) != bool(args.override_approver):
        print("[FAIL] --override and --override-approver must be used together", file=sys.stderr)
        return 2
    if args.override and (not args.override.strip() or not args.override_approver.strip()):
        print("[FAIL] --override and --override-approver must be non-empty", file=sys.stderr)
        return 2
    if args.reconcile and (args.override or args.override_approver):
        print("[FAIL] --reconcile cannot be combined with override options", file=sys.stderr)
        return 2
    strict_scope = args.strict_scope or not args.allow_scope_drift
    if args.check_tao:
        tao_warnings = check_tao_trace(artifacts_root, args.task_id)
        for w in tao_warnings:
            print(f"[WARN] {w}")
        if not tao_warnings:
            print("[OK] TAO Trace check passed (no missing traces)")
        return 0
    if args.verify_floor_dry_run:
        baseline_path = artifacts_root.parent / VERIFY_FLOOR_BASELINE_PATH
        baseline = load_verify_floor_baseline(baseline_path)
        if baseline is None:
            print(f"[WARN] verify-floor-baseline not found at {baseline_path}; cannot classify", file=sys.stderr)
            return 0
        verify_path = artifact_path(artifacts_root, args.task_id, "verify")
        policy = classify_verify_floor_policy(verify_path, baseline)
        print(f"[INFO] verify-floor policy for {args.task_id}: {policy}")
        if policy == VERIFY_FLOOR_POLICY_STRICT:
            print(
                f"[INFO] {args.task_id}: verify artifact is NEW or MODIFIED after baseline "
                f"-> strict enforcement applies (full enforcement via Prompt 6d / TASK-1015)"
            )
        else:
            print(
                f"[INFO] {args.task_id}: verify artifact is in baseline (historical unchanged) "
                f"-> advisory_until_6d; strict enforcement deferred to Prompt 6d / TASK-1015"
            )
        return 0
    try:
        auto_classification = resolve_validation_mode(artifacts_root, args.task_id, args.auto_classify)
        validation_mode = auto_classification.validation_mode
        if args.reconcile:
            result = reconcile_status(artifacts_root, args.task_id)
            result.warnings = auto_classification.warnings + result.warnings
            print_result(result)
            return 0 if result.ok else 1
        if args.override:
            ensure_override_log_not_missing(artifacts_root, args.task_id)
        if args.write_transition:
            result = write_transition(
                artifacts_root,
                args.task_id,
                args.write_transition[0],
                args.write_transition[1],
                strict_scope=strict_scope,
                validation_mode=validation_mode,
            )
            result = apply_decision_waivers(result, load_json(artifact_path(artifacts_root, args.task_id, "status")))
            result.warnings = auto_classification.warnings + result.warnings
            if args.override:
                result = apply_override(result, artifacts_root, args.task_id, args.override, args.override_approver)
            print_result(result, override_active=bool(args.override))
            return 0 if result.ok else 1
        if bool(args.from_state) != bool(args.to_state):
            print("[FAIL] --from-state and --to-state must be used together", file=sys.stderr)
            return 2
        result = validate_all(
            artifacts_root,
            args.task_id,
            strict_scope=strict_scope,
            validation_mode=validation_mode,
        )
        if args.from_state and args.to_state:
            transition_result = validate_transition(args.from_state, args.to_state, artifacts_root, args.task_id)
            result.errors.extend(transition_result.errors)
            result.warnings.extend(transition_result.warnings)
        result = apply_decision_waivers(result, load_json(artifact_path(artifacts_root, args.task_id, "status")))
        result.warnings = auto_classification.warnings + result.warnings
        if args.override:
            result = apply_override(result, artifacts_root, args.task_id, args.override, args.override_approver)
        print_result(result, override_active=bool(args.override))
        return 0 if result.ok else 1
    except GuardError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover
        print(f"[FAIL] Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
