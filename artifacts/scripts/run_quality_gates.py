#!/usr/bin/env python3
"""v3.5.0 baseline-aware P0 quality gate runner (TASK-1025 deliverable).

Consumes:
- artifacts/governance/quality-baseline.v3.5.json (TASK-1024 frozen baseline)
- artifacts/governance/quality-gate-policy.v3.5.json (this task's policy)

Implements baseline-aware enforcement for QC-SYNC-001, QC-SCHEMA-001,
QC-IMPORT-001, QC-GOLDEN-001 plus advisory QC-RUFF-001.

Existing baseline drift with unchanged sha256 is NOT a TASK-1025 failure.
New or modified drift after baseline IS blocking unless covered by a
valid unexpired waiver. Expired waivers are blocking.

TASK-1042 adds explicit CLI-only runtime waiver registry consumption via
``--waiver-policy <path>``. When the flag is absent, behavior is byte-
identical to TASK-1025/TASK-1037 default mode. When provided, the runner
loads a ``waiver-policy-registry/v1`` registry and applies its valid
active unexpired waivers to QC-SYNC-001 findings only; registry load
failures fail closed with exit code 2.

Usage:
  python artifacts/scripts/run_quality_gates.py [--baseline PATH] [--policy PATH]
                                                [--waiver-policy PATH]
                                                [--format json] [--self-check]
                                                [--output PATH]

Exit codes:
  0 = no blocking failures
  1 = at least one blocking gate failed
  2 = invocation error / missing inputs / waiver registry load failure
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_PATH = Path(__file__).resolve()
TAIPEI_TZ = timezone(timedelta(hours=8))

REQUIRED_WAIVER_FIELDS = (
    "rule_id",
    "scope",
    "reason_code",
    "owner",
    "evidence_ref",
    "expires_at",
)


# ---------------------------------------------------------------------------
# Stream init (CLI entrypoint only — do NOT call at import time)
# ---------------------------------------------------------------------------

def init_streams(stdout: Any = None, stderr: Any = None) -> None:
    """Apply UTF-8 encoding wrapper to streams. CLI entrypoint only."""
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    if hasattr(out, "buffer") and getattr(out, "encoding", "utf-8").lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(out.buffer, encoding="utf-8", errors="replace")
    if hasattr(err, "buffer") and getattr(err, "encoding", "utf-8").lower() != "utf-8":
        sys.stderr = io.TextIOWrapper(err.buffer, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Repo helpers
# ---------------------------------------------------------------------------

def detect_repo_root() -> Path:
    matches = [
        parent
        for parent in SCRIPT_PATH.parents
        if (parent / "council-forge-governance-repair-plan-v3.5.md").is_file()
        and (parent / "artifacts" / "governance" / "quality-baseline.v3.5.json").is_file()
        and (parent / "template").is_dir()
    ]
    if not matches:
        raise RuntimeError(f"Unable to detect repo root from {SCRIPT_PATH}")
    return matches[-1]


def sha256_of_file(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def now_taipei_iso() -> str:
    return datetime.now(TAIPEI_TZ).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Waiver helpers
# ---------------------------------------------------------------------------

def is_waiver_shape_valid(waiver: Dict[str, Any]) -> Tuple[bool, str]:
    missing = [f for f in REQUIRED_WAIVER_FIELDS if f not in waiver]
    if missing:
        return False, "missing_fields:" + ",".join(missing)
    scope = waiver.get("scope")
    if not isinstance(scope, list) or not scope:
        return False, "scope_must_be_nonempty_list"
    return True, "ok"


def is_waiver_unexpired(waiver: Dict[str, Any], today_iso: str) -> Tuple[bool, str]:
    expires = waiver.get("expires_at", "")
    if not isinstance(expires, str) or not expires:
        return False, "expires_at_missing"
    today_date = today_iso[:10]
    if today_date > expires:
        return False, "expired:" + expires
    return True, "ok"


def find_applicable_waivers(
    rule_id: str, target_path: str, policy_waivers: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for w in policy_waivers:
        if w.get("rule_id") != rule_id:
            continue
        scope = w.get("scope") or []
        if isinstance(scope, list) and target_path in scope:
            out.append(w)
    return out


def select_valid_waivers(
    waivers: List[Dict[str, Any]], today_iso: str
) -> Tuple[List[Dict[str, Any]], List[str]]:
    valid: List[Dict[str, Any]] = []
    invalid_reasons: List[str] = []
    for w in waivers:
        ok_s, msg_s = is_waiver_shape_valid(w)
        if not ok_s:
            invalid_reasons.append(msg_s)
            continue
        ok_e, msg_e = is_waiver_unexpired(w, today_iso)
        if not ok_e:
            invalid_reasons.append(msg_e)
            continue
        valid.append(w)
    return valid, invalid_reasons


# ---------------------------------------------------------------------------
# TASK-1042 runtime waiver registry (explicit --waiver-policy <path> only)
# ---------------------------------------------------------------------------

RUNTIME_WAIVER_REGISTRY_SCHEMA_VERSION = "waiver-policy-registry/v1"

RUNTIME_WAIVER_REGISTRY_REQUIRED_TOP_FIELDS: Tuple[str, ...] = (
    "schema_version",
    "created_by_task",
    "registry_status",
    "runtime_consumption_authorized",
    "waivers",
)

RUNTIME_WAIVER_REGISTRY_OPTIONAL_TOP_FIELDS: Tuple[str, ...] = (
    "plan_version",
    "generated_at",
    "limitations",
)

RUNTIME_WAIVER_REGISTRY_ALLOWED_TOP_FIELDS: Tuple[str, ...] = (
    RUNTIME_WAIVER_REGISTRY_REQUIRED_TOP_FIELDS
    + RUNTIME_WAIVER_REGISTRY_OPTIONAL_TOP_FIELDS
)

RUNTIME_WAIVER_ENTRY_REQUIRED_FIELDS: Tuple[str, ...] = (
    "waiver_id",
    "rule_id",
    "target",
    "scope",
    "reason_code",
    "owner",
    "evidence_ref",
    "expires_at",
    "created_by_task",
    "created_at",
    "status",
)

RUNTIME_WAIVER_ENTRY_ALLOWED_FIELDS: Tuple[str, ...] = RUNTIME_WAIVER_ENTRY_REQUIRED_FIELDS

RUNTIME_WAIVER_ALLOWED_STATUSES: Tuple[str, ...] = (
    "active",
    "expired",
    "revoked",
    "superseded",
    "invalid",
    "advisory_only",
)

RUNTIME_WAIVER_SUPPORTED_RULE_IDS: Tuple[str, ...] = ("QC-SYNC-001",)

RUNTIME_WAIVER_SUPPORTED_SCOPE_TYPES: Tuple[str, ...] = ("path", "pair", "task", "artifact")

RUNTIME_WAIVER_FORBIDDEN_SCOPE_VALUES_WILDCARD: Tuple[str, ...] = (
    "*",
    "**",
    "**/*",
    "*/",
    "*.*",
)

RUNTIME_WAIVER_FORBIDDEN_SCOPE_VALUES_BROAD: Tuple[str, ...] = (
    "",
    "/",
    "artifacts",
    "artifacts/",
    "template",
    "template/",
    "docs",
    "docs/",
    ".github",
    ".github/",
)

RUNTIME_WAIVER_FORBIDDEN_EVIDENCE_REF_PREFIXES: Tuple[str, ...] = (
    ".obsidian/",
    ".omc/",
    ".tmp/",
    ".pytest-basetemp/",
    "__pycache__/",
    ".pytest_cache/",
    "node_modules/",
    ".venv/",
    ".git/",
)

RUNTIME_WAIVER_FORBIDDEN_EVIDENCE_REF_SCHEMES: Tuple[str, ...] = (
    "http://",
    "https://",
    "ftp://",
    "file://",
    "ssh://",
    "git://",
    "git+ssh://",
)

RUNTIME_WAIVER_FORBIDDEN_EVIDENCE_REF_SHELL_TOKENS: Tuple[str, ...] = (
    ";",
    "|",
    "&&",
    ">",
    "<",
    "`",
    "$(",
)

_EXPIRES_AT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _waiver_registry_load_error(reason_code: str) -> Dict[str, Any]:
    return {"error": "waiver_registry_load_failed", "reason_code": reason_code}


def _validate_runtime_waiver_evidence_ref(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return "waiver_registry_missing_required_field:evidence_ref"
    if value.startswith("/") or value.startswith("\\"):
        return "waiver_registry_forbidden_pattern:absolute_path"
    if len(value) >= 2 and value[1] == ":":
        return "waiver_registry_forbidden_pattern:absolute_path"
    if ".." in value:
        return "waiver_registry_forbidden_pattern:parent_traversal"
    for scheme in RUNTIME_WAIVER_FORBIDDEN_EVIDENCE_REF_SCHEMES:
        if value.startswith(scheme):
            return "waiver_registry_forbidden_pattern:remote_url:" + scheme
    for tok in RUNTIME_WAIVER_FORBIDDEN_EVIDENCE_REF_SHELL_TOKENS:
        if tok in value:
            return "waiver_registry_forbidden_pattern:shell_token"
    for prefix in RUNTIME_WAIVER_FORBIDDEN_EVIDENCE_REF_PREFIXES:
        if value.startswith(prefix):
            return "waiver_registry_forbidden_pattern:forbidden_root:" + prefix.rstrip("/")
    if not value.startswith("artifacts/"):
        return "waiver_registry_forbidden_pattern:not_under_artifacts"
    return None


def _validate_runtime_waiver_scope(scope: Any) -> Optional[str]:
    if not isinstance(scope, dict):
        return "waiver_registry_invalid_scope_shape:not_object"
    extras = set(scope.keys()) - {"type", "value"}
    if extras:
        return "waiver_registry_unknown_waiver_field:scope." + sorted(extras)[0]
    s_type = scope.get("type")
    s_value = scope.get("value")
    if s_type not in RUNTIME_WAIVER_SUPPORTED_SCOPE_TYPES:
        return "waiver_registry_unknown_enum_value:scope.type=" + str(s_type)
    if not isinstance(s_value, str):
        return "waiver_registry_invalid_scope_shape:value_not_string"
    if s_value in RUNTIME_WAIVER_FORBIDDEN_SCOPE_VALUES_WILDCARD or s_value.strip("*/") == "":
        return "waiver_registry_forbidden_pattern:wildcard_only_scope"
    if s_value in RUNTIME_WAIVER_FORBIDDEN_SCOPE_VALUES_BROAD:
        return "waiver_registry_forbidden_pattern:broad_repo_wide_waiver"
    return None


def load_runtime_waiver_registry(
    path: Path,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Load and validate a TASK-1042 runtime waiver registry.

    Returns a tuple ``(registry, error_envelope)``. On success the
    error envelope is None and the registry dict is returned. On any
    validation failure the registry is None and an error envelope of
    the form ``{"error": "waiver_registry_load_failed", "reason_code": ...}``
    is returned.
    """
    if not path.is_file():
        return None, _waiver_registry_load_error(
            "waiver_registry_missing:" + str(path).replace("\\", "/")
        )
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None, _waiver_registry_load_error("waiver_registry_malformed_json")
    if not isinstance(data, dict):
        return None, _waiver_registry_load_error("waiver_registry_malformed_json")

    schema_version = data.get("schema_version")
    if schema_version != RUNTIME_WAIVER_REGISTRY_SCHEMA_VERSION:
        return None, _waiver_registry_load_error(
            "waiver_registry_schema_version_mismatch:" + str(schema_version)
        )

    for required in RUNTIME_WAIVER_REGISTRY_REQUIRED_TOP_FIELDS:
        if required not in data:
            return None, _waiver_registry_load_error(
                "waiver_registry_missing_required_field:" + required
            )

    for present in data.keys():
        if present not in RUNTIME_WAIVER_REGISTRY_ALLOWED_TOP_FIELDS:
            return None, _waiver_registry_load_error(
                "waiver_registry_unknown_top_level_field:" + str(present)
            )

    if data.get("runtime_consumption_authorized") is not True:
        return None, _waiver_registry_load_error(
            "waiver_registry_runtime_consumption_not_authorized"
        )

    waivers = data.get("waivers")
    if not isinstance(waivers, list):
        return None, _waiver_registry_load_error("waiver_registry_waivers_not_array")

    seen_ids: Dict[str, Dict[str, Any]] = {}
    active_target_keys: Dict[Tuple[str, str], str] = {}

    for entry in waivers:
        if not isinstance(entry, dict):
            return None, _waiver_registry_load_error(
                "waiver_registry_waiver_entry_not_object"
            )
        for required in RUNTIME_WAIVER_ENTRY_REQUIRED_FIELDS:
            if required not in entry:
                return None, _waiver_registry_load_error(
                    "waiver_registry_missing_required_field:" + required
                )
        for present in entry.keys():
            if present not in RUNTIME_WAIVER_ENTRY_ALLOWED_FIELDS:
                return None, _waiver_registry_load_error(
                    "waiver_registry_unknown_waiver_field:" + str(present)
                )
        for str_field in (
            "waiver_id",
            "rule_id",
            "target",
            "reason_code",
            "owner",
            "created_by_task",
            "created_at",
            "status",
        ):
            value = entry.get(str_field)
            if not isinstance(value, str) or not value.strip():
                return None, _waiver_registry_load_error(
                    "waiver_registry_missing_required_field:" + str_field
                )
        if entry["status"] not in RUNTIME_WAIVER_ALLOWED_STATUSES:
            return None, _waiver_registry_load_error(
                "waiver_registry_unknown_enum_value:status=" + str(entry["status"])
            )
        if entry["rule_id"] not in RUNTIME_WAIVER_SUPPORTED_RULE_IDS:
            return None, _waiver_registry_load_error(
                "waiver_registry_unknown_enum_value:rule_id=" + str(entry["rule_id"])
            )
        expires_at = entry.get("expires_at")
        if not isinstance(expires_at, str) or not expires_at:
            return None, _waiver_registry_load_error(
                "waiver_registry_missing_required_field:expires_at"
            )
        if not _EXPIRES_AT_PATTERN.match(expires_at):
            return None, _waiver_registry_load_error(
                "waiver_registry_invalid_expires_at:" + expires_at
            )
        scope_err = _validate_runtime_waiver_scope(entry.get("scope"))
        if scope_err is not None:
            return None, _waiver_registry_load_error(scope_err)
        evidence_err = _validate_runtime_waiver_evidence_ref(entry.get("evidence_ref"))
        if evidence_err is not None:
            return None, _waiver_registry_load_error(evidence_err)
        wid = entry["waiver_id"]
        if wid in seen_ids:
            return None, _waiver_registry_load_error(
                "waiver_registry_pair_uniqueness_violation:" + wid
            )
        seen_ids[wid] = entry
        if entry["status"] == "active":
            key = (entry["rule_id"], entry["target"])
            if key in active_target_keys:
                return None, _waiver_registry_load_error(
                    "waiver_registry_qc_sync_001_conflict:" + entry["target"]
                )
            active_target_keys[key] = wid

    return data, None


def find_runtime_waiver_for_target(
    rule_id: str,
    target: str,
    runtime_waivers: List[Dict[str, Any]],
    today_date: str,
) -> Optional[Dict[str, Any]]:
    """Return the first matching valid active unexpired runtime waiver, else None."""
    for w in runtime_waivers:
        if w.get("rule_id") != rule_id:
            continue
        if w.get("status") != "active":
            continue
        if w.get("target") != target:
            continue
        expires_at = w.get("expires_at", "")
        if not isinstance(expires_at, str) or today_date > expires_at:
            continue
        scope = w.get("scope") or {}
        s_type = scope.get("type")
        s_value = scope.get("value")
        if s_type in ("path", "pair") and s_value == target:
            return w
    return None


# ---------------------------------------------------------------------------
# QC-SYNC-001 source/template baseline-aware enforcement
# ---------------------------------------------------------------------------

# Source/template root convention. Discovery runs over this convention to find
# post-baseline new pairs that the TASK-1024 baseline does not list.
SOURCE_TEMPLATE_ROOTS: List[Tuple[str, str]] = [
    ("artifacts/scripts", "template/artifacts/scripts"),
]


def discover_current_pairs(repo_root: Path) -> Dict[str, Dict[str, str]]:
    """Discover current source/template pairs from repo state.

    Returns dict keyed by repo-relative source_path. Each value contains
    source_path and template_path. The pair is collected when the .py file
    appears under either side; the absent side is reported as missing later.
    """
    pairs: Dict[str, Dict[str, str]] = {}
    for src_rel_root, tpl_rel_root in SOURCE_TEMPLATE_ROOTS:
        src_root = repo_root / src_rel_root
        tpl_root = repo_root / tpl_rel_root
        names: set = set()
        if src_root.is_dir():
            for f in src_root.glob("*.py"):
                if f.is_file():
                    names.add(f.name)
        if tpl_root.is_dir():
            for f in tpl_root.glob("*.py"):
                if f.is_file():
                    names.add(f.name)
        for name in sorted(names):
            rel_src = src_rel_root + "/" + name
            rel_tpl = tpl_rel_root + "/" + name
            pairs[rel_src] = {"source_path": rel_src, "template_path": rel_tpl}
    return pairs


def _classify_current(current_src_sha: Optional[str], current_tpl_sha: Optional[str]) -> str:
    if current_src_sha is None and current_tpl_sha is None:
        return "missing_both"
    if current_src_sha is None:
        return "missing_source"
    if current_tpl_sha is None:
        return "missing_template"
    if current_src_sha == current_tpl_sha:
        return "in_sync"
    return "drift"


def run_qc_sync_001(
    repo_root: Path,
    baseline: Dict[str, Any],
    policy: Dict[str, Any],
    today_iso: str,
    runtime_waivers: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    pairs = baseline.get("source_template_pairs", []) or []
    waivers = policy.get("waivers", []) or []
    runtime_waivers = runtime_waivers or []
    today_date = today_iso[:10]
    checks: List[Dict[str, Any]] = []

    baseline_src_paths: set = set()

    # ------------------- Pass 1: baseline-existing pairs -------------------
    for pair in pairs:
        bid = pair.get("baseline_id", "?")
        src_rel = pair.get("source_path") or ""
        tpl_rel = pair.get("template_path") or ""
        baseline_status = pair.get("status")
        baseline_src_sha = pair.get("sha256_source")
        baseline_tpl_sha = pair.get("sha256_template")

        if src_rel:
            baseline_src_paths.add(src_rel)

        src_path = repo_root / src_rel if src_rel else None
        tpl_path = repo_root / tpl_rel if tpl_rel else None
        current_src_sha = sha256_of_file(src_path) if src_path else None
        current_tpl_sha = sha256_of_file(tpl_path) if tpl_path else None

        current_status = _classify_current(current_src_sha, current_tpl_sha)
        baseline_unchanged = (
            current_src_sha == baseline_src_sha
            and current_tpl_sha == baseline_tpl_sha
        )

        check: Dict[str, Any] = {
            "gate_id": "QC-SYNC-001",
            "target": src_rel,
            "pair_classification": "baseline_existing_pair",
            "expected": "in_sync_or_unchanged_baseline_drift_or_valid_waiver",
            "actual": (
                "current_status=" + str(current_status)
                + "; baseline_status=" + str(baseline_status)
                + "; baseline_unchanged=" + str(baseline_unchanged)
            ),
            "evidence_ref": "baseline_id=" + str(bid),
        }

        if current_status == "in_sync":
            check["status"] = "pass"
            check["reason_code"] = "in_sync"
        elif baseline_status in ("drift", "missing_template", "missing_source") and baseline_unchanged:
            check["status"] = "pass"
            check["reason_code"] = "baseline_existing"
        else:
            runtime_match = find_runtime_waiver_for_target(
                "QC-SYNC-001", src_rel, runtime_waivers, today_date
            )
            if runtime_match is not None:
                check["status"] = "skipped_with_reason_code"
                check["reason_code"] = (
                    "waiver_active_until:"
                    + runtime_match.get("waiver_id", "")
                    + ":"
                    + runtime_match.get("expires_at", "")
                )
            else:
                applicable = find_applicable_waivers("QC-SYNC-001", src_rel, waivers)
                valid, invalid_reasons = select_valid_waivers(applicable, today_iso)
                if valid:
                    check["status"] = "skipped_with_reason_code"
                    check["reason_code"] = (
                        "waivered_until:" + valid[0].get("expires_at", "")
                    )
                else:
                    check["status"] = "fail"
                    if invalid_reasons:
                        check["reason_code"] = "waiver_invalid:" + ";".join(invalid_reasons)
                    elif baseline_status not in ("drift", "missing_template", "missing_source"):
                        check["reason_code"] = "new_or_modified_drift_after_baseline"
                    else:
                        check["reason_code"] = "baseline_drift_changed_without_waiver"
        checks.append(check)

    # ------------------- Pass 2: post-baseline new pairs -------------------
    current_pairs = discover_current_pairs(repo_root)
    for src_rel, info in sorted(current_pairs.items()):
        if src_rel in baseline_src_paths:
            continue  # already handled in Pass 1
        tpl_rel = info["template_path"]
        src_path = repo_root / src_rel
        tpl_path = repo_root / tpl_rel
        current_src_sha = sha256_of_file(src_path)
        current_tpl_sha = sha256_of_file(tpl_path)
        current_status = _classify_current(current_src_sha, current_tpl_sha)

        check: Dict[str, Any] = {
            "gate_id": "QC-SYNC-001",
            "target": src_rel,
            "pair_classification": "post_baseline_new_pair",
            "expected": "post_baseline_new_pair_in_sync_or_valid_waiver",
            "actual": "current_status=" + str(current_status),
            "evidence_ref": "post_baseline_discovery:" + src_rel,
        }

        if current_status == "in_sync":
            check["status"] = "pass"
            check["reason_code"] = "post_baseline_new_pair_in_sync"
        else:
            runtime_match = find_runtime_waiver_for_target(
                "QC-SYNC-001", src_rel, runtime_waivers, today_date
            )
            if runtime_match is not None:
                check["status"] = "skipped_with_reason_code"
                check["reason_code"] = (
                    "post_baseline_new_pair_waiver_active_until:"
                    + runtime_match.get("waiver_id", "")
                    + ":"
                    + runtime_match.get("expires_at", "")
                )
            else:
                applicable = find_applicable_waivers("QC-SYNC-001", src_rel, waivers)
                valid, invalid_reasons = select_valid_waivers(applicable, today_iso)
                if valid:
                    check["status"] = "skipped_with_reason_code"
                    check["reason_code"] = (
                        "post_baseline_new_pair_waivered_until:"
                        + valid[0].get("expires_at", "")
                    )
                else:
                    check["status"] = "fail"
                    if invalid_reasons:
                        check["reason_code"] = (
                            "post_baseline_new_pair_waiver_invalid:" + ";".join(invalid_reasons)
                        )
                    elif current_status == "missing_template":
                        check["reason_code"] = "post_baseline_new_pair_missing_template"
                    elif current_status == "missing_source":
                        check["reason_code"] = "post_baseline_new_pair_missing_source"
                    elif current_status == "drift":
                        check["reason_code"] = "post_baseline_new_pair_drift"
                    else:
                        check["reason_code"] = "post_baseline_new_pair_unknown_status"
        checks.append(check)

    return checks


# ---------------------------------------------------------------------------
# QC-SCHEMA-001 minimal JSON schema / structure validation
# ---------------------------------------------------------------------------

REQUIRED_JSON_TARGETS: List[Tuple[str, Optional[str], List[str]]] = [
    (
        "governance-repair-manifest.v3.5.json",
        "governance-repair-manifest/v1",
        ["plan_version", "execution_order", "findings"],
    ),
    ("artifacts/status/TASK-1023.status.json", None, ["task_id", "state"]),
    ("artifacts/status/TASK-1024.status.json", None, ["task_id", "state"]),
    ("artifacts/status/TASK-1025.status.json", None, ["task_id", "state"]),
    (
        "artifacts/governance/quality-baseline.v3.5.json",
        "quality-baseline/v1",
        ["plan_version", "metrics", "source_template_pairs"],
    ),
    (
        "artifacts/governance/quality-gate-policy.v3.5.json",
        "quality-gate-policy/v1",
        ["gates", "rollout_phase"],
    ),
]


def run_qc_schema_001(repo_root: Path) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    for rel, expected_schema, required_keys in REQUIRED_JSON_TARGETS:
        path = repo_root / rel
        check: Dict[str, Any] = {
            "gate_id": "QC-SCHEMA-001",
            "target": rel,
            "evidence_ref": rel,
        }
        if not path.is_file():
            check["expected"] = "file_present"
            check["actual"] = "missing"
            check["status"] = "skipped_with_reason_code"
            check["reason_code"] = "file_not_present_yet"
            checks.append(check)
            continue
        try:
            data = load_json(path)
        except (json.JSONDecodeError, OSError) as e:
            check["expected"] = "valid_json"
            check["actual"] = "parse_error:" + type(e).__name__
            check["status"] = "fail"
            check["reason_code"] = "json_parse_error"
            checks.append(check)
            continue
        if expected_schema is not None:
            actual_schema = data.get("schema_version") if isinstance(data, dict) else None
            if actual_schema != expected_schema:
                check["expected"] = "schema_version=" + expected_schema
                check["actual"] = "schema_version=" + str(actual_schema)
                check["status"] = "fail"
                check["reason_code"] = "schema_version_mismatch"
                checks.append(check)
                continue
        missing_keys = [k for k in required_keys if not (isinstance(data, dict) and k in data)]
        if missing_keys:
            check["expected"] = "required_keys:" + ",".join(required_keys)
            check["actual"] = "missing:" + ",".join(missing_keys)
            check["status"] = "fail"
            check["reason_code"] = "missing_required_keys"
        else:
            check["expected"] = "required_keys_present:" + ",".join(required_keys)
            check["actual"] = "ok"
            check["status"] = "pass"
            check["reason_code"] = "schema_and_keys_ok"
        checks.append(check)
    return checks


# ---------------------------------------------------------------------------
# QC-IMPORT-001 import-time side-effect gate (subprocess; no __pycache__)
# ---------------------------------------------------------------------------

def run_qc_import_001(
    repo_root: Path, baseline: Dict[str, Any], policy: Dict[str, Any]
) -> List[Dict[str, Any]]:
    surface = baseline.get("import_side_effect_surface", []) or []
    gate_cfg = next(
        (g for g in policy.get("gates", []) if g.get("gate_id") == "QC-IMPORT-001"), {}
    )
    expected_clean = set(gate_cfg.get("expected_import_clean", []) or [])
    advisory_for_unlisted = bool(gate_cfg.get("first_cycle_advisory_for_unlisted_candidates", True))

    checks: List[Dict[str, Any]] = []
    for entry in surface:
        if not entry.get("candidate_for_import_side_effect_gate"):
            continue
        rel = entry.get("path", "")
        path = repo_root / rel
        check: Dict[str, Any] = {
            "gate_id": "QC-IMPORT-001",
            "target": rel,
            "expected": "import_clean_when_in_expected_clean_else_advisory",
            "evidence_ref": rel,
        }
        if not path.is_file():
            check["actual"] = "missing"
            check["status"] = "skipped_with_reason_code"
            check["reason_code"] = "file_not_found"
            checks.append(check)
            continue

        module_name = path.stem
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUTF8"] = "1"
        env["PYTHONNOUSERSITE"] = "1"
        code = (
            "import sys\n"
            "sys.path.insert(0, " + repr(str(path.parent)) + ")\n"
            "__import__(" + repr(module_name) + ")\n"
        )
        try:
            r = subprocess.run(
                [sys.executable, "-S", "-B", "-c", code],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(repo_root),
            )
        except subprocess.TimeoutExpired:
            check["actual"] = "timeout_30s"
            check["status"] = "fail" if rel in expected_clean else "advisory"
            check["reason_code"] = "import_timeout"
            checks.append(check)
            continue

        out_text = r.stdout or ""
        err_text = r.stderr or ""
        if r.returncode != 0:
            tail = err_text.strip()[-200:]
            check["actual"] = "exit=" + str(r.returncode) + "; stderr_tail=" + tail
            if rel in expected_clean:
                check["status"] = "fail"
                check["reason_code"] = "import_error_when_expected_clean"
            elif advisory_for_unlisted:
                check["status"] = "advisory"
                check["reason_code"] = "first_cycle_observation_import_error"
            else:
                check["status"] = "fail"
                check["reason_code"] = "import_error"
        elif out_text or err_text:
            check["actual"] = (
                "stdout_len=" + str(len(out_text))
                + "; stderr_len=" + str(len(err_text))
            )
            if rel in expected_clean:
                check["status"] = "fail"
                check["reason_code"] = "import_emitted_output_when_expected_clean"
            elif advisory_for_unlisted:
                check["status"] = "advisory"
                check["reason_code"] = "first_cycle_observation_dirty_import"
            else:
                check["status"] = "fail"
                check["reason_code"] = "import_emitted_output"
        else:
            check["actual"] = "stdout_and_stderr_empty;exit=0"
            check["status"] = "pass"
            check["reason_code"] = "import_clean"
        checks.append(check)
    return checks


# ---------------------------------------------------------------------------
# QC-GOLDEN-001 golden CLI harness bootstrap (no execution)
# ---------------------------------------------------------------------------

def run_qc_golden_001(repo_root: Path, baseline: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates = baseline.get("golden_cli_candidates", []) or []
    checks: List[Dict[str, Any]] = []
    for c in candidates:
        cmd_id = c.get("command_id", "")
        cmd = c.get("command", "")
        capture_policy = c.get("capture_policy", "")
        check: Dict[str, Any] = {
            "gate_id": "QC-GOLDEN-001",
            "target": cmd_id,
            "expected": "capture_policy=post_task_evidence_only_and_no_execution",
            "actual": "command=" + cmd + "; capture_policy=" + str(capture_policy),
            "evidence_ref": cmd_id,
        }
        if capture_policy == "post_task_evidence_only":
            check["status"] = "skipped_with_reason_code"
            check["reason_code"] = "post_task_evidence_only_capture_deferred"
        else:
            check["status"] = "fail"
            check["reason_code"] = "unsafe_capture_policy:" + str(capture_policy)
        checks.append(check)
    return checks


# ---------------------------------------------------------------------------
# QC-RUFF-001 advisory only (do NOT invoke ruff)
# ---------------------------------------------------------------------------

def run_qc_ruff_001(repo_root: Path) -> List[Dict[str, Any]]:
    config_files = ["ruff.toml", ".ruff.toml", "pyproject.toml"]
    found = [name for name in config_files if (repo_root / name).is_file()]
    return [
        {
            "gate_id": "QC-RUFF-001",
            "target": "ruff_config",
            "expected": "advisory_only_in_v3.5.0_no_invocation",
            "actual": "config_files_found=" + ",".join(found) if found else "no_config_found",
            "status": "advisory",
            "reason_code": "advisory_only_in_v3.5.0",
            "evidence_ref": "ruff_config_search",
        }
    ]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all_gates(
    repo_root: Path,
    baseline: Dict[str, Any],
    policy: Dict[str, Any],
    today_iso: str,
    runtime_waivers: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    checks.extend(run_qc_sync_001(repo_root, baseline, policy, today_iso, runtime_waivers))
    checks.extend(run_qc_schema_001(repo_root))
    checks.extend(run_qc_import_001(repo_root, baseline, policy))
    checks.extend(run_qc_golden_001(repo_root, baseline))
    checks.extend(run_qc_ruff_001(repo_root))
    return checks


def overall_status(checks: List[Dict[str, Any]]) -> str:
    return "fail" if any(c.get("status") == "fail" for c in checks) else "pass"


def build_result(
    repo_root: Path,
    baseline_path: Path,
    policy_path: Path,
    checks: List[Dict[str, Any]],
    today_iso: str,
    self_check: bool,
    waiver_policy_path: Optional[Path] = None,
    runtime_waiver_count: int = 0,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "schema_version": "quality-gate-result/v1",
        "task_id": "TASK-1025",
        "generated_at": today_iso,
        "self_check": self_check,
        "baseline_ref": str(baseline_path.relative_to(repo_root)).replace("\\", "/"),
        "policy_ref": str(policy_path.relative_to(repo_root)).replace("\\", "/"),
        "overall_status": overall_status(checks),
        "checks": checks,
        "limitations": [
            "Ruff is P1 advisory only and is not invoked.",
            "Golden CLI capture is post_task_evidence_only and deferred to a future task.",
            "Waiver discovery uses policy.waivers array; no global waiver registry in v3.5.0.",
            "Baseline-existing drift is allowed when sha256 unchanged from baseline.",
            "QC-IMPORT-001 first cycle treats unlisted candidates as advisory.",
            "TASK-1042 adds optional --waiver-policy <path> for explicit runtime waiver registry consumption applied to QC-SYNC-001 only.",
        ],
        "waiver_policy_ref": (
            str(waiver_policy_path).replace("\\", "/")
            if waiver_policy_path is not None
            else None
        ),
        "runtime_waiver_count": runtime_waiver_count,
    }
    return result


def main(argv: Optional[List[str]] = None) -> int:
    init_streams()
    parser = argparse.ArgumentParser(
        description="v3.5.0 baseline-aware P0 quality gate runner (TASK-1025)"
    )
    parser.add_argument("--baseline", default=None, help="path to quality-baseline.v3.5.json")
    parser.add_argument("--policy", default=None, help="path to quality-gate-policy.v3.5.json")
    parser.add_argument(
        "--waiver-policy",
        default=None,
        help=(
            "TASK-1042 explicit waiver registry path (waiver-policy-registry/v1). "
            "Applied to QC-SYNC-001 findings only. Without this flag the runner "
            "behaves identically to TASK-1025/TASK-1037 default mode."
        ),
    )
    parser.add_argument("--format", choices=["json"], default="json")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="dry-run; print result to stdout; do not write evidence file",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="optional evidence output path (only honored when --self-check is NOT set)",
    )
    args = parser.parse_args(argv)

    try:
        repo_root = detect_repo_root()
    except RuntimeError as e:
        print(json.dumps({"error": "repo_root_detection_failed", "detail": str(e)}))
        return 2

    baseline_path = (
        Path(args.baseline) if args.baseline
        else repo_root / "artifacts" / "governance" / "quality-baseline.v3.5.json"
    )
    policy_path = (
        Path(args.policy) if args.policy
        else repo_root / "artifacts" / "governance" / "quality-gate-policy.v3.5.json"
    )

    if not baseline_path.is_file():
        print(json.dumps({"error": "baseline_not_found", "path": str(baseline_path)}))
        return 2
    if not policy_path.is_file():
        print(json.dumps({"error": "policy_not_found", "path": str(policy_path)}))
        return 2

    baseline = load_json(baseline_path)
    policy = load_json(policy_path)
    today_iso = now_taipei_iso()

    runtime_waivers: List[Dict[str, Any]] = []
    waiver_policy_path: Optional[Path] = None
    if args.waiver_policy is not None:
        waiver_policy_path = Path(args.waiver_policy)
        if not waiver_policy_path.is_absolute():
            waiver_policy_path = repo_root / waiver_policy_path
        registry, load_err = load_runtime_waiver_registry(waiver_policy_path)
        if load_err is not None:
            print(json.dumps(load_err, ensure_ascii=False))
            return 2
        if registry is not None:
            runtime_waivers = list(registry.get("waivers", []) or [])

    checks = run_all_gates(repo_root, baseline, policy, today_iso, runtime_waivers)
    result = build_result(
        repo_root,
        baseline_path,
        policy_path,
        checks,
        today_iso,
        args.self_check,
        waiver_policy_path,
        len(runtime_waivers),
    )

    if args.output and not args.self_check:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = repo_root / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(json.dumps({"output_written": str(out_path), "overall_status": result["overall_status"]}))
    else:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    return 0 if result["overall_status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
