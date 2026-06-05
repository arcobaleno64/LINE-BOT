from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence, Tuple


@dataclass(frozen=True)
class LegacyVerifyCorpusCase:
    case_id: str
    fixture_name: str
    strategy: str
    confidence: str
    manual_review_required: bool
    expected_pass_fail_result: str
    expected_checklist_result: str
    expected_reason_code: str
    expected_unresolved_fields: Tuple[str, ...]
    summary_fragment: str
    text: str


def corpus_root() -> Path:
    return Path(__file__).resolve().parent.parent / "test" / "legacy_verify_corpus"


def _load_manifest(root: Path) -> Sequence[dict]:
    manifest_path = root / "manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def load_corpus_cases(root: Path | None = None) -> List[LegacyVerifyCorpusCase]:
    base_root = root or corpus_root()
    cases: List[LegacyVerifyCorpusCase] = []
    for row in _load_manifest(base_root):
        fixture_path = base_root / row["fixture_name"]
        cases.append(
            LegacyVerifyCorpusCase(
                case_id=str(row["case_id"]),
                fixture_name=str(row["fixture_name"]),
                strategy=str(row["strategy"]),
                confidence=str(row["confidence"]),
                manual_review_required=bool(row["manual_review_required"]),
                expected_pass_fail_result=str(row["expected_pass_fail_result"]),
                expected_checklist_result=str(row["expected_checklist_result"]),
                expected_reason_code=str(row.get("expected_reason_code", "")),
                expected_unresolved_fields=tuple(row.get("expected_unresolved_fields", [])),
                summary_fragment=str(row["summary_fragment"]),
                text=fixture_path.read_text(encoding="utf-8"),
            )
        )
    return cases


def load_corpus_case(case_id: str, root: Path | None = None) -> LegacyVerifyCorpusCase:
    for case in load_corpus_cases(root):
        if case.case_id == case_id:
            return case
    raise KeyError(f"legacy verify corpus case not found: {case_id}")
