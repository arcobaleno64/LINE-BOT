"""Shared constants for workflow guard scripts."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

REQUIRED_TOPICS = {
    "multi-agent",
    "developer-tools",
    "workflow-template",
    "artifact-first",
    "gate-guarded",
    "premortem",
}

TOPIC_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

DEFAULT_ASSURANCE_LEVEL = "poc"
DEFAULT_PROJECT_ADAPTER = "generic"

ASSURANCE_LEVELS = (
    "poc",
    "mvp",
    "production",
)

PROJECT_ADAPTERS = (
    "generic",
    "web-app",
    "backend-service",
    "batch-etl",
    "cli-tool",
    "docs-spec",
    "resource-constrained-ui",
)

WORKFLOW_STATES = (
    "drafted",
    "researched",
    "planned",
    "coding",
    "testing",
    "verifying",
    "done",
    "blocked",
)

ARTIFACT_TYPES = (
    "task",
    "research",
    "plan",
    "code",
    "test",
    "verify",
    "decision",
    "improvement",
    "status",
)

STRUCTURED_CHECKLIST_FIELDS = (
    "criterion",
    "method",
    "evidence",
    "result",
    "reviewer",
    "timestamp",
)

RACI_MATRIX = {
    "Claude Code": {"task", "plan", "decision", "status"},
    "Gemini CLI": {"research", "Tavily Cache", "Remember Capture draft"},
    "Codex CLI": {"code"},
    "Implementer": {"code (實檔修改)"},
    "Tester": {"test"},
    "Verifier": {"verify"},
    "Reviewer": {"review notes"},
}

VERIFICATION_ITEM_RESULTS = (
    "verified",
    "unverified",
    "unverifiable",
    "deferred",
)

VERIFICATION_REASON_CODES = (
    "NO_RUNTIME_ENV",
    "THIRD_PARTY_BLOCKED",
    "MANUAL_CHECK_DEFERRED",
    "NON_DETERMINISTIC_RUNTIME",
    "NOT_APPLICABLE_BY_ADAPTER",
)

VERIFICATION_READINESS_STATES = (
    "poc",
    "mvp",
    "production-blocked",
    "production-ready",
)

DECISION_CLASSES = (
    "scope-drift-waiver",
    "risk-acceptance",
    "defer",
    "reject",
    "conflict-resolution",
)

GOVERNANCE_DECISION_CLASS_PREFIX = "governance-"


def is_governance_decision_class(value: str) -> bool:
    """Return True iff `value` is a governance-family Decision Class (v2 schema).

    A governance-family class is any string that starts with `governance-`
    (case-insensitive) and carries a non-empty subclass token after the prefix.
    Empty subclass (just `governance-` or `governance-   `) is rejected.

    See docs/artifact_schema.md §5.13 for the v2 governance extension.
    """
    if not isinstance(value, str):
        return False
    lowered = value.strip().lower()
    if not lowered.startswith(GOVERNANCE_DECISION_CLASS_PREFIX):
        return False
    subclass = lowered[len(GOVERNANCE_DECISION_CLASS_PREFIX):].strip()
    return bool(subclass)

IMPROVEMENT_PROFILES = (
    "gate-e",
    "retrospective",
)

ASSURANCE_PROFILE_FIELDS = (
    "required_artifacts_by_state",
    "verify_required_fields",
    "verify_required_sections",
    "allow_deferred",
    "allow_unverifiable",
    "requires_manual_review",
    "default_verification_readiness",
    "status_debt_results",
)

ASSURANCE_PROFILES = {
    "poc": {
        "required_artifacts_by_state": {
            "drafted": {"task", "status"},
            "researched": {"task", "research", "status"},
            "planned": {"task", "plan", "status"},
            "coding": {"task", "plan", "status"},
            "testing": {"task", "plan", "code", "status"},
            "verifying": {"task", "plan", "code", "verify", "status"},
            "done": {"task", "code", "verify", "status"},
            "blocked": {"task", "status"},
        },
        "verify_required_fields": {"criterion", "method", "evidence", "result"},
        "verify_required_sections": {
            "Verification Summary",
            "Acceptance Criteria Checklist",
            "Overall Maturity",
            "Deferred Items",
            "Pass Fail Result",
        },
        "allow_deferred": True,
        "allow_unverifiable": True,
        "requires_manual_review": False,
        "default_verification_readiness": "poc",
        "status_debt_results": {"unverified", "deferred"},
    },
    "mvp": {
        "required_artifacts_by_state": {
            "drafted": {"task", "status"},
            "researched": {"task", "research", "status"},
            "planned": {"task", "plan", "research", "status"},
            "coding": {"task", "plan", "research", "status"},
            "testing": {"task", "plan", "research", "code", "test", "status"},
            "verifying": {"task", "plan", "research", "code", "test", "verify", "status"},
            "done": {"task", "plan", "code", "test", "verify", "status"},
            "blocked": {"task", "status"},
        },
        "verify_required_fields": {"criterion", "method", "evidence", "result"},
        "verify_required_sections": {
            "Verification Summary",
            "Acceptance Criteria Checklist",
            "Overall Maturity",
            "Deferred Items",
            "Decision Refs",
            "Evidence Refs",
            "Pass Fail Result",
        },
        "allow_deferred": True,
        "allow_unverifiable": True,
        "requires_manual_review": False,
        "default_verification_readiness": "mvp",
        "status_debt_results": {"unverified", "deferred"},
    },
    "production": {
        "required_artifacts_by_state": {
            "drafted": {"task", "status"},
            "researched": {"task", "research", "status"},
            "planned": {"task", "plan", "research", "status"},
            "coding": {"task", "plan", "research", "status"},
            "testing": {"task", "plan", "research", "code", "test", "status"},
            "verifying": {"task", "plan", "research", "code", "test", "verify", "status"},
            "done": {"task", "plan", "research", "code", "test", "verify", "status"},
            "blocked": {"task", "status"},
        },
        "verify_required_fields": {"criterion", "method", "evidence", "result", "reviewer", "timestamp"},
        "verify_required_sections": {
            "Verification Summary",
            "Acceptance Criteria Checklist",
            "Overall Maturity",
            "Deferred Items",
            "Decision Refs",
            "Evidence Refs",
            "Pass Fail Result",
            "Build Guarantee",
        },
        "allow_deferred": False,
        "allow_unverifiable": False,
        "requires_manual_review": True,
        "default_verification_readiness": "production-blocked",
        "status_debt_results": {"unverified", "deferred", "unverifiable"},
    },
}

PROJECT_ADAPTER_RULES = {
    "generic": {
        "inherits": None,
        "artifact_overrides_by_state": {},
        "verify_section_overrides": set(),
        "verify_field_overrides": set(),
        "allowed_reason_codes": {
            "NO_RUNTIME_ENV",
            "THIRD_PARTY_BLOCKED",
            "MANUAL_CHECK_DEFERRED",
            "NON_DETERMINISTIC_RUNTIME",
        },
        "forbidden_reason_codes": set(),
        "requires_build_guarantee": False,
    },
    "docs-spec": {
        "inherits": "generic",
        "artifact_overrides_by_state": {
            "testing": {"test": False, "code": False},
            "verifying": {"test": False, "code": False},
            "done": {"test": False, "code": False},
        },
        "verify_section_overrides": set(),
        "verify_field_overrides": set(),
        "allowed_reason_codes": {"NOT_APPLICABLE_BY_ADAPTER"},
        "forbidden_reason_codes": set(),
        "requires_build_guarantee": False,
    },
    "web-app": {
        "inherits": "generic",
        "artifact_overrides_by_state": {},
        "verify_section_overrides": {"Build Guarantee"},
        "verify_field_overrides": set(),
        "allowed_reason_codes": set(),
        "forbidden_reason_codes": {"NOT_APPLICABLE_BY_ADAPTER"},
        "requires_build_guarantee": True,
    },
    "backend-service": {
        "inherits": "generic",
        "artifact_overrides_by_state": {},
        "verify_section_overrides": {"Build Guarantee"},
        "verify_field_overrides": set(),
        "allowed_reason_codes": set(),
        "forbidden_reason_codes": {"NOT_APPLICABLE_BY_ADAPTER"},
        "requires_build_guarantee": True,
    },
    "batch-etl": {
        "inherits": "generic",
        "artifact_overrides_by_state": {},
        "verify_section_overrides": {"Build Guarantee"},
        "verify_field_overrides": set(),
        "allowed_reason_codes": set(),
        "forbidden_reason_codes": {"NOT_APPLICABLE_BY_ADAPTER"},
        "requires_build_guarantee": True,
    },
    "cli-tool": {
        "inherits": "generic",
        "artifact_overrides_by_state": {},
        "verify_section_overrides": {"Build Guarantee"},
        "verify_field_overrides": set(),
        "allowed_reason_codes": set(),
        "forbidden_reason_codes": {"NOT_APPLICABLE_BY_ADAPTER"},
        "requires_build_guarantee": True,
    },
    "resource-constrained-ui": {
        "inherits": "generic",
        "artifact_overrides_by_state": {},
        "verify_section_overrides": {"Build Guarantee"},
        "verify_field_overrides": {"reviewer", "timestamp"},
        "allowed_reason_codes": set(),
        "forbidden_reason_codes": {"NOT_APPLICABLE_BY_ADAPTER"},
        "requires_build_guarantee": True,
    },
}


# Verify Floor Baseline constants (TASK-1009)
VERIFY_FLOOR_BASELINE_PATH = "artifacts/governance/verify-floor-baseline.v3.4.json"
VERIFY_FLOOR_POLICY_HISTORICAL = "advisory_until_6d"
VERIFY_FLOOR_POLICY_STRICT = "strict"
VERIFY_FLOOR_SCHEMA_VERSION = "verify-floor-baseline/v1"


def normalize_assurance_level(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in ASSURANCE_LEVELS else DEFAULT_ASSURANCE_LEVEL


def validate_assurance_level_strict(value: str) -> str:
    """Strict mode: raises ValueError for unknown or empty assurance level."""
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValueError(
            f"assurance_level is required but missing or empty. "
            f"Allowed values: {list(ASSURANCE_LEVELS)}."
        )
    if normalized not in ASSURANCE_LEVELS:
        raise ValueError(
            f"Unknown assurance_level '{normalized}'. "
            f"Allowed values: {list(ASSURANCE_LEVELS)}. "
            "Use legacy compatibility mode only if explicitly authorized."
        )
    return normalized


def warn_and_default_assurance_level(value: str) -> tuple:
    """
    Legacy compatibility mode only. Returns (resolved_level, warning_dict).
    Must be explicitly invoked; never called as a silent fallback.
    warning_dict keys when defaulting occurs: defaulted_from, selected_default, migration_debt.
    Empty dict means no defaulting was needed (value was already valid).
    """
    normalized = str(value or "").strip().lower()
    if normalized in ASSURANCE_LEVELS:
        return normalized, {}
    defaulted_from = normalized if normalized else "(empty)"
    warning = {
        "defaulted_from": defaulted_from,
        "selected_default": DEFAULT_ASSURANCE_LEVEL,
        "migration_debt": (
            f"assurance_level '{defaulted_from}' is not in the allowed vocabulary "
            f"{list(ASSURANCE_LEVELS)}. Defaulted to '{DEFAULT_ASSURANCE_LEVEL}' via "
            "legacy compatibility mode. Update this artifact's assurance_level to a "
            "valid value to remove this migration debt."
        ),
    }
    return DEFAULT_ASSURANCE_LEVEL, warning


def normalize_project_adapter(value: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in PROJECT_ADAPTERS else DEFAULT_PROJECT_ADAPTER


def _clone_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "required_artifacts_by_state": {
            state: set(artifacts)
            for state, artifacts in profile["required_artifacts_by_state"].items()
        },
        "verify_required_fields": set(profile["verify_required_fields"]),
        "verify_required_sections": set(profile["verify_required_sections"]),
        "allow_deferred": bool(profile["allow_deferred"]),
        "allow_unverifiable": bool(profile["allow_unverifiable"]),
        "requires_manual_review": bool(profile["requires_manual_review"]),
        "default_verification_readiness": str(profile["default_verification_readiness"]),
        "status_debt_results": set(profile["status_debt_results"]),
    }


def _resolve_adapter_chain(project_adapter: str) -> List[str]:
    chain: List[str] = []
    seen: Set[str] = set()
    current = str(project_adapter or "").strip().lower()
    while current:
        if current in seen:
            raise ValueError(f"Adapter inheritance cycle detected at '{current}'")
        adapter_rule = PROJECT_ADAPTER_RULES.get(current)
        if adapter_rule is None:
            raise ValueError(f"Unknown project adapter rule: {current}")
        seen.add(current)
        chain.append(current)
        parent = adapter_rule["inherits"]
        current = str(parent).strip().lower() if parent else ""
    chain.reverse()
    return chain


def resolve_verification_policy(assurance_level: str, project_adapter: str) -> Dict[str, Any]:
    normalized_assurance = normalize_assurance_level(assurance_level)
    normalized_adapter = normalize_project_adapter(project_adapter)
    profile = ASSURANCE_PROFILES.get(normalized_assurance)
    if profile is None:
        raise ValueError(f"Missing assurance profile: {normalized_assurance}")
    missing_fields = [field for field in ASSURANCE_PROFILE_FIELDS if field not in profile]
    if missing_fields:
        raise ValueError(
            f"Assurance profile '{normalized_assurance}' missing fields: {missing_fields}"
        )
    resolved = _clone_profile(profile)
    forbidden_reason_codes: Set[str] = set()
    allowed_reason_codes: Set[str] = set()

    for adapter_name in _resolve_adapter_chain(normalized_adapter):
        adapter_rule = PROJECT_ADAPTER_RULES[adapter_name]
        for state, overrides in adapter_rule["artifact_overrides_by_state"].items():
            artifacts = resolved["required_artifacts_by_state"].setdefault(state, set())
            for artifact_name, is_required in overrides.items():
                if is_required:
                    artifacts.add(artifact_name)
                else:
                    artifacts.discard(artifact_name)
        resolved["verify_required_sections"].update(adapter_rule["verify_section_overrides"])
        resolved["verify_required_fields"].update(adapter_rule["verify_field_overrides"])
        allowed_reason_codes.update(adapter_rule["allowed_reason_codes"])
        forbidden_reason_codes.update(adapter_rule["forbidden_reason_codes"])
        resolved["requires_build_guarantee"] = (
            resolved.get("requires_build_guarantee", False) or bool(adapter_rule["requires_build_guarantee"])
        )

    resolved["allowed_results"] = set(VERIFICATION_ITEM_RESULTS)
    resolved["allowed_reason_codes"] = allowed_reason_codes - forbidden_reason_codes
    resolved["disallowed_results"] = set()
    if not resolved["allow_deferred"]:
        resolved["disallowed_results"].add("deferred")
    if not resolved["allow_unverifiable"]:
        resolved["disallowed_results"].add("unverifiable")
    resolved["project_adapter"] = normalized_adapter
    resolved["assurance_level"] = normalized_assurance
    return resolved


def derive_verification_readiness(
    assurance_level: str,
    project_adapter: str,
    state: str = "",
    open_verification_debts: Optional[List[Any]] = None,
) -> str:
    policy = resolve_verification_policy(assurance_level, project_adapter)
    state_value = str(state or "").strip().lower()
    debts = [item for item in list(open_verification_debts or []) if str(item).strip()]
    if (
        policy["assurance_level"] == "production"
        and state_value == "done"
        and not debts
    ):
        return "production-ready"
    return str(policy["default_verification_readiness"])


def validate_workflow_rule_tables() -> List[str]:
    errors: List[str] = []
    valid_assurance_levels: Set[str] = set()
    resolvable_adapters: Set[str] = set()

    for assurance_level in ASSURANCE_LEVELS:
        profile = ASSURANCE_PROFILES.get(assurance_level)
        if profile is None:
            errors.append(f"Missing assurance profile: {assurance_level}")
            continue
        missing_fields = [field for field in ASSURANCE_PROFILE_FIELDS if field not in profile]
        if missing_fields:
            errors.append(f"Assurance profile '{assurance_level}' missing fields: {missing_fields}")
            continue
        states = set(profile["required_artifacts_by_state"].keys())
        if states != set(WORKFLOW_STATES):
            errors.append(
                f"Assurance profile '{assurance_level}' must define required_artifacts_by_state for {list(WORKFLOW_STATES)}"
            )
        for state_name, artifacts in profile["required_artifacts_by_state"].items():
            unknown_artifacts = sorted(set(artifacts) - set(ARTIFACT_TYPES))
            if unknown_artifacts:
                errors.append(
                    f"Assurance profile '{assurance_level}' state '{state_name}' uses unknown artifacts: {unknown_artifacts}"
                )
        unknown_fields = sorted(set(profile["verify_required_fields"]) - set(STRUCTURED_CHECKLIST_FIELDS))
        if unknown_fields:
            errors.append(
                f"Assurance profile '{assurance_level}' verify_required_fields uses unknown fields: {unknown_fields}"
            )
        unknown_results = sorted(set(profile["status_debt_results"]) - set(VERIFICATION_ITEM_RESULTS))
        if unknown_results:
            errors.append(
                f"Assurance profile '{assurance_level}' status_debt_results uses unknown results: {unknown_results}"
            )
        readiness = str(profile["default_verification_readiness"])
        if readiness not in VERIFICATION_READINESS_STATES:
            errors.append(
                f"Assurance profile '{assurance_level}' default_verification_readiness must be one of {list(VERIFICATION_READINESS_STATES)}"
            )
        valid_assurance_levels.add(assurance_level)

    for adapter_name in PROJECT_ADAPTERS:
        rule = PROJECT_ADAPTER_RULES.get(adapter_name)
        if rule is None:
            errors.append(f"Missing project adapter rule: {adapter_name}")
            continue
        parent = rule["inherits"]
        if parent is not None and parent not in PROJECT_ADAPTER_RULES:
            errors.append(f"Adapter '{adapter_name}' inherits unknown adapter '{parent}'")
            continue
        for state_name, overrides in rule["artifact_overrides_by_state"].items():
            if state_name not in WORKFLOW_STATES:
                errors.append(f"Adapter '{adapter_name}' defines overrides for unknown state '{state_name}'")
            unknown_artifacts = sorted(set(overrides.keys()) - set(ARTIFACT_TYPES))
            if unknown_artifacts:
                errors.append(
                    f"Adapter '{adapter_name}' artifact_overrides_by_state uses unknown artifacts: {unknown_artifacts}"
                )
        unknown_fields = sorted(set(rule["verify_field_overrides"]) - set(STRUCTURED_CHECKLIST_FIELDS))
        if unknown_fields:
            errors.append(f"Adapter '{adapter_name}' verify_field_overrides uses unknown fields: {unknown_fields}")
        unknown_reason_codes = sorted(
            (set(rule["allowed_reason_codes"]) | set(rule["forbidden_reason_codes"]))
            - set(VERIFICATION_REASON_CODES)
        )
        if unknown_reason_codes:
            errors.append(
                f"Adapter '{adapter_name}' uses unknown reason codes: {unknown_reason_codes}"
            )
        resolvable_adapters.add(adapter_name)

    for assurance_level in ASSURANCE_LEVELS:
        if assurance_level not in valid_assurance_levels:
            continue
        for adapter_name in PROJECT_ADAPTERS:
            if adapter_name not in resolvable_adapters:
                continue
            try:
                policy = resolve_verification_policy(assurance_level, adapter_name)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            for key in (
                "required_artifacts_by_state",
                "verify_required_fields",
                "verify_required_sections",
                "allowed_results",
                "allowed_reason_codes",
                "disallowed_results",
                "requires_manual_review",
                "requires_build_guarantee",
                "status_debt_results",
                "default_verification_readiness",
            ):
                if key not in policy:
                    errors.append(
                        f"Resolved policy for {assurance_level}/{adapter_name} missing contract key '{key}'"
                    )
            states = set(policy.get("required_artifacts_by_state", {}).keys())
            if states != set(WORKFLOW_STATES):
                errors.append(
                    f"Resolved policy for {assurance_level}/{adapter_name} must cover all workflow states"
                )
            unknown_reason_codes = sorted(set(policy.get("allowed_reason_codes", set())) - set(VERIFICATION_REASON_CODES))
            if unknown_reason_codes:
                errors.append(
                    f"Resolved policy for {assurance_level}/{adapter_name} exposes unknown reason codes: {unknown_reason_codes}"
                )
            unknown_results = sorted(
                (
                    set(policy.get("allowed_results", set()))
                    | set(policy.get("disallowed_results", set()))
                    | set(policy.get("status_debt_results", set()))
                )
                - set(VERIFICATION_ITEM_RESULTS)
            )
            if unknown_results:
                errors.append(
                    f"Resolved policy for {assurance_level}/{adapter_name} exposes unknown verification results: {unknown_results}"
                )
            readiness = str(policy.get("default_verification_readiness", ""))
            if readiness not in VERIFICATION_READINESS_STATES:
                errors.append(
                    f"Resolved policy for {assurance_level}/{adapter_name} has invalid readiness '{readiness}'"
                )
    return errors


# ---------------------------------------------------------------------------
# RACI Auditor v2 — path classification and canonical RACI matrix (TASK-1007)
# ---------------------------------------------------------------------------

THREAT_MODEL_PATH_RE = re.compile(r"^threat-model-[^/]+/")

_PATH_PREFIX_RULES: list[tuple[str, str]] = [
    ("artifacts/tasks/", "task"),
    ("artifacts/research/", "research"),
    ("artifacts/plans/", "plan"),
    ("artifacts/code/", "code"),
    ("artifacts/test/", "test"),
    ("artifacts/verify/", "verify"),
    ("artifacts/decisions/", "decision"),
    ("artifacts/status/", "status"),
    ("artifacts/improvement/", "improvement"),
    ("artifacts/scripts/", "scripts"),
    ("docs/", "workflow_contract_docs"),
    (".github/memory-bank/", "memory_bank"),
    (".github/workflows/", "ci_workflows"),
    (".github/agents/", "agent_definitions"),
    (".github/skills/", "skills"),
    (".github/prompts/", "prompts"),
    ("template/", "template_mirror"),
    ("external/", "external_dependency"),
]

_WORKFLOW_ENTRY_FILES: frozenset[str] = frozenset({
    "README.md", "README.zh-TW.md", "OBSIDIAN.md", "START_HERE.md",
})

_AGENT_PROMPT_FILES: frozenset[str] = frozenset({
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "CODEX.md", "BOOTSTRAP_PROMPT.md",
})


def classify_path(path_str: str) -> str:
    """
    Classify a repo-relative file path into a RACI v2 path category.
    Returns 'unknown' (fail-closed) for unrecognized paths.
    """
    normalized = path_str.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]

    filename = normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized

    if filename in _WORKFLOW_ENTRY_FILES:
        return "workflow_entry"
    if filename in _AGENT_PROMPT_FILES:
        return "agent_prompt"
    if THREAT_MODEL_PATH_RE.match(normalized):
        return "threat_model"

    for prefix, category in _PATH_PREFIX_RULES:
        if normalized.startswith(prefix):
            return category

    return "unknown"


RACI_MATRIX_V2: dict[str, frozenset[str]] = {
    "Claude Code": frozenset({"task", "plan", "decision", "status"}),
    "Gemini CLI":  frozenset({"research", "memory_bank"}),
    "Codex CLI":   frozenset({"code"}),
    "Implementer": frozenset({"code"}),
    "Tester":      frozenset({"test"}),
    "Verifier":    frozenset({"verify"}),
    "Reviewer":    frozenset({"verify"}),
}
