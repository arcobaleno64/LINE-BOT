#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Sequence

import guard_status_validator as gsv
from workflow_constants import REQUIRED_TOPICS, TOPIC_PATTERN, validate_workflow_rule_tables

SOURCE_REPO_SENTINEL = ".council-forge-source-repo"
BROWNFIELD_SENTINEL = ".council-forge-brownfield"
SOURCE_REPO_MODE = "source"
DOWNSTREAM_REPO_MODE = "downstream"

EXACT_SYNC_FILES = [
    "AGENTS.md",
    "BOOTSTRAP_PROMPT.md",
    "CODEX.md",
    "GEMINI.md",
    "START_HERE.md",
    "requirements-dev.txt",
    "artifacts/scripts/agent_identity.py",
    "artifacts/scripts/build_decision_registry.py",
    "artifacts/scripts/conftest.py",
    "artifacts/scripts/guard_contract_validator.py",
    "artifacts/scripts/prompt_regression_validator.py",
    "artifacts/scripts/repo_security_scan.py",
    "artifacts/scripts/run_red_team_suite.py",
    "artifacts/scripts/release_gate.py",
    "artifacts/scripts/sast_gate.py",
    "artifacts/scripts/sbom_gate.py",
    "artifacts/scripts/sca_gate.py",
    "artifacts/scripts/security_txt_gate.py",
    "artifacts/scripts/drills/prompt_regression_cases.json",
    "artifacts/scripts/guard_status_validator.py",
    "artifacts/scripts/migrate_artifact_schema.py",
    "artifacts/scripts/test_artifact_schema_migration.py",
    "artifacts/scripts/test_decision_registry_and_red_team.py",
    "artifacts/scripts/test_guard_contract_validator.py",
    "artifacts/scripts/test_guard_status_validator_artifacts.py",
    "artifacts/scripts/test_guard_status_validator_core.py",
    "artifacts/scripts/test_guard_status_validator_state.py",
    "artifacts/scripts/test_guard_units.py",
    "artifacts/scripts/test_invoke_codex_agent.py",
    "artifacts/scripts/test_invoke_codex_review.py",
    "artifacts/scripts/test_invoke_gemini_agent.py",
    "artifacts/scripts/test_prompt_regression_validator.py",
    "artifacts/scripts/test_repository_and_pdca.py",
    "artifacts/scripts/test_validate_context_stack.py",
    "artifacts/scripts/test_workflow_constants.py",
    "artifacts/scripts/update_repository_profile.py",
    "artifacts/scripts/workflow_constants.py",
    "docs/artifact_schema.md",
    "docs/agentic_execution_layer.md",
    "docs/dispatch_prompt_discipline.md",
    "docs/lightweight_mode_rules.md",
    "docs/orchestration.md",
    "docs/premortem_rules.md",
    "docs/red_team_backlog.md",
    "docs/red_team_runbook.md",
    "docs/red_team_scorecard.md",
    "docs/sop/dispatch_implementation.md",
    "docs/sop/dispatch_memory_curator.md",
    "docs/sop/dispatch_research.md",
    "docs/sop/task_completion.md",
    "docs/subagent_roles.md",
    "docs/subagent_task_templates.md",
    "docs/workflow_state_machine.md",
]

COMMON_REQUIRED_PHRASES: Dict[str, Sequence[str]] = {
    "BOOTSTRAP_PROMPT.md": (
        "guard_contract_validator.py",
        "prompt_regression_validator.py",
        "update_repository_profile.py",
        "downstream terminal repo",
    ),
    "template/BOOTSTRAP_PROMPT.md": (
        "guard_contract_validator.py",
        "prompt_regression_validator.py",
        "update_repository_profile.py",
        "downstream terminal repo",
    ),
}

SOURCE_REQUIRED_PHRASES: Dict[str, Sequence[str]] = {
    "CLAUDE.md": (
        "guard_contract_validator.py",
        "OBSIDIAN.md",
        "template/OBSIDIAN.md",
        ".council-forge-source-repo",
        "source template repo",
        "任一同步缺漏（包含 Obsidian 入口）都視為 workflow 變更未完成。",
    ),
    "template/CLAUDE.md": (
        "downstream terminal repo",
        "不得再建立新的 `template/`",
        "只維護 root 文件",
        "guard_contract_validator.py",
    ),
}

DOWNSTREAM_REQUIRED_PHRASES: Dict[str, Sequence[str]] = {
    "CLAUDE.md": (
        "downstream terminal repo",
        "不得再建立新的 `template/`",
        "只維護 root 文件",
        "guard_contract_validator.py",
        "OBSIDIAN.md",
        "不再建立新的 `template/`",
    ),
}

# Backward-compatible alias for tests and external imports that only need the
# source-repo map shape.
REQUIRED_PHRASES = {**COMMON_REQUIRED_PHRASES, **SOURCE_REQUIRED_PHRASES}

PLACEHOLDER_PATTERNS = (
    (r"\{\{PROJECT_NAME\}\}", "__PROJECT__"),
    (r"\{\{REPO_NAME\}\}", "__REPO__"),
    (r"\{\{UPSTREAM_ORG\}\}", "__ORG__"),
)

PROMPT_ENTRY_FILES = {
    "CLAUDE.md",
    "GEMINI.md",
    "CODEX.md",
    "template/CLAUDE.md",
    "template/GEMINI.md",
    "template/CODEX.md",
}

PROMPT_REGRESSION_FILES = {
    "artifacts/scripts/drills/prompt_regression_cases.json",
    "template/artifacts/scripts/drills/prompt_regression_cases.json",
}

REPOSITORY_PROFILE_FILES = (
    ".github/repository-profile.json",
    "template/.github/repository-profile.json",
)

ACTIVE_GEMINI_POLICY_FILES = (
    "CLAUDE.md",
    "BOOTSTRAP_PROMPT.md",
    "docs/subagent_roles.md",
    "artifacts/scripts/Invoke-GeminiAgent.ps1",
    "template/CLAUDE.md",
    "template/BOOTSTRAP_PROMPT.md",
    "template/docs/subagent_roles.md",
    "template/artifacts/scripts/Invoke-GeminiAgent.ps1",
)

ALLOWED_GEMINI_MODELS = {
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
}

DISALLOWED_GEMINI_FRAGMENTS = (
    "gemini-2.0",
    "gemini-2.5",
    "gemini 2.0",
    "gemini 2.5",
    "2.0-flash",
    "2.5-flash",
)

README_HEADERS_EN = [
    "Start Here",
    "Product Positioning",
    "Why This Project Exists",
    "Core Capabilities",
    "Product Highlights",
    "Use Cases",
    "Workflow Overview",
    "Architecture Snapshot",
    "Getting Started",
    "Repository Structure",
    "Validator Commands",
    "Security And Supply-Chain Hardening",
    "Operational Notes",
    "Context System",
    "Contributing",
    "License",
]

README_HEADERS_ZH = [
    "從這裡開始",
    "產品定位",
    "為什麼是這個專案",
    "核心能力",
    "產品特色",
    "適用情境",
    "工作流總覽",
    "架構速覽",
    "開始使用",
    "儲存庫結構",
    "驗證指令",
    "安全與供應鏈強化",
    "操作備註",
    "上下文管理系統",
    "貢獻指引",
    "授權條款",
]

OBSIDIAN_HEADERS = [
    "文件語言規範",
    "建議閱讀順序",
    "導覽目錄",
    "同步範圍",
    "Workflow 摘要",
    "Decision Registry",
    "GitHub / Template 對應",
]

README_CONTRACTS: Dict[str, Dict[str, dict[str, object]]] = {
    SOURCE_REPO_MODE: {
        "README.md": {
            "headers": README_HEADERS_EN,
            "sections": {
                "Architecture Snapshot": {
                    "required": ("template/ + .github/ + OBSIDIAN.md + external/",),
                },
                "Getting Started": {
                    "required": ("source template repo", ".council-forge-source-repo", "downstream terminal repo"),
                },
                "Validator Commands": {
                    "required": ("source mode checks root ↔ template ↔ Obsidian",),
                },
            },
        },
        "README.zh-TW.md": {
            "headers": README_HEADERS_ZH,
            "sections": {
                "架構速覽": {
                    "required": ("template/ + .github/ + OBSIDIAN.md + external/",),
                },
                "開始使用": {
                    "required": ("source template repo", ".council-forge-source-repo", "downstream terminal repo"),
                },
                "驗證指令": {
                    "required": ("source mode 檢查 root ↔ template ↔ Obsidian",),
                },
            },
        },
        "template/README.md": {
            "headers": README_HEADERS_EN,
            "sections": {
                "Architecture Snapshot": {
                    "required": (".github/ + OBSIDIAN.md + external/",),
                    "forbidden": ("template/ + .github/ + OBSIDIAN.md + external/",),
                },
                "Getting Started": {
                    "required": ("downstream terminal repo", "nested `template/`"),
                    "forbidden": (".council-forge-source-repo",),
                },
                "Validator Commands": {
                    "required": ("downstream mode checks root ↔ Obsidian",),
                },
            },
        },
        "template/README.zh-TW.md": {
            "headers": README_HEADERS_ZH,
            "sections": {
                "架構速覽": {
                    "required": (".github/ + OBSIDIAN.md + external/",),
                    "forbidden": ("template/ + .github/ + OBSIDIAN.md + external/",),
                },
                "開始使用": {
                    "required": ("downstream terminal repo", "nested `template/`"),
                    "forbidden": (".council-forge-source-repo",),
                },
                "驗證指令": {
                    "required": ("downstream mode 檢查 root ↔ Obsidian",),
                },
            },
        },
    },
    DOWNSTREAM_REPO_MODE: {
        "README.md": {
            "headers": README_HEADERS_EN,
            "sections": {
                "Architecture Snapshot": {
                    "required": (".github/ + OBSIDIAN.md + external/",),
                    "forbidden": ("template/ + .github/ + OBSIDIAN.md + external/",),
                },
                "Getting Started": {
                    "required": ("downstream terminal repo", "nested `template/`"),
                    "forbidden": (".council-forge-source-repo",),
                },
                "Validator Commands": {
                    "required": ("downstream mode checks root ↔ Obsidian",),
                    "forbidden": ("source mode checks root ↔ template ↔ Obsidian",),
                },
            },
        },
        "README.zh-TW.md": {
            "headers": README_HEADERS_ZH,
            "sections": {
                "架構速覽": {
                    "required": (".github/ + OBSIDIAN.md + external/",),
                    "forbidden": ("template/ + .github/ + OBSIDIAN.md + external/",),
                },
                "開始使用": {
                    "required": ("downstream terminal repo", "nested `template/`"),
                    "forbidden": (".council-forge-source-repo",),
                },
                "驗證指令": {
                    "required": ("downstream mode 檢查 root ↔ Obsidian",),
                    "forbidden": ("source mode 檢查 root ↔ template ↔ Obsidian",),
                },
            },
        },
    },
}

OBSIDIAN_CONTRACTS: Dict[str, Dict[str, dict[str, object]]] = {
    SOURCE_REPO_MODE: {
        "OBSIDIAN.md": {
            "headers": OBSIDIAN_HEADERS,
            "sections": {
                "同步範圍": {
                    "required": ("source template repo", "template 對應文件", "downstream terminal repo"),
                },
                "Workflow 摘要": {
                    "required": (
                        "source template repo 的 workflow 規則變更後，必須同步更新 root、`template/` 與 Obsidian 入口，並通過 contract guard。",
                        "downstream terminal repo 的 workflow 規則變更後，只維護 root 文件與 `OBSIDIAN.md`，並通過 contract guard。",
                    ),
                },
                "GitHub / Template 對應": {
                    "required": ("template/START_HERE.md", "template/OBSIDIAN.md"),
                },
            },
        },
        "template/OBSIDIAN.md": {
            "headers": OBSIDIAN_HEADERS,
            "sections": {
                "同步範圍": {
                    "required": ("只維護 root 文件與 `OBSIDIAN.md`", "不再建立新的 `template/`"),
                    "forbidden": ("template 對應文件",),
                },
                "Workflow 摘要": {
                    "required": ("downstream terminal repo 的 workflow 規則變更後，只維護 root 文件與 `OBSIDIAN.md`，並通過 contract guard。",),
                    "forbidden": ("必須同步更新 root、`template/` 與 Obsidian 入口",),
                },
                "GitHub / Template 對應": {
                    "required": ("本 repo 不建立 nested `template/`",),
                    "forbidden": ("template/START_HERE.md", "template/OBSIDIAN.md"),
                },
            },
        },
    },
    DOWNSTREAM_REPO_MODE: {
        "OBSIDIAN.md": {
            "headers": OBSIDIAN_HEADERS,
            "sections": {
                "同步範圍": {
                    "required": ("只維護 root 文件與 `OBSIDIAN.md`", "不再建立新的 `template/`"),
                    "forbidden": ("template 對應文件",),
                },
                "Workflow 摘要": {
                    "required": ("downstream terminal repo 的 workflow 規則變更後，只維護 root 文件與 `OBSIDIAN.md`，並通過 contract guard。",),
                    "forbidden": ("必須同步更新 root、`template/` 與 Obsidian 入口",),
                },
                "GitHub / Template 對應": {
                    "required": ("本 repo 不建立 nested `template/`",),
                    "forbidden": ("template/START_HERE.md", "template/OBSIDIAN.md"),
                },
            },
        },
    },
}

def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n")
    for pattern, replacement in PLACEHOLDER_PATTERNS:
        normalized = re.sub(pattern, replacement, normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    return normalized.strip()


def detect_repo_mode(root: Path) -> str:
    sentinel_path = root / SOURCE_REPO_SENTINEL
    return SOURCE_REPO_MODE if sentinel_path.exists() else DOWNSTREAM_REPO_MODE


def is_brownfield(root: Path) -> bool:
    """A brownfield downstream is an existing repo retrofitted with council-forge
    governance (marker `.council-forge-brownfield`). It keeps its own project
    README.md and CLAUDE.md, so council-forge relaxes its product-template README
    structure / bilingual requirement for it. The orchestrator prompt content
    council-forge mandates is instead guaranteed by the EXACT_SYNC docs
    (docs/orchestration.md), not the project's own CLAUDE.md."""
    return (root / BROWNFIELD_SENTINEL).exists()


def required_phrases_for_mode(mode: str) -> Dict[str, Sequence[str]]:
    if mode == SOURCE_REPO_MODE:
        return {**COMMON_REQUIRED_PHRASES, **SOURCE_REQUIRED_PHRASES}
    return {
        **{
            rel: phrases
            for rel, phrases in COMMON_REQUIRED_PHRASES.items()
            if not rel.startswith("template/")
        },
        **DOWNSTREAM_REQUIRED_PHRASES,
    }


def validate_exact_sync(root: Path) -> List[str]:
    if detect_repo_mode(root) == DOWNSTREAM_REPO_MODE:
        return []
    errors: List[str] = []
    for relative in EXACT_SYNC_FILES:
        root_path = root / relative
        template_path = root / "template" / relative
        if not root_path.exists():
            errors.append(f"Missing root file: {relative}")
            continue
        if not template_path.exists():
            errors.append(f"Missing template file: template/{relative}")
            continue
        if normalize_text(load_text(root_path)) != normalize_text(load_text(template_path)):
            errors.append(f"Contract drift detected between {relative} and template/{relative}")
    return errors


def validate_required_phrases(root: Path) -> List[str]:
    phrase_map = required_phrases_for_mode(detect_repo_mode(root))
    errors: List[str] = []
    for relative, phrases in phrase_map.items():
        path = root / relative
        if not path.exists():
            errors.append(f"Missing required file: {relative}")
            continue
        text = load_text(path)
        for phrase in phrases:
            if phrase not in text:
                errors.append(f"{relative} missing required phrase: {phrase}")
    return errors


def _has_git_dir(root: Path) -> bool:
    """True if ``root`` or an ancestor contains a ``.git`` (dir or file) — a POSITIVE signal that
    this is a git repo context, INDEPENDENT of whether the git binary is runnable. Used to tell a
    genuine non-git bootstrap (no ``.git`` anywhere -> legit skip) apart from a real repo whose git
    is missing / ownership-blocked (safe.directory) / corrupt (``.git`` present -> degraded ->
    fail-closed). TASK-1090."""
    try:
        here = root.resolve()
    except OSError:  # pragma: no cover - defensive (resolve rarely raises)
        here = root
    for d in (here, *here.parents):
        if (d / ".git").exists():
            return True
    return False


def detect_changed_files(root: Path) -> tuple[bool, set[str], list[str]]:
    """Return ``(is_repo, changed, errors)`` for change-detection at ``root`` (TASK-1090).

    - ``is_repo=False``  -> ``root`` is NOT a git work tree (or git is unavailable): a non-git
      bootstrap context (e.g. a greenfield / tarball downstream scaffolded with
      ``git_init=False``). Change-detection is then N/A — NOT an error, and NOT a fail-open.
    - ``is_repo=True``   -> a git work tree. ``errors`` lists every change-detection probe that
      FAILED. A non-empty ``errors`` means detection is DEGRADED: a caller that needs complete
      coverage (e.g. ``validate_prompt_case_sync``) must FAIL CLOSED rather than treat the
      partial result as "no changes" (a tracked edit could otherwise be silently missed).
    """
    # Decide repo-vs-non-repo FIRST so a non-git bootstrap is not conflated with a degraded
    # detector. ``git rev-parse --is-inside-work-tree`` prints "true" only inside a work tree.
    in_work_tree = False
    rev_parse_rc = None
    try:
        probe = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, check=False, encoding="utf-8",
        )
        rev_parse_rc = probe.returncode
        in_work_tree = (probe.returncode == 0 and probe.stdout.strip() == "true")
    except FileNotFoundError:
        rev_parse_rc = None              # git binary not installed
    if not in_work_tree:
        # rev-parse could not confirm a work tree. Only a root with NO ``.git`` anywhere is a
        # genuine non-git bootstrap (legit skip). If a ``.git`` IS present, git is missing /
        # ownership-blocked (safe.directory) / corrupt on a REAL repo -> that is a DEGRADED
        # detector and MUST fail closed, not be mistaken for a bootstrap (TASK-1090; codex impl).
        if _has_git_dir(root):
            reason = "git executable not found" if rev_parse_rc is None else f"git rev-parse failed (exit {rev_parse_rc})"
            return True, set(), [f"{reason} in a repo context (.git present) — change-detection unavailable"]
        return False, set(), []          # no .git anywhere -> genuine non-git bootstrap

    commands = [
        ["git", "-C", str(root), "diff", "--name-only", "HEAD"],
        ["git", "-C", str(root), "diff", "--name-only", "--cached"],
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
    ]
    changed: set[str] = set()
    errors: list[str] = []
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, encoding="utf-8")
        except FileNotFoundError:
            errors.append(f"{' '.join(command)}: git not found")
            continue
        if result.returncode != 0:
            errors.append(f"{' '.join(command)}: exit {result.returncode}")
            continue
        for line in result.stdout.splitlines():
            token = line.strip().replace("\\", "/")
            if token:
                changed.add(token)
    return True, changed, errors


def validate_prompt_case_sync(root: Path) -> List[str]:
    is_repo, changed, errors = detect_changed_files(root)
    if not is_repo:
        # Non-git bootstrap (greenfield / tarball / scaffold git_init=False): no change-baseline,
        # so prompt-contract sync is N/A. A deliberate, documented skip — NOT a silent fail-open.
        return []
    if errors:
        # git work tree but a change-detection probe FAILED -> detection is DEGRADED. A tracked
        # prompt edit could be silently missed, so FAIL CLOSED rather than pass (TASK-1090).
        return [
            "Cannot verify prompt-contract sync: git change-detection is degraded "
            f"({'; '.join(errors)}). Refusing to pass silently (fail-closed)."
        ]
    if not changed:
        return []
    if changed.intersection(PROMPT_ENTRY_FILES) and not changed.intersection(PROMPT_REGRESSION_FILES):
        return [
            "Prompt contract changed but prompt regression cases were not updated. "
            "When modifying CLAUDE/GEMINI/CODEX prompts, also update artifacts/scripts/drills/prompt_regression_cases.json"
        ]
    return []


def validate_repository_profile(root: Path) -> List[str]:
    mode = detect_repo_mode(root)
    errors: List[str] = []
    profile_files = (
        REPOSITORY_PROFILE_FILES
        if mode == SOURCE_REPO_MODE
        else (".github/repository-profile.json",)
    )
    for relative in profile_files:
        path = root / relative
        if not path.exists():
            errors.append(f"Missing required repository profile: {relative}")
            continue
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{relative} is not valid JSON: {exc}")
            continue

        about = profile.get("about")
        topics = profile.get("topics")

        if not isinstance(about, str) or not about.strip():
            errors.append(f"{relative} must define non-empty string field 'about'")
        else:
            about_len = len(about.strip())
            if about_len < 80 or about_len > 200:
                errors.append(f"{relative} field 'about' must be 80-200 chars, got {about_len}")

        if not isinstance(topics, list):
            errors.append(f"{relative} must define list field 'topics'")
            continue
        normalized_topics = [str(topic).strip() for topic in topics]
        if len(normalized_topics) < 6 or len(normalized_topics) > 12:
            errors.append(f"{relative} field 'topics' must contain 6-12 items, got {len(normalized_topics)}")
        if len(set(normalized_topics)) != len(normalized_topics):
            errors.append(f"{relative} field 'topics' must not contain duplicates")
        invalid_topics = [topic for topic in normalized_topics if not TOPIC_PATTERN.match(topic)]
        if invalid_topics:
            errors.append(f"{relative} has invalid topics (must be lowercase-kebab-case): {invalid_topics}")
        missing_required_topics = sorted(REQUIRED_TOPICS - set(normalized_topics))
        if missing_required_topics:
            errors.append(f"{relative} missing required topics: {missing_required_topics}")
    return errors


def extract_h2_headers(text: str) -> list[str]:
    """Extract all H2 headers (lines starting with ##) from markdown text."""
    return [title for title, _ in parse_h2_sections(text)]


def parse_h2_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title: str | None = None
    current_body: list[str] = []
    in_code_fence = False

    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith("```"):
            in_code_fence = not in_code_fence
        if not in_code_fence and line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_body).strip()))
            current_title = line[3:].strip()
            current_body = []
            continue
        if current_title is not None:
            current_body.append(line)

    if current_title is not None:
        sections.append((current_title, "\n".join(current_body).strip()))
    return sections


def squeeze_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def contains_phrase(text: str, phrase: str) -> bool:
    return squeeze_whitespace(phrase) in squeeze_whitespace(text)


def validate_section_contract(
    relative: str,
    text: str,
    expected_headers: Sequence[str],
    section_rules: dict[str, object],
) -> List[str]:
    errors: List[str] = []
    sections = parse_h2_sections(text)
    actual_headers = [title for title, _ in sections]
    if actual_headers != list(expected_headers):
        errors.append(f"{relative} H2 order mismatch: expected {list(expected_headers)}, got {actual_headers}")

    section_map = {title: body for title, body in sections}
    for section_name, raw_rule in section_rules.items():
        body = section_map.get(section_name)
        if body is None:
            errors.append(f"{relative} missing required section: {section_name}")
            continue
        rules = raw_rule if isinstance(raw_rule, dict) else {}
        for phrase in rules.get("required", ()):
            if not contains_phrase(body, phrase):
                errors.append(f"{relative} section '{section_name}' missing required phrase: {phrase}")
        for phrase in rules.get("forbidden", ()):
            if contains_phrase(body, phrase):
                errors.append(f"{relative} section '{section_name}' contains forbidden phrase: {phrase}")
    return errors


def validate_markdown_contracts(root: Path) -> List[str]:
    mode = detect_repo_mode(root)
    errors: List[str] = []

    # A brownfield downstream keeps its own project README; council-forge does not
    # impose its product-README structure on it. The OBSIDIAN contract still applies
    # (OBSIDIAN.md is council-forge-provided by the overlay).
    contract_groups = (
        (OBSIDIAN_CONTRACTS[mode],)
        if is_brownfield(root)
        else (README_CONTRACTS[mode], OBSIDIAN_CONTRACTS[mode])
    )
    for contract_group in contract_groups:
        for relative, contract in contract_group.items():
            path = root / relative
            if not path.exists():
                errors.append(f"Missing required file: {relative}")
                continue
            text = load_text(path)
            headers = contract.get("headers", [])
            section_rules = contract.get("sections", {})
            errors.extend(
                validate_section_contract(
                    relative,
                    text,
                    headers if isinstance(headers, list) else [],
                    section_rules if isinstance(section_rules, dict) else {},
                )
            )
    return errors


def validate_readme_structure(root: Path) -> List[str]:
    """Validate README bilingual structure alongside the section-level contract."""
    mode = detect_repo_mode(root)
    errors: List[str] = []

    if is_brownfield(root):
        # Brownfield downstream owns its README; a single-language project README is fine.
        return errors

    readme_en = root / "README.md"
    readme_zh = root / "README.zh-TW.md"

    if not readme_en.exists():
        errors.append("Missing README.md in root")
    if not readme_zh.exists():
        errors.append("Missing README.zh-TW.md in root")

    if readme_en.exists() and readme_zh.exists():
        en_headers = extract_h2_headers(readme_en.read_text(encoding="utf-8"))
        zh_headers = extract_h2_headers(readme_zh.read_text(encoding="utf-8"))
        if len(en_headers) != len(zh_headers):
            errors.append(
                f"README structure mismatch in root: EN has {len(en_headers)} sections vs ZH has {len(zh_headers)} sections"
            )

    if mode == SOURCE_REPO_MODE:
        template_readme_en = root / "template" / "README.md"
        template_readme_zh = root / "template" / "README.zh-TW.md"

        if not template_readme_en.exists():
            errors.append("Missing README.md in template")
        if not template_readme_zh.exists():
            errors.append("Missing README.zh-TW.md in template")

        if template_readme_en.exists() and template_readme_zh.exists():
            template_en_headers = extract_h2_headers(template_readme_en.read_text(encoding="utf-8"))
            template_zh_headers = extract_h2_headers(template_readme_zh.read_text(encoding="utf-8"))
            if len(template_en_headers) != len(template_zh_headers):
                errors.append(
                    f"README structure mismatch in template: EN has {len(template_en_headers)} sections vs ZH has {len(template_zh_headers)} sections"
                )

    return errors


def validate_allowed_gemini_models(root: Path) -> List[str]:
    errors: List[str] = []
    model_pattern = re.compile(r"\bgemini-[a-z0-9.\-]+\b", re.IGNORECASE)

    for relative in ACTIVE_GEMINI_POLICY_FILES:
        path = root / relative
        if not path.exists():
            continue
        text = load_text(path)
        lowered = text.lower()
        for fragment in DISALLOWED_GEMINI_FRAGMENTS:
            if fragment in lowered:
                errors.append(f"{relative} contains disallowed Gemini model fragment: {fragment}")
        referenced_models = {match.group(0).lower() for match in model_pattern.finditer(text)}
        for model in sorted(referenced_models):
            if model not in ALLOWED_GEMINI_MODELS:
                errors.append(f"{relative} contains unsupported Gemini model reference: {model}")

    return errors


def validate_workflow_policy_contract() -> List[str]:
    return validate_workflow_rule_tables()


def validate_root_artifact_strictness(root: Path) -> List[str]:
    errors: List[str] = []
    artifact_roots = {
        "task": root / "artifacts" / "tasks",
        "decision": root / "artifacts" / "decisions",
        "improvement": root / "artifacts" / "improvement",
        "verify": root / "artifacts" / "verify",
    }
    for artifact_type, directory in artifact_roots.items():
        if not directory.exists():
            continue
        for path in sorted(directory.glob("TASK-*.*.md")):
            task_id = path.name.split(".", 1)[0]
            result = gsv.validate_markdown_artifact(path, artifact_type, task_id)
            for error in result.errors:
                errors.append(f"{path.relative_to(root).as_posix()}: {error}")
            for warning in result.warnings:
                errors.append(f"{path.relative_to(root).as_posix()}: root strictness forbids warning: {warning}")

    status_dir = root / "artifacts" / "status"
    if status_dir.exists():
        for path in sorted(status_dir.glob("TASK-*.status.json")):
            task_id = path.name.split(".", 1)[0]
            payload = json.loads(path.read_text(encoding="utf-8"))
            result = gsv.validate_status_schema(payload, task_id)
            for error in result.errors:
                errors.append(f"{path.relative_to(root).as_posix()}: {error}")
            for warning in result.warnings:
                errors.append(f"{path.relative_to(root).as_posix()}: root strictness forbids warning: {warning}")
    return errors

class RaciViolation:
    def __init__(self, agent: str, file_path: Path, actual_type: str, required_type: str):
        self.agent = agent
        self.file_path = file_path
        self.actual_type = actual_type
        self.required_type = required_type


def validate_raci_hybrid_sync(root: Path) -> None:
    roles_md_path = root / "docs" / "subagent_roles.md"
    if not roles_md_path.exists():
        raise ValueError(f"RACI hybrid sync failed: {roles_md_path.as_posix()} not found")
    
    text = roles_md_path.read_text(encoding="utf-8")
    
    raci_table = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "角色" in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 9:
            agent = parts[1]
            r_col = parts[3]
            if r_col != "--":
                artifacts = {a.strip() for a in r_col.split("/") if a.strip()}
                raci_table[agent] = artifacts

    import workflow_constants as wc
    
    for agent, artifacts in wc.RACI_MATRIX.items():
        if agent not in raci_table:
            raise ValueError(f"RACI hybrid sync failed: Agent '{agent}' in RACI_MATRIX but not in subagent_roles.md")
        if raci_table[agent] != artifacts:
            raise ValueError(f"RACI hybrid sync failed: Agent '{agent}' mismatch. Code: {artifacts}, Docs: {raci_table[agent]}")
    
    for agent, artifacts in raci_table.items():
        if agent not in wc.RACI_MATRIX:
            raise ValueError(f"RACI hybrid sync failed: Agent '{agent}' in docs but not in RACI_MATRIX")


def detect_raci_violations(file_path: Path, agent_identity: str, raci_matrix: Dict[str, set]) -> List[RaciViolation]:
    """LEGACY / SUPERSEDED (TASK-1090): this artifact-type classifier has NO runtime caller.

    The authoritative, live RACI enforcement path is ``workflow_constants.classify_path`` via the
    ``--audit-raci`` CLI mode, which FAILS CLOSED on an ``unknown`` path category. This legacy
    helper's "unmatched path -> code" default is deliberately retained because it is the CORRECT
    classification for a real source file (a non-artifact file IS code); it is kept only for
    historical reference and its own unit tests. New code MUST use ``classify_path`` /
    ``--audit-raci`` rather than this function.
    """
    allowed = raci_matrix.get(agent_identity, set())
    
    actual_type = "code (實檔修改)"
    path_str = file_path.as_posix()
    if "artifacts/tasks/TASK-" in path_str and path_str.endswith(".task.md"):
        actual_type = "task"
    elif "artifacts/plans/TASK-" in path_str and path_str.endswith(".plan.md"):
        actual_type = "plan"
    elif "artifacts/decisions/TASK-" in path_str and path_str.endswith(".decision.md"):
        actual_type = "decision"
    elif "artifacts/status/TASK-" in path_str and path_str.endswith(".status.json"):
        actual_type = "status"
    elif "artifacts/research/TASK-" in path_str and path_str.endswith(".research.md"):
        actual_type = "research"
    elif "artifacts/test/TASK-" in path_str and path_str.endswith(".test.md"):
        actual_type = "test"
    elif "artifacts/verify/TASK-" in path_str and path_str.endswith(".verify.md"):
        actual_type = "verify"
    elif path_str.startswith(".github/memory-bank/"):
        actual_type = "Remember Capture draft"
    
    if actual_type not in allowed:
        # Codex CLI uses "code" instead of "code (實檔修改)" in some places, so we unify it here.
        if actual_type == "code (實檔修改)" and "code" in allowed:
            return []
            
        return [RaciViolation(
            agent=agent_identity,
            file_path=file_path,
            actual_type=actual_type,
            required_type="code (實檔修改)" if actual_type == "code (實檔修改)" else " / ".join(allowed) if allowed else "None"
        )]
    return []


def apply_raci_waivers(violations: List[RaciViolation], decisions: List[dict]) -> List[RaciViolation]:
    waived = []
    ex_ante_decisions = [d for d in decisions if d.get("Waiver Type") == "ex-ante"]
    
    for v in violations:
        is_waived = False
        for d in ex_ante_decisions:
            if d.get("Waived Agent") == v.agent and d.get("Waived Artifact Type") == v.actual_type:
                is_waived = True
                break
        if not is_waived:
            waived.append(v)
            
    return waived


def _run_raci_audit_v2(
    root: Path,
    file_path_str: str,
    agent_str: str,
    fix: bool,
    dry_run: bool,
    compatibility_mode: bool,
) -> int:
    """RACI Auditor v2: JSON output, fail-closed paths, alias rejection, --fix rejection."""
    import agent_identity as ai
    import workflow_constants as wc

    # --fix is unconditionally rejected for RACI audits (exit 2)
    if fix:
        print(json.dumps({
            "schema_version": "raci-audit/v2",
            "error": "RACI_FIX_REJECTED",
            "message": (
                "--fix is not allowed for --audit-raci. "
                "RACI violations require decision / waiver / correction evidence, not auto-fix."
            ),
        }, indent=2))
        return 2

    # Resolve agent identity; alias in strict mode → exit 2, unknown → exit 2
    try:
        canonical_agent, was_aliased = ai.resolve_identity(
            agent_str, strict=True, compatibility_mode=compatibility_mode
        )
    except ai.AliasRejectedError as exc:
        print(json.dumps({
            "schema_version": "raci-audit/v2",
            "error": "ALIAS_REJECTED",
            "alias": agent_str,
            "canonical": exc.canonical,
            "message": str(exc),
        }, indent=2))
        return 2
    except ai.UnknownIdentityError as exc:
        print(json.dumps({
            "schema_version": "raci-audit/v2",
            "error": "UNKNOWN_IDENTITY",
            "agent": agent_str,
            "message": str(exc),
        }, indent=2))
        return 2

    if was_aliased:
        import sys as _sys
        print(
            f"[WARN] Alias '{agent_str}' resolved to '{canonical_agent}' (migration debt). "
            "Update to canonical name.",
            file=_sys.stderr,
        )

    # Compute repo-relative path for classification
    fp = Path(file_path_str)
    if fp.is_absolute():
        try:
            rel_path_str = fp.relative_to(root).as_posix()
        except ValueError:
            rel_path_str = file_path_str.replace("\\", "/")
    else:
        rel_path_str = file_path_str.replace("\\", "/")
        if rel_path_str.startswith("./"):
            rel_path_str = rel_path_str[2:]

    path_category = wc.classify_path(rel_path_str)
    allowed: frozenset[str] = wc.RACI_MATRIX_V2.get(canonical_agent, frozenset())

    # Build raw_violations: unknown path or path not in allowed set
    raw_violations: list[dict] = []
    if path_category == "unknown" or path_category not in allowed:
        raw_violations.append({
            "agent": canonical_agent,
            "file_path": rel_path_str,
            "path_category": path_category,
        })

    # Load ex-ante waivers from decision artifacts
    decisions: list[dict] = []
    decision_dir = root / "artifacts" / "decisions"
    if decision_dir.exists():
        for p in sorted(decision_dir.glob("TASK-*.decision.md")):
            text = p.read_text(encoding="utf-8")
            d: dict[str, str] = {}
            for line in text.splitlines():
                if line.startswith("- Waiver Type:"):
                    d["Waiver Type"] = line.split(":", 1)[1].strip()
                elif line.startswith("- Waived Agent:"):
                    d["Waived Agent"] = line.split(":", 1)[1].strip()
                elif line.startswith("- Waived Artifact Type:"):
                    d["Waived Artifact Type"] = line.split(":", 1)[1].strip()
            if d:
                decisions.append(d)

    ex_ante = [d for d in decisions if d.get("Waiver Type") == "ex-ante"]
    waivers_applied: list[dict] = []
    post_waiver_violations: list[dict] = []
    for v in raw_violations:
        is_waived = any(
            d.get("Waived Agent") == canonical_agent
            and d.get("Waived Artifact Type") == v["path_category"]
            for d in ex_ante
        )
        if is_waived:
            waivers_applied.append({
                "agent": canonical_agent,
                "path_category": v["path_category"],
                "waiver_type": "ex-ante",
            })
        else:
            post_waiver_violations.append(v)

    result_str = "VIOLATION" if post_waiver_violations else "PASS"
    audit_output = {
        "schema_version": "raci-audit/v2",
        "agent": canonical_agent,
        "file_path": rel_path_str,
        "path_category": path_category,
        "allowed_categories": sorted(allowed),
        "raw_violations": raw_violations,
        "waivers_applied": waivers_applied,
        "post_waiver_violations": post_waiver_violations,
        "result": result_str,
    }
    print(json.dumps(audit_output, indent=2))

    # Append to violations log unless dry-run
    if post_waiver_violations and not dry_run:
        import datetime
        log_path = root / ".github" / "memory-bank" / "raci-violations-log.md"
        if log_path.exists():
            ts = datetime.datetime.now(
                datetime.timezone(datetime.timedelta(hours=8))
            ).strftime("%Y-%m-%dT%H:%M:%S+08:00")
            with log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"- {ts} | Agent: {canonical_agent} | "
                    f"File: {rel_path_str} | Category: {path_category}\n"
                )

    return 1 if post_waiver_violations else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate workflow sync contracts across README, Obsidian, root, and template docs.")
    parser.add_argument("--root", default=".", help="Repository root. Default: current directory")
    parser.add_argument("--check-readme", action="store_true", help="Validate README section contract plus bilingual H2 structure consistency")
    parser.add_argument("--audit-raci", nargs=2, metavar=("FILE", "AGENT"), help="Run RACI auditor v2 on a specific file against an agent (JSON output)")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing violations log (default for audit)")
    parser.add_argument("--fix", action="store_true", help="Automatically fix obvious state drifts; rejected for --audit-raci (exit 2)")
    parser.add_argument("--compatibility-mode", action="store_true", help="Allow alias resolution for --audit-raci (migration debt; emits deprecation warning)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()

    if args.audit_raci:
        return _run_raci_audit_v2(
            root,
            file_path_str=args.audit_raci[0],
            agent_str=args.audit_raci[1],
            fix=args.fix,
            dry_run=args.dry_run,
            compatibility_mode=args.compatibility_mode,
        )

    errors = validate_exact_sync(root)
    errors.extend(validate_required_phrases(root))
    errors.extend(validate_markdown_contracts(root))
    errors.extend(validate_prompt_case_sync(root))
    errors.extend(validate_repository_profile(root))
    errors.extend(validate_allowed_gemini_models(root))
    errors.extend(validate_workflow_policy_contract())
    errors.extend(validate_root_artifact_strictness(root))
    
    try:
        validate_raci_hybrid_sync(root)
    except ValueError as e:
        errors.append(str(e))
    
    if args.check_readme:
        errors.extend(validate_readme_structure(root))

    if errors:
        print("[ERROR] Contract validation failed")
        for error in errors:
            print(f"[FAIL] {error}")
        return 1

    print("[OK] Contract validation passed")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
