#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

ROW_PATTERN = re.compile(
    r"^\|\s*`?(?P<case>[^|`]+)`?\s*\|\s*(?P<phase>[^|]+)\|\s*(?P<expected>[^|]+)\|\s*(?P<outcome>[^|]+)\|\s*(?P<exit>[^|]+)\|\s*(?P<baseline>[^|]+)\|\s*(?P<delta>[^|]+)\|\s*(?P<final>[^|]+)\|\s*`?(?P<evidence>[^|`]+)`?\s*\|\s*(?P<notes>[^|]*)\|\s*$"
)

EMPTY_NOTES_VALUES = {
    "",
    "none",
    "n/a",
    "na",
    "tbd",
    "-",
    "待補",
    "待補充",
}


@dataclass
class Row:
    case: str
    reviewer_delta: int
    notes: str


def parse_rows(markdown: str) -> List[Row]:
    rows: List[Row] = []
    for line in markdown.splitlines():
        match = ROW_PATTERN.match(line.strip())
        if not match:
            continue
        case_value = match.group("case").strip()
        phase_value = match.group("phase").strip()
        if case_value in {"Case", "---"} or phase_value == "---":
            continue
        delta_raw = match.group("delta").strip()
        try:
            delta_value = int(delta_raw)
        except ValueError:
            continue
        rows.append(Row(case=case_value, reviewer_delta=delta_value, notes=match.group("notes").strip()))
    return rows


def validate_rows(rows: Sequence[Row]) -> List[str]:
    failures: List[str] = []
    for row in rows:
        if row.reviewer_delta == 0:
            continue
        notes_normalized = row.notes.strip().lower()
        if notes_normalized in EMPTY_NOTES_VALUES:
            failures.append(
                f"{row.case}: Reviewer Delta = {row.reviewer_delta}, but Notes is empty or placeholder"
            )
    return failures


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate scorecard reviewer deltas. Non-zero delta must include a concrete Notes reason."
    )
    parser.add_argument(
        "--scorecard",
        required=True,
        help="Path to scorecard markdown file, for example docs/red_team_scorecard.generated.md",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    scorecard_path = Path(args.scorecard).resolve()

    if not scorecard_path.exists():
        print(f"[FAIL] scorecard file not found: {scorecard_path}")
        return 1

    rows = parse_rows(scorecard_path.read_text(encoding="utf-8"))
    if not rows:
        print("[FAIL] no scorecard rows found")
        return 1

    failures = validate_rows(rows)
    if failures:
        print("[ERROR] Scorecard delta validation failed")
        for failure in failures:
            print(f"[FAIL] {failure}")
        return 1

    print("[OK] Scorecard delta validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
