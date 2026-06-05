#!/usr/bin/env python3
"""
Context Stack Validator

驗證上下文系統（memory-bank、prompts、skills、copilot-instructions）的
內容完整性、交叉引用、frontmatter 合法性、名稱唯一性與檔案品質。
"""
from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# ---------------------------------------------------------------------------
# Stream init (CLI entrypoint only — do NOT call at import time)
# ---------------------------------------------------------------------------

def init_streams(stdout=None, stderr=None) -> None:
    """Apply UTF-8 encoding wrapper to output streams if needed.

    Must be called from the CLI entrypoint (main) only.
    Accepts optional stream arguments for testability; defaults to sys.stdout/sys.stderr.
    """
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    if hasattr(out, "buffer") and getattr(out, "encoding", "utf-8") != "utf-8":
        sys.stdout = io.TextIOWrapper(out.buffer, encoding="utf-8", errors="replace")
    if hasattr(err, "buffer") and getattr(err, "encoding", "utf-8") != "utf-8":
        sys.stderr = io.TextIOWrapper(err.buffer, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MEMORY_BANK_DIR = ".github/memory-bank"
PROMPTS_DIR = ".github/prompts"
SKILLS_DIR = ".github/skills"
COPILOT_INSTRUCTIONS = ".github/copilot-instructions.md"

# memory-bank/README.md 列出的檔案
MEMORY_BANK_EXPECTED_FILES = [
    "artifact-rules.md",
    "workflow-gates.md",
    "prompt-patterns.md",
    "project-facts.md",
]

# 每個 memory-bank 檔案的必要標題
MEMORY_BANK_REQUIRED_HEADINGS: Dict[str, List[str]] = {
    "artifact-rules.md": ["Task", "Plan", "Code", "Verify"],
    "workflow-gates.md": ["Intake", "Research", "Planning", "Coding", "Review"],
    "prompt-patterns.md": ["Agent Dispatch", "Artifact Output"],
    "project-facts.md": ["技術棧", "主要組件", "環境變數"],
}

MEMORY_BANK_MAX_LINES = 120
COPILOT_INSTRUCTIONS_MAX_TOKENS = 2000  # rough: 1 token ≈ 4 chars for CJK mixed

# 交叉引用 pattern
XREF_PATTERNS = [
    re.compile(r"(?:see|見|詳見|Reference)\s+[`]?(docs/[^\s`]+)[`]?", re.IGNORECASE),
    re.compile(r"(?:see|見|詳見|Reference)\s+[`]?(\.github/[^\s`]+)[`]?", re.IGNORECASE),
    re.compile(r"(?:see|見|詳見|Reference)\s+[`]?(artifacts/[^\s`]+)[`]?", re.IGNORECASE),
]

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
NAME_RE = re.compile(r"^name:\s*(.+)$", re.MULTILINE)
HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def estimate_tokens(text: str) -> int:
    """Rough token estimate: CJK chars ≈ 1.5 tokens each, ASCII words ≈ 1 token."""
    cjk_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    ascii_words = len(re.findall(r"[a-zA-Z0-9_]+", text))
    return int(cjk_chars * 1.5 + ascii_words)


def extract_frontmatter_name(text: str) -> str | None:
    fm = FRONTMATTER_RE.search(text)
    if not fm:
        return None
    m = NAME_RE.search(fm.group(1))
    return m.group(1).strip() if m else None


def extract_headings(text: str) -> List[str]:
    return [m.group(1).strip() for m in HEADING_RE.finditer(text)]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_memory_bank_existence(root: Path) -> List[str]:
    """Check 1: memory-bank 檔案存在且非空。"""
    errors: List[str] = []
    mb = root / MEMORY_BANK_DIR
    if not mb.is_dir():
        errors.append(f"Directory missing: {MEMORY_BANK_DIR}")
        return errors
    for fname in MEMORY_BANK_EXPECTED_FILES:
        fpath = mb / fname
        if not fpath.exists():
            errors.append(f"Missing: {MEMORY_BANK_DIR}/{fname}")
        elif fpath.stat().st_size == 0:
            errors.append(f"Empty file: {MEMORY_BANK_DIR}/{fname}")
    return errors


def check_cross_references(root: Path) -> List[str]:
    """Check 2: memory-bank 檔案中的交叉引用可解析。"""
    errors: List[str] = []
    mb = root / MEMORY_BANK_DIR
    if not mb.is_dir():
        return errors
    for md_file in mb.glob("*.md"):
        text = load_text(md_file)
        for pattern in XREF_PATTERNS:
            for m in pattern.finditer(text):
                ref_path = m.group(1)
                # Strip trailing punctuation
                ref_path = ref_path.rstrip(".,;:)）」")
                if not (root / ref_path).exists():
                    errors.append(
                        f"Broken xref in {md_file.relative_to(root)}: "
                        f"'{ref_path}' not found"
                    )
    return errors


def check_frontmatter(root: Path) -> Tuple[List[str], Dict[str, List[str]]]:
    """Check 3: prompt/skill frontmatter 合法性，回傳 names mapping。"""
    errors: List[str] = []
    names: Dict[str, List[str]] = {"prompt": [], "skill": []}

    # Prompts
    prompts_dir = root / PROMPTS_DIR
    if prompts_dir.is_dir():
        for pf in prompts_dir.glob("*.md"):
            text = load_text(pf)
            rel = str(pf.relative_to(root))
            if text.startswith("---"):
                fm = FRONTMATTER_RE.search(text)
                if not fm:
                    errors.append(f"Malformed frontmatter: {rel}")
                else:
                    name = extract_frontmatter_name(text)
                    if name:
                        names["prompt"].append(name)

    # Skills
    skills_dir = root / SKILLS_DIR
    if skills_dir.is_dir():
        for skill_md in skills_dir.rglob("SKILL.md"):
            text = load_text(skill_md)
            rel = str(skill_md.relative_to(root))
            fm = FRONTMATTER_RE.search(text)
            if not fm:
                errors.append(f"Missing or malformed frontmatter: {rel}")
            else:
                name = extract_frontmatter_name(text)
                if name:
                    names["skill"].append(name)

    return errors, names


def check_name_uniqueness(names: Dict[str, List[str]]) -> List[str]:
    """Check 6: prompt/skill 名稱唯一性。"""
    errors: List[str] = []

    # Duplicate prompt names
    seen: Dict[str, int] = {}
    for n in names["prompt"]:
        seen[n] = seen.get(n, 0) + 1
    for n, count in seen.items():
        if count > 1:
            errors.append(f"Duplicate prompt name: '{n}' appears {count} times")

    # Duplicate skill names
    seen = {}
    for n in names["skill"]:
        seen[n] = seen.get(n, 0) + 1
    for n, count in seen.items():
        if count > 1:
            errors.append(f"Duplicate skill name: '{n}' appears {count} times")

    # Cross-type collision
    prompt_set: Set[str] = set(names["prompt"])
    skill_set: Set[str] = set(names["skill"])
    collisions = prompt_set & skill_set
    for c in collisions:
        errors.append(f"Name collision between prompt and skill: '{c}'")

    return errors


def check_copilot_instructions_size(root: Path) -> List[str]:
    """Check 4: copilot-instructions.md token 大小。"""
    errors: List[str] = []
    ci = root / COPILOT_INSTRUCTIONS
    if not ci.exists():
        errors.append(f"Missing: {COPILOT_INSTRUCTIONS}")
        return errors
    text = load_text(ci)
    tokens = estimate_tokens(text)
    if tokens > COPILOT_INSTRUCTIONS_MAX_TOKENS:
        errors.append(
            f"{COPILOT_INSTRUCTIONS}: ~{tokens} tokens "
            f"(limit {COPILOT_INSTRUCTIONS_MAX_TOKENS})"
        )
    return errors


def check_template_sync(root: Path) -> List[str]:
    """Check 5: template/.github/ 與根 .github/ 的同步一致性。"""
    errors: List[str] = []
    template_gh = root / "template" / ".github"
    root_gh = root / ".github"
    if not template_gh.is_dir():
        return errors  # template 不存在時不檢查

    # Check memory-bank sync
    for subdir in ["memory-bank", "prompts", "skills"]:
        root_sub = root_gh / subdir
        tmpl_sub = template_gh / subdir
        if not root_sub.is_dir():
            continue
        if not tmpl_sub.is_dir():
            errors.append(f"Missing template dir: template/.github/{subdir}")
            continue
        root_files = {f.name for f in root_sub.rglob("*.md")}
        tmpl_files = {f.name for f in tmpl_sub.rglob("*.md")}
        missing = root_files - tmpl_files
        for m in missing:
            errors.append(
                f"template/.github/{subdir} missing: {m} "
                f"(exists in .github/{subdir})"
            )

    # Check copilot-instructions.md
    root_ci = root_gh / "copilot-instructions.md"
    tmpl_ci = template_gh / "copilot-instructions.md"
    if root_ci.exists() and not tmpl_ci.exists():
        errors.append("template/.github/copilot-instructions.md missing")

    return errors


def check_memory_bank_quality(root: Path) -> List[str]:
    """Check 7: memory-bank 檔案品質（行數、標題、orphan section、source ref）。"""
    errors: List[str] = []
    warnings: List[str] = []
    mb = root / MEMORY_BANK_DIR
    if not mb.is_dir():
        return errors

    for fname in MEMORY_BANK_EXPECTED_FILES:
        fpath = mb / fname
        if not fpath.exists():
            continue
        text = load_text(fpath)
        lines = text.splitlines()
        rel = f"{MEMORY_BANK_DIR}/{fname}"

        # Line count
        if len(lines) > MEMORY_BANK_MAX_LINES:
            warnings.append(
                f"{rel}: {len(lines)} lines (limit {MEMORY_BANK_MAX_LINES}), "
                f"consider consolidation"
            )

        # Required headings
        headings = extract_headings(text)
        heading_lower = [h.lower() for h in headings]
        for req in MEMORY_BANK_REQUIRED_HEADINGS.get(fname, []):
            if not any(req.lower() in h for h in heading_lower):
                errors.append(f"{rel}: missing required heading containing '{req}'")

        # Orphan sections (heading followed by another heading or EOF with no content)
        # Skip headings inside code fences
        in_fence = False
        for i, line in enumerate(lines):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            if re.match(r"^#{1,3}\s+", line):
                # Look ahead for content before next heading or EOF
                has_content = False
                fence_depth = False
                for j in range(i + 1, min(i + 15, len(lines))):
                    stripped = lines[j].strip()
                    if stripped.startswith("```"):
                        fence_depth = not fence_depth
                        # A code fence opening counts as content
                        if fence_depth:
                            has_content = True
                            break
                    if re.match(r"^#{1,3}\s+", lines[j]):
                        break
                    if stripped and not stripped.startswith("<!--"):
                        has_content = True
                        break
                if not has_content:
                    heading_text = line.strip()
                    warnings.append(f"{rel}: orphan section '{heading_text}' (no content)")

    return errors + warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    init_streams()
    parser = argparse.ArgumentParser(description="Context Stack Validator")
    parser.add_argument("--root", default=".", help="Repository root")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    all_errors: List[str] = []
    all_warnings: List[str] = []

    checks = [
        ("Memory Bank existence", check_memory_bank_existence),
        ("Cross-references", check_cross_references),
        ("Copilot instructions size", check_copilot_instructions_size),
        ("Template sync", check_template_sync),
    ]

    for label, fn in checks:
        print(f"[CHECK] {label}...")
        issues = fn(root)
        if issues:
            for i in issues:
                print(f"  FAIL: {i}")
            all_errors.extend(issues)
        else:
            print("  OK")

    # Frontmatter + name uniqueness (coupled)
    print("[CHECK] Frontmatter validity...")
    fm_errors, names = check_frontmatter(root)
    if fm_errors:
        for e in fm_errors:
            print(f"  FAIL: {e}")
        all_errors.extend(fm_errors)
    else:
        print("  OK")

    print("[CHECK] Name uniqueness...")
    name_errors = check_name_uniqueness(names)
    if name_errors:
        for e in name_errors:
            print(f"  FAIL: {e}")
        all_errors.extend(name_errors)
    else:
        print("  OK")

    print("[CHECK] Memory Bank quality...")
    quality_issues = check_memory_bank_quality(root)
    if quality_issues:
        for q in quality_issues:
            severity = "WARN" if "consider" in q or "orphan" in q else "FAIL"
            print(f"  {severity}: {q}")
            if severity == "FAIL":
                all_errors.append(q)
            else:
                all_warnings.append(q)
    else:
        print("  OK")

    # Summary
    print()
    if all_errors:
        print(f"FAILED: {len(all_errors)} error(s), {len(all_warnings)} warning(s)")
        return 1
    elif all_warnings:
        print(f"PASSED with {len(all_warnings)} warning(s)")
        return 0
    else:
        print("PASSED: all checks OK")
        return 0


if __name__ == "__main__":
    sys.exit(main())
