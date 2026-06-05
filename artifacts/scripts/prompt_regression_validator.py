#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence


@dataclass
class AssertionFailure:
    file: str
    message: str
    note: str


@dataclass
class CaseResult:
    case_id: str
    title: str
    passed: bool
    failures: List[AssertionFailure]
    skipped: bool = False


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.lower()


def contains_any(text: str, candidates: Sequence[str]) -> bool:
    return any(candidate.lower() in text for candidate in candidates)


def check_near_terms(text: str, terms: Sequence[str], max_chars: int) -> bool:
    positions: List[int] = []
    for term in terms:
        match = re.search(re.escape(term.lower()), text)
        if not match:
            return False
        positions.append(match.start())
    return max(positions) - min(positions) <= max_chars


def load_cases(cases_path: Path) -> List[dict]:
    try:
        payload = json.loads(cases_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Cases file not found: {cases_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {cases_path}: {exc}") from exc
    if not isinstance(payload, list):
        raise RuntimeError("Cases payload must be a list")
    return payload


def detect_repo_mode(root: Path) -> str:
    """Source repos carry the .council-forge-source-repo sentinel; others are downstream terminal repos."""
    return "source" if (root / ".council-forge-source-repo").exists() else "downstream"


def is_brownfield(root: Path) -> bool:
    """A brownfield downstream (retrofitted onto an existing repo) keeps its own
    project CLAUDE.md / README; assertions targeting those project-owned files are
    skipped for it, because that content is guaranteed by the EXACT_SYNC docs and the
    overlaid GEMINI/CODEX prompts instead."""
    return (root / ".council-forge-brownfield").exists()


# Files a brownfield downstream owns (its own project versions); council-forge's prompt
# assertions targeting these are skipped for brownfield repos.
BROWNFIELD_PROJECT_OWNED_FILES = {"CLAUDE.md", "README.md", "README.zh-TW.md"}


def case_applies(case: dict, mode: str) -> bool:
    """A case runs when its optional ``applies_to`` is absent/"all" or matches the repo mode.

    Source-only cases (e.g. the source/template sync split) assert template/ files that a
    downstream terminal repo deliberately lacks, so they are skipped in downstream mode.
    """
    applies = str(case.get("applies_to", "all")).strip().lower()
    return applies in ("all", mode)


def evaluate_case(case: dict, root: Path, cache: Dict[str, str]) -> CaseResult:
    case_id = str(case.get("id", ""))
    title = str(case.get("title", ""))
    failures: List[AssertionFailure] = []
    brownfield = is_brownfield(root)

    assertions = case.get("assertions", [])
    if not isinstance(assertions, list) or not assertions:
        failures.append(AssertionFailure(file="(case)", message="Case has no assertions", note="Add assertion entries"))
        return CaseResult(case_id=case_id, title=title, passed=False, failures=failures)

    for assertion in assertions:
        file_name = str(assertion.get("file", "")).strip()
        note = str(assertion.get("note", "")).strip()
        if not file_name:
            failures.append(AssertionFailure(file="(case)", message="Assertion missing file", note=note))
            continue
        if brownfield and file_name in BROWNFIELD_PROJECT_OWNED_FILES:
            # Brownfield downstream owns its project CLAUDE.md / README; council-forge's
            # orchestrator + product-README content is guaranteed via the EXACT_SYNC docs
            # and the overlaid GEMINI/CODEX prompts instead.
            continue

        if file_name not in cache:
            path = root / file_name
            if not path.exists():
                failures.append(AssertionFailure(file=file_name, message="Target file missing", note=note))
                continue
            cache[file_name] = normalize_text(path.read_text(encoding="utf-8"))
        text = cache[file_name]

        groups = assertion.get("all_of_any", [])
        if groups:
            if not isinstance(groups, list):
                failures.append(AssertionFailure(file=file_name, message="all_of_any must be a list", note=note))
                continue
            for group in groups:
                if not isinstance(group, list) or not group:
                    failures.append(AssertionFailure(file=file_name, message="each all_of_any group must be a non-empty list", note=note))
                    continue
                if not contains_any(text, [str(item) for item in group]):
                    failures.append(
                        AssertionFailure(
                            file=file_name,
                            message=f"missing required semantic bundle: one of {group}",
                            note=note,
                        )
                    )

        must_contain_all = assertion.get("must_contain_all", [])
        if must_contain_all:
            if not isinstance(must_contain_all, list):
                failures.append(AssertionFailure(file=file_name, message="must_contain_all must be a list", note=note))
                continue
            for required in must_contain_all:
                term = str(required)
                if term.lower() not in text:
                    failures.append(
                        AssertionFailure(
                            file=file_name,
                            message=f"missing required term: {term}",
                            note=note,
                        )
                    )

        must_not_contain_any = assertion.get("must_not_contain_any", [])
        if must_not_contain_any:
            if not isinstance(must_not_contain_any, list):
                failures.append(AssertionFailure(file=file_name, message="must_not_contain_any must be a list", note=note))
                continue
            for forbidden in must_not_contain_any:
                term = str(forbidden)
                if term.lower() in text:
                    failures.append(
                        AssertionFailure(
                            file=file_name,
                            message=f"forbidden term detected: {term}",
                            note=note,
                        )
                    )

        near_items = assertion.get("near", [])
        if near_items:
            if not isinstance(near_items, list):
                failures.append(AssertionFailure(file=file_name, message="near must be a list", note=note))
                continue
            for near in near_items:
                terms = near.get("terms", []) if isinstance(near, dict) else []
                max_chars = int(near.get("max_chars", 250)) if isinstance(near, dict) else 250
                if not isinstance(terms, list) or len(terms) < 2:
                    failures.append(AssertionFailure(file=file_name, message="near.terms must contain at least 2 terms", note=note))
                    continue
                if not check_near_terms(text, [str(term) for term in terms], max_chars):
                    failures.append(
                        AssertionFailure(
                            file=file_name,
                            message=f"terms must appear near each other (<= {max_chars} chars): {terms}",
                            note=note,
                        )
                    )

    return CaseResult(case_id=case_id, title=title, passed=not failures, failures=failures)


def render_report(results: Sequence[CaseResult]) -> str:
    lines: List[str] = [
        "# Prompt Regression Report",
        "",
        "| Case | Title | Outcome | Failures |",
        "|---|---|---|---:|",
    ]
    for result in results:
        outcome = "skip" if result.skipped else ("pass" if result.passed else "fail")
        lines.append(f"| `{result.case_id}` | {result.title} | {outcome} | {len(result.failures)} |")

    lines.append("")
    lines.append("## Failure Details")
    has_failure = False
    for result in results:
        if result.passed:
            continue
        has_failure = True
        lines.append(f"### {result.case_id}: {result.title}")
        for failure in result.failures:
            lines.append(f"- `{failure.file}`: {failure.message}")
            if failure.note:
                lines.append(f"  note: {failure.note}")
        lines.append("")

    if not has_failure:
        lines.append("None")

    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run prompt regression test cases for workflow entry prompts and related contract docs")
    parser.add_argument("--root", default=".", help="Repository root. Default: current directory")
    parser.add_argument(
        "--cases",
        default="artifacts/scripts/drills/prompt_regression_cases.json",
        help="Path to regression cases JSON. Default: artifacts/scripts/drills/prompt_regression_cases.json",
    )
    parser.add_argument("--case-id", help="Run only one case id")
    parser.add_argument("--output", help="Optional markdown report path")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    cases_path = (root / args.cases).resolve()

    try:
        cases = load_cases(cases_path)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")
        return 1

    if args.case_id:
        cases = [case for case in cases if str(case.get("id", "")) == args.case_id]
        if not cases:
            print(f"[FAIL] case id not found: {args.case_id}")
            return 1

    cache: Dict[str, str] = {}
    mode = detect_repo_mode(root)
    results: List[CaseResult] = []
    for case in cases:
        if case_applies(case, mode):
            results.append(evaluate_case(case, root, cache))
        else:
            results.append(
                CaseResult(
                    case_id=str(case.get("id", "")),
                    title=str(case.get("title", "")),
                    passed=True,
                    failures=[],
                    skipped=True,
                )
            )
    report = render_report(results)
    print(report, end="")

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")

    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
