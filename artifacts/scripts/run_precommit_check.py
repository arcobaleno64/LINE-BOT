#!/usr/bin/env python3
"""v3.5.0 Minimal PCACC runner (TASK-1026 deliverable).

Pre-Commit Cross-Artifact Consistency Check. Runs four strict structural
checks against a target task's lifecycle artifacts:

    PCACC-001 lifecycle artifact set exists (task / plan / decision / verify / status)
    PCACC-002 Evidence Refs exist and match required format
    PCACC-003 status owner / reviewer references are canonical
    PCACC-004 review_timestamp > evidence_generated_at

PCACC v3.5.0 is structural only. It is NOT a reasoning-faithfulness audit,
NOT a belief-state audit, NOT a self-confidence audit. Output is JSON only;
no free-text rationale field is emitted. Status values are one of
{pass, fail, skipped_with_reason_code}.

Consumes:
- artifacts/governance/precommit-check-policy.v3.5.json (this task's policy)
- artifacts/{tasks,plans,decisions,verify,status}/<task_id>.<kind>.<ext>

Usage:
  python artifacts/scripts/run_precommit_check.py --task TASK-1026
  python artifacts/scripts/run_precommit_check.py --task TASK-1026 --self-check
  python artifacts/scripts/run_precommit_check.py --task TASK-1026 \
      --policy artifacts/governance/precommit-check-policy.v3.5.json \
      --output artifacts/verify/TASK-1026/precommit-check-result.json

Exit codes:
  0 = no blocking failures (overall_status == pass)
  1 = at least one blocking PCACC check failed
  2 = invocation error / missing inputs
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_PATH = Path(__file__).resolve()
TAIPEI_TZ = timezone(timedelta(hours=8))

LIFECYCLE_KINDS: Tuple[Tuple[str, str, str], ...] = (
    ("task", "artifacts/tasks", "task.md"),
    ("plan", "artifacts/plans", "plan.md"),
    ("decision", "artifacts/decisions", "decision.md"),
    ("verify", "artifacts/verify", "verify.md"),
    ("status", "artifacts/status", "status.json"),
)

REQUIRED_CHECK_FIELDS = (
    "check_id",
    "target",
    "expected",
    "actual",
    "evidence_ref",
    "status",
    "reason_code",
)

ALLOWED_STATUS_VALUES = ("pass", "fail", "skipped_with_reason_code")

# TASK-1035 Evidence Ref policy registry (controlled runtime extraction).
# Default behavior without --evidence-ref-policy remains unchanged.
EVIDENCE_REF_REGISTRY_SCHEMA_VERSION = "evidence-ref-policy/v1"
EVIDENCE_REF_REGISTRY_REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version",
    "plan_version",
    "created_by_task",
    "runtime_status",
    "runtime_consumption_authorized",
    "source_policy_refs",
    "policy_surface",
    "allowed_ref_prefixes",
    "ref_format_rules",
    "local_artifact_constraints",
    "required_ref_contexts",
    "optional_ref_contexts",
    "malformed_ref_behavior",
    "missing_ref_behavior",
    "pcacc_compatibility",
    "failure_semantics",
    "non_authorization",
    "limitations",
)
EVIDENCE_REF_REGISTRY_PREFIX_KIND_ENUM = (
    "local_repo_relative_directory",
    "local_repo_relative_filename_prefix",
    "git_scheme_token",
    "git_scheme_regex",
    "inline_metadata_token",
)
EVIDENCE_REF_REGISTRY_REQUIRED_LOCAL_CONSTRAINTS = (
    "must_be_relative_path",
    "must_not_escape_repo_root",
    "must_not_contain_parent_traversal",
    "must_not_be_absolute",
    "must_not_use_windows_drive_letter",
    "must_use_forward_slashes",
    "must_be_normalized",
)
EVIDENCE_REF_REGISTRY_REQUIRED_FORBIDDEN_URL_SCHEMES = (
    "http://",
    "https://",
    "ftp://",
    "file://",
    "ssh://",
    "git://",
    "git+ssh://",
)
EVIDENCE_REF_REGISTRY_REQUIRED_FORBIDDEN_ROOT_DIRS = (
    ".obsidian",
    ".omc",
    ".tmp",
    ".pytest-basetemp",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".venv",
    ".git",
)
EVIDENCE_REF_REGISTRY_PCACC_ACTIVE_SURFACE = (
    "PCACC-001",
    "PCACC-002",
    "PCACC-003",
    "PCACC-004",
)
EVIDENCE_REF_REGISTRY_ORC_REASON_CODE_RE = re.compile(
    r"evidence_refs_optional_per_orc_([A-Za-z0-9_\-]+)"
)


class EvidenceRefRegistryError(Exception):
    """Raised when an explicitly supplied Evidence Ref policy registry fails to load or validate."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(reason_code if not detail else reason_code + ":" + detail)


# ---------------------------------------------------------------------------
# Stream init (CLI entrypoint only; no import-time side-effect)
# ---------------------------------------------------------------------------

def init_streams(stdout: Any = None, stderr: Any = None) -> None:
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
        and (parent / "artifacts" / "governance").is_dir()
        and (parent / "template").is_dir()
    ]
    if not matches:
        raise RuntimeError(f"Unable to detect repo root from {SCRIPT_PATH}")
    return matches[-1]


def now_taipei_iso() -> str:
    return datetime.now(TAIPEI_TZ).replace(microsecond=0).isoformat()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Markdown metadata + section helpers
# ---------------------------------------------------------------------------

METADATA_KEY_RE = re.compile(r"^-\s+([A-Za-z][A-Za-z0-9 _\-]*?):\s*(.*?)\s*$")


def parse_metadata_block(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    in_block = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Metadata"):
            in_block = True
            continue
        if in_block:
            if stripped.startswith("## "):
                break
            m = METADATA_KEY_RE.match(stripped)
            if m:
                out[m.group(1).strip()] = m.group(2).strip()
    return out


def extract_section(text: str, heading: str) -> Optional[List[str]]:
    """Return list of non-empty stripped lines under '## {heading}' until next H2."""
    target = "## " + heading
    lines = text.splitlines()
    out: List[str] = []
    capture = False
    for line in lines:
        stripped = line.rstrip()
        if stripped.strip() == target:
            capture = True
            continue
        if capture and stripped.lstrip().startswith("## "):
            break
        if capture:
            s = stripped.strip()
            if s:
                out.append(s)
    return out if capture else None


def parse_evidence_refs(text: str) -> Optional[List[str]]:
    section = extract_section(text, "Evidence Refs")
    if section is None:
        return None
    refs: List[str] = []
    for raw in section:
        line = raw.lstrip("-").strip()
        if not line:
            continue
        if line.lower() == "none":
            return []
        if "(" in line and line.startswith("["):
            m = re.search(r"\]\(([^)]+)\)", line)
            if m:
                line = m.group(1).strip()
        if " " in line and not line.startswith("HEAD") and "://" not in line:
            line = line.split(" ", 1)[0]
        refs.append(line)
    return refs


def load_evidence_ref_registry(path: Path) -> Dict[str, Any]:
    """TASK-1035 controlled runtime extraction.

    Load and strictly validate the Evidence Ref policy registry from an explicit path.
    Fails closed (raises EvidenceRefRegistryError) on missing file, malformed JSON,
    schema_version mismatch, missing required top-level field, unknown enum value,
    forbidden pattern, invalid local-artifact constraint, or PCACC-002 conflict.
    Never silently falls back to in-module default.
    """
    if not path.is_file():
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_missing",
            str(path).replace("\\", "/"),
        )
    try:
        data = load_json(path)
    except json.JSONDecodeError:
        raise EvidenceRefRegistryError("evidence_ref_registry_malformed_json")
    except OSError as e:
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_io_error", type(e).__name__
        )

    if not isinstance(data, dict):
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_malformed_json", "top_level_not_object"
        )

    if data.get("schema_version") != EVIDENCE_REF_REGISTRY_SCHEMA_VERSION:
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_schema_version_mismatch",
            str(data.get("schema_version")),
        )

    for field in EVIDENCE_REF_REGISTRY_REQUIRED_TOP_LEVEL_FIELDS:
        if field not in data:
            raise EvidenceRefRegistryError(
                "evidence_ref_registry_missing_required_field", field
            )

    if data.get("runtime_consumption_authorized") is not True:
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_runtime_consumption_not_authorized"
        )

    prefixes = data.get("allowed_ref_prefixes")
    if not isinstance(prefixes, list) or not prefixes:
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_invalid_allowed_ref_prefixes",
            "must_be_non_empty_list",
        )
    for entry in prefixes:
        if not isinstance(entry, dict):
            raise EvidenceRefRegistryError(
                "evidence_ref_registry_invalid_allowed_ref_prefixes",
                "entry_not_object",
            )
        kind = entry.get("kind")
        if kind not in EVIDENCE_REF_REGISTRY_PREFIX_KIND_ENUM:
            raise EvidenceRefRegistryError(
                "evidence_ref_registry_unknown_enum_value",
                "allowed_ref_prefixes.kind=" + str(kind),
            )

    constraints = data.get("local_artifact_constraints")
    if not isinstance(constraints, dict):
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_invalid_local_artifact_constraint",
            "must_be_object",
        )
    for key in EVIDENCE_REF_REGISTRY_REQUIRED_LOCAL_CONSTRAINTS:
        if constraints.get(key) is not True:
            raise EvidenceRefRegistryError(
                "evidence_ref_registry_invalid_local_artifact_constraint", key
            )
    forbidden_url_schemes = constraints.get("forbidden_url_schemes") or []
    for required_scheme in EVIDENCE_REF_REGISTRY_REQUIRED_FORBIDDEN_URL_SCHEMES:
        if required_scheme not in forbidden_url_schemes:
            raise EvidenceRefRegistryError(
                "evidence_ref_registry_forbidden_pattern",
                "missing_forbidden_url_scheme:" + required_scheme,
            )
    forbidden_roots = constraints.get("forbidden_root_directories") or []
    for required_root in EVIDENCE_REF_REGISTRY_REQUIRED_FORBIDDEN_ROOT_DIRS:
        if required_root not in forbidden_roots:
            raise EvidenceRefRegistryError(
                "evidence_ref_registry_forbidden_pattern",
                "missing_forbidden_root_directory:" + required_root,
            )

    pcacc_compat = data.get("pcacc_compatibility")
    if not isinstance(pcacc_compat, dict):
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_pcacc_002_conflict",
            "pcacc_compatibility_missing_or_not_object",
        )
    if pcacc_compat.get("prototype_introduces_pcacc_005") is True:
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_pcacc_002_conflict",
            "pcacc_005_introduction_disallowed",
        )
    if pcacc_compat.get("prototype_changes_pcacc_active_count") is True:
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_pcacc_002_conflict",
            "active_count_change_disallowed",
        )
    surface = pcacc_compat.get("current_pcacc_active_check_surface")
    if list(surface or ()) != list(EVIDENCE_REF_REGISTRY_PCACC_ACTIVE_SURFACE):
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_pcacc_002_conflict",
            "active_check_surface_mismatch",
        )
    if pcacc_compat.get("ac_to_verify_coverage_activated") is True:
        raise EvidenceRefRegistryError(
            "evidence_ref_registry_pcacc_002_conflict",
            "ac_to_verify_coverage_activation_disallowed",
        )

    return data


def lifecycle_paths(repo_root: Path, task_id: str) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    for kind, folder, suffix in LIFECYCLE_KINDS:
        out[kind] = repo_root / folder / (task_id + "." + suffix)
    return out


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

ISO_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$"
)


def is_iso_timestamp(value: Any) -> bool:
    return isinstance(value, str) and bool(ISO_TS_RE.match(value))


def collect_review_timestamp(
    status_data: Optional[Dict[str, Any]],
    verify_meta: Dict[str, str],
) -> Tuple[Optional[str], str]:
    if status_data and is_iso_timestamp(status_data.get("last_updated")):
        return status_data["last_updated"], "status.last_updated"
    raw_v = verify_meta.get("Last Updated", "")
    if is_iso_timestamp(raw_v):
        return raw_v, "verify.Last Updated"
    return None, "no_review_timestamp_present"


def collect_evidence_generated_at(
    repo_root: Path, task_id: str, status_data: Optional[Dict[str, Any]]
) -> Tuple[Optional[str], str, Optional[str]]:
    """Return (timestamp, source_label, evidence_ref_path).

    Search order:
      1. status.self_check_result_ref -> JSON.generated_at
      2. artifacts/verify/<task>/precommit-check-result.json -> generated_at
      3. artifacts/verify/<task>/<*>.json -> first generated_at found (deterministic order)
    """
    if status_data:
        ref = status_data.get("self_check_result_ref")
        if isinstance(ref, str) and ref:
            p = repo_root / ref
            if p.is_file():
                try:
                    data = load_json(p)
                except (json.JSONDecodeError, OSError):
                    data = None
                if isinstance(data, dict) and is_iso_timestamp(data.get("generated_at")):
                    return data["generated_at"], "status.self_check_result_ref", ref

    pcacc_path = repo_root / "artifacts" / "verify" / task_id / "precommit-check-result.json"
    if pcacc_path.is_file():
        try:
            data = load_json(pcacc_path)
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, dict) and is_iso_timestamp(data.get("generated_at")):
            rel = "artifacts/verify/" + task_id + "/precommit-check-result.json"
            return data["generated_at"], "pcacc_result.generated_at", rel

    evidence_dir = repo_root / "artifacts" / "verify" / task_id
    if evidence_dir.is_dir():
        for child in sorted(evidence_dir.glob("*.json")):
            if child.name == "precommit-check-result.json":
                continue
            try:
                data = load_json(child)
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data, dict) and is_iso_timestamp(data.get("generated_at")):
                rel = (
                    "artifacts/verify/" + task_id + "/" + child.name
                )
                return data["generated_at"], "evidence_dir.generated_at", rel

    return None, "no_evidence_generated_at_found", None


# ---------------------------------------------------------------------------
# PCACC-001 lifecycle artifact set exists
# ---------------------------------------------------------------------------

def run_pcacc_001(repo_root: Path, task_id: str) -> Dict[str, Any]:
    paths = lifecycle_paths(repo_root, task_id)
    missing: List[str] = []
    present: List[str] = []
    for kind, p in paths.items():
        if p.is_file():
            present.append(kind)
        else:
            missing.append(kind)
    check: Dict[str, Any] = {
        "check_id": "PCACC-001",
        "target": task_id,
        "expected": "all_lifecycle_artifacts_present:task,plan,decision,verify,status",
        "actual": "present=" + ",".join(present) + ";missing=" + ",".join(missing),
        "evidence_ref": "lifecycle_paths_for_" + task_id,
    }
    if not missing:
        check["status"] = "pass"
        check["reason_code"] = "lifecycle_complete"
    else:
        check["status"] = "fail"
        check["reason_code"] = "lifecycle_missing:" + ",".join(missing)
    return check


# ---------------------------------------------------------------------------
# PCACC-002 Evidence Refs exist and match required format
# ---------------------------------------------------------------------------

def run_pcacc_002(
    repo_root: Path,
    task_id: str,
    evidence_ref_registry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    verify_path = repo_root / "artifacts" / "verify" / (task_id + ".verify.md")
    rel_evidence = "artifacts/verify/" + task_id + ".verify.md#Evidence Refs"
    check: Dict[str, Any] = {
        "check_id": "PCACC-002",
        "target": task_id,
        "expected": "evidence_refs_section_nonempty_and_paths_resolvable",
        "evidence_ref": rel_evidence,
    }
    if not verify_path.is_file():
        check["actual"] = "verify_artifact_missing"
        check["status"] = "skipped_with_reason_code"
        check["reason_code"] = "verify_artifact_missing"
        return check

    text = read_text(verify_path)
    refs = parse_evidence_refs(text)
    if refs is None:
        check["actual"] = "evidence_refs_section_absent"
        check["status"] = "fail"
        check["reason_code"] = "evidence_refs_section_absent"
        return check
    if not refs:
        # TASK-1035: under registry-driven mode, an empty Evidence Refs section
        # may be optionally skipped if the verify artifact carries an explicit
        # ORC reason_code marker (evidence_refs_optional_per_orc_<id>).
        # Default in-module behavior continues to fail on empty section.
        if evidence_ref_registry is not None:
            orc_match = EVIDENCE_REF_REGISTRY_ORC_REASON_CODE_RE.search(text)
            if orc_match:
                check["actual"] = "evidence_refs_section_empty_with_orc_reason_code"
                check["status"] = "skipped_with_reason_code"
                check["reason_code"] = "evidence_refs_optional_per_orc_" + orc_match.group(1)
                return check
        check["actual"] = "evidence_refs_section_empty_or_none"
        check["status"] = "fail"
        check["reason_code"] = "evidence_refs_section_empty"
        return check

    malformed: List[str] = []
    missing: List[str] = []
    resolved: List[str] = []
    # TASK-1035: registry-mode forbidden-pattern sieve. Default mode is unchanged
    # (these locals stay empty / False), so TASK-1030 NEG-002 / NEG-003 outcomes
    # are byte-identical without the flag.
    forbidden_schemes_to_check: List[str] = []
    forbidden_roots_to_check: List[str] = []
    parent_traversal_forbidden = False
    if evidence_ref_registry is not None:
        _constraints = evidence_ref_registry.get("local_artifact_constraints", {}) or {}
        forbidden_schemes_to_check = list(_constraints.get("forbidden_url_schemes") or [])
        forbidden_roots_to_check = list(_constraints.get("forbidden_root_directories") or [])
        parent_traversal_forbidden = (
            _constraints.get("must_not_contain_parent_traversal") is True
        )
    for ref in refs:
        if evidence_ref_registry is not None:
            if any(ref.startswith(s) for s in forbidden_schemes_to_check):
                malformed.append(ref)
                continue
            if parent_traversal_forbidden and "../" in ref:
                malformed.append(ref)
                continue
            if any(
                ref.startswith(fr + "/") or ref == fr
                for fr in forbidden_roots_to_check
            ):
                malformed.append(ref)
                continue
        if "://" in ref or ref.startswith("/") or (len(ref) >= 2 and ref[1] == ":"):
            if ref.startswith("HEAD") or re.match(r"^[A-Za-z]+\s*[:=]", ref):
                resolved.append(ref)
                continue
            malformed.append(ref)
            continue
        if ref.startswith("HEAD") or "=" in ref or ref.startswith("commit"):
            resolved.append(ref)
            continue
        if ref.startswith("artifacts/") or ref.startswith("template/") or ref.startswith("docs/") \
                or ref.startswith("council-forge-") or ref.startswith("governance-repair-") \
                or ref.startswith(".github/"):
            target = repo_root / ref
            if target.is_file() or target.is_dir():
                resolved.append(ref)
            else:
                missing.append(ref)
            continue
        if ref.lower().startswith("commit ") or re.match(r"^[0-9a-f]{7,40}$", ref):
            resolved.append(ref)
            continue
        malformed.append(ref)

    check["actual"] = (
        "ref_count=" + str(len(refs))
        + ";resolved=" + str(len(resolved))
        + ";missing=" + str(len(missing))
        + ";malformed=" + str(len(malformed))
    )
    if missing or malformed:
        check["status"] = "fail"
        parts: List[str] = []
        if missing:
            parts.append("missing_paths:" + ",".join(missing[:5]))
        if malformed:
            parts.append("malformed_refs:" + ",".join(malformed[:5]))
        check["reason_code"] = ";".join(parts)
    else:
        check["status"] = "pass"
        check["reason_code"] = "evidence_refs_resolved"
    return check


# ---------------------------------------------------------------------------
# PCACC-003 canonical owner / reviewer references
# ---------------------------------------------------------------------------

def _canonical_set(policy: Dict[str, Any], key: str) -> List[str]:
    pcacc_003 = next(
        (c for c in policy.get("checks", []) if c.get("check_id") == "PCACC-003"),
        {},
    )
    val = pcacc_003.get(key) or []
    return [str(v) for v in val if isinstance(v, (str,))]


def run_pcacc_003(
    repo_root: Path, task_id: str, policy: Dict[str, Any]
) -> Dict[str, Any]:
    canonical_reviewers = _canonical_set(policy, "canonical_reviewers")
    canonical_owners = _canonical_set(policy, "canonical_owners")
    rel_status = "artifacts/status/" + task_id + ".status.json"
    rel_task = "artifacts/tasks/" + task_id + ".task.md"

    check: Dict[str, Any] = {
        "check_id": "PCACC-003",
        "target": task_id,
        "expected": (
            "status.current_owner in " + ",".join(canonical_owners)
            + ";task.Owner in " + ",".join(canonical_owners)
            + ";final_approver_or_reviewer in " + ",".join(canonical_reviewers)
        ),
        "evidence_ref": rel_status + ";" + rel_task,
    }
    status_path = repo_root / rel_status
    task_path = repo_root / rel_task
    if not status_path.is_file() or not task_path.is_file():
        check["actual"] = "status_or_task_missing"
        check["status"] = "skipped_with_reason_code"
        check["reason_code"] = "status_or_task_missing"
        return check

    if not canonical_reviewers or not canonical_owners:
        check["actual"] = "canonical_set_empty"
        check["status"] = "skipped_with_reason_code"
        check["reason_code"] = "canonical_registry_missing_in_policy"
        return check

    try:
        status_data = load_json(status_path)
    except (json.JSONDecodeError, OSError) as e:
        check["actual"] = "status_parse_error:" + type(e).__name__
        check["status"] = "fail"
        check["reason_code"] = "status_parse_error"
        return check
    task_meta = parse_metadata_block(read_text(task_path))

    failures: List[str] = []
    current_owner = str(status_data.get("current_owner", ""))
    if current_owner and current_owner not in canonical_owners:
        failures.append("status.current_owner=" + current_owner)
    task_owner = task_meta.get("Owner", "")
    if task_owner and task_owner not in canonical_owners:
        failures.append("task.Owner=" + task_owner)

    text = read_text(task_path)
    final_approver = ""
    m = re.search(r"final_approver:\s*(?:\n[^A-Za-z]*reviewer_id:\s*([^\s\n]+))", text)
    if m:
        final_approver = m.group(1).strip()
    if final_approver and final_approver not in canonical_reviewers:
        failures.append("final_approver.reviewer_id=" + final_approver)

    check["actual"] = (
        "current_owner=" + (current_owner or "<empty>")
        + ";task.Owner=" + (task_owner or "<empty>")
        + ";final_approver=" + (final_approver or "<empty>")
    )
    if failures:
        check["status"] = "fail"
        check["reason_code"] = "non_canonical:" + ";".join(failures)
    else:
        check["status"] = "pass"
        check["reason_code"] = "owner_and_reviewer_canonical"
    return check


# ---------------------------------------------------------------------------
# PCACC-004 review timestamp follows evidence generation timestamp
# ---------------------------------------------------------------------------

def run_pcacc_004(repo_root: Path, task_id: str) -> Dict[str, Any]:
    status_path = repo_root / "artifacts" / "status" / (task_id + ".status.json")
    verify_path = repo_root / "artifacts" / "verify" / (task_id + ".verify.md")
    status_data: Optional[Dict[str, Any]] = None
    if status_path.is_file():
        try:
            status_data = load_json(status_path)
        except (json.JSONDecodeError, OSError):
            status_data = None
    verify_meta: Dict[str, str] = {}
    if verify_path.is_file():
        verify_meta = parse_metadata_block(read_text(verify_path))

    review_ts, review_src = collect_review_timestamp(status_data, verify_meta)
    evidence_ts, evidence_src, evidence_ref = collect_evidence_generated_at(
        repo_root, task_id, status_data
    )

    check: Dict[str, Any] = {
        "check_id": "PCACC-004",
        "target": task_id,
        "expected": "review_timestamp_strictly_after_evidence_generated_at",
        "evidence_ref": evidence_ref or ("status:" + str(status_path.relative_to(repo_root)).replace("\\", "/")),
        "actual": (
            "review_ts=" + (review_ts or "<missing>")
            + "(" + review_src + ")"
            + ";evidence_ts=" + (evidence_ts or "<missing>")
            + "(" + evidence_src + ")"
        ),
    }

    if review_ts is None and evidence_ts is None:
        check["status"] = "skipped_with_reason_code"
        check["reason_code"] = "no_review_or_evidence_timestamp"
        return check
    if review_ts is None:
        check["status"] = "skipped_with_reason_code"
        check["reason_code"] = "no_review_timestamp"
        return check
    if evidence_ts is None:
        check["status"] = "skipped_with_reason_code"
        check["reason_code"] = "no_evidence_generated_at"
        return check
    if review_ts > evidence_ts:
        check["status"] = "pass"
        check["reason_code"] = "review_after_evidence"
    elif review_ts == evidence_ts:
        check["status"] = "fail"
        check["reason_code"] = "review_equal_to_evidence_not_strictly_after"
    else:
        check["status"] = "fail"
        check["reason_code"] = "review_before_evidence"
    return check


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_all_checks(
    repo_root: Path,
    task_id: str,
    policy: Dict[str, Any],
    evidence_ref_registry: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    checks: List[Dict[str, Any]] = []
    checks.append(run_pcacc_001(repo_root, task_id))
    checks.append(run_pcacc_002(repo_root, task_id, evidence_ref_registry))
    checks.append(run_pcacc_003(repo_root, task_id, policy))
    checks.append(run_pcacc_004(repo_root, task_id))
    return checks


def overall_status(checks: List[Dict[str, Any]]) -> str:
    return "fail" if any(c.get("status") == "fail" for c in checks) else "pass"


def validate_policy(policy: Dict[str, Any]) -> Optional[str]:
    if policy.get("schema_version") != "precommit-check-policy/v1":
        return "schema_version_mismatch"
    if policy.get("plan_version") != "v3.5.0":
        return "plan_version_mismatch"
    checks = policy.get("checks") or []
    if len(checks) != 4:
        return "checks_count_must_be_exactly_4_got_" + str(len(checks))
    expected_ids = {"PCACC-001", "PCACC-002", "PCACC-003", "PCACC-004"}
    actual_ids = {c.get("check_id") for c in checks}
    if actual_ids != expected_ids:
        return "checks_ids_mismatch"
    op = policy.get("output_policy") or {}
    if op.get("format") != "json":
        return "output_policy_format_must_be_json"
    if op.get("free_text_rationale") is not False:
        return "output_policy_free_text_rationale_must_be_false"
    return None


def build_result(
    repo_root: Path,
    task_id: str,
    policy_path: Path,
    checks: List[Dict[str, Any]],
    today_iso: str,
    self_check: bool,
) -> Dict[str, Any]:
    return {
        "schema_version": "precommit-check-result/v1",
        "task_id": task_id,
        "generated_at": today_iso,
        "self_check": self_check,
        "policy_ref": str(policy_path.relative_to(repo_root)).replace("\\", "/"),
        "overall_status": overall_status(checks),
        "checks": checks,
        "limitations": [
            "PCACC v3.5.0 is structural only; not a reasoning-faithfulness audit.",
            "PCACC-003 canonical reviewer set is sourced from policy; missing registry yields explicit reason_code, not silent pass.",
            "PCACC-004 timestamp comparison is strict (review_ts > evidence_ts); equal timestamps fail.",
            "Missing review_timestamp or evidence_generated_at returns skipped_with_reason_code, never silent pass.",
            "PCACC detects violations only; resolution flows through the existing decision artifact workflow.",
        ],
    }


def main(argv: Optional[List[str]] = None) -> int:
    init_streams()
    parser = argparse.ArgumentParser(
        description="v3.5.0 Minimal PCACC runner (TASK-1026)"
    )
    parser.add_argument("--task", required=False, default="TASK-1026", help="target task id (e.g. TASK-1026)")
    parser.add_argument("--policy", default=None, help="path to precommit-check-policy.v3.5.json")
    parser.add_argument(
        "--evidence-ref-policy",
        default=None,
        dest="evidence_ref_policy",
        help="optional Evidence Ref policy registry path (TASK-1035; explicit activation only; fail-closed exit 2 on load failure)",
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

    policy_path = (
        Path(args.policy) if args.policy
        else repo_root / "artifacts" / "governance" / "precommit-check-policy.v3.5.json"
    )
    if not policy_path.is_file():
        print(json.dumps({"error": "policy_not_found", "path": str(policy_path)}))
        return 2

    policy = load_json(policy_path)
    policy_err = validate_policy(policy)
    if policy_err:
        print(json.dumps({"error": "policy_invalid", "detail": policy_err}))
        return 2

    task_id = str(args.task or "").strip()
    if not re.match(r"^TASK-\d+$", task_id):
        print(json.dumps({"error": "invalid_task_id", "value": task_id}))
        return 2

    evidence_ref_registry: Optional[Dict[str, Any]] = None
    if args.evidence_ref_policy:
        erp_path = Path(args.evidence_ref_policy)
        if not erp_path.is_absolute():
            erp_path = repo_root / erp_path
        try:
            evidence_ref_registry = load_evidence_ref_registry(erp_path)
        except EvidenceRefRegistryError as e:
            print(json.dumps({
                "error": "evidence_ref_registry_load_failed",
                "reason_code": e.reason_code,
                "detail": e.detail,
                "path": str(erp_path).replace("\\", "/"),
            }))
            return 2

    today_iso = now_taipei_iso()
    checks = run_all_checks(repo_root, task_id, policy, evidence_ref_registry)
    result = build_result(repo_root, task_id, policy_path, checks, today_iso, args.self_check)

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
