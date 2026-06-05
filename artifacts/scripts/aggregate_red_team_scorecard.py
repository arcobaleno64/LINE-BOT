#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence


@dataclass(init=False)
class CaseRow:
    case: str
    phase: str
    expected: str
    outcome: str
    expected_exit_code: str
    actual_exit_code: str
    evidence: str
    notes: str

    def __init__(
        self,
        case: str,
        phase: str,
        expected: str,
        outcome: str,
        expected_exit_code: str,
        actual_exit_code: str,
        evidence: str = "",
        notes: str = "",
    ) -> None:
        self.case = case
        self.phase = phase
        self.expected = expected
        self.outcome = outcome
        self.expected_exit_code = expected_exit_code
        if notes == "" and not str(actual_exit_code).isdigit():
            self.actual_exit_code = expected_exit_code
            self.evidence = actual_exit_code
            self.notes = evidence
        else:
            self.actual_exit_code = actual_exit_code
            self.evidence = evidence
            self.notes = notes

    @property
    def case_passed(self) -> bool:
        return self.outcome.strip().lower() == "pass"


def parse_report(markdown: str) -> List[CaseRow]:
    rows: List[CaseRow] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        parts = [part.strip() for part in stripped.split("|")[1:-1]]
        if len(parts) not in {7, 8}:
            continue
        case_value = parts[0].strip("`").strip()
        phase_value = parts[1].strip()
        if case_value in {"Case", "---"} or phase_value == "---":
            continue
        if len(parts) == 7:
            expected, outcome, exit_code, evidence, notes = parts[2:]
            expected_exit_code = exit_code
            actual_exit_code = exit_code
        else:
            expected, outcome, expected_exit_code, actual_exit_code, evidence, notes = parts[2:]
        rows.append(
            CaseRow(
                case=case_value,
                phase=phase_value,
                expected=expected.strip(),
                outcome=outcome.strip(),
                expected_exit_code=expected_exit_code.strip(),
                actual_exit_code=actual_exit_code.strip(),
                evidence=evidence.strip("`").strip(),
                notes=notes.strip(),
            )
        )
    return rows


def auto_score(row: CaseRow) -> int:
    return 2 if row.case_passed else 0


def build_scorecard(rows: Sequence[CaseRow], report_path: Path) -> str:
    timestamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds")
    lines: List[str] = [
        "# Red Team Scorecard (Semi-Auto)",
        "",
        "此檔由 `artifacts/scripts/aggregate_red_team_scorecard.py` 依 red-team report 自動產生。",
        f"",
        "## Metadata",
        f"- Source Report: `{report_path.as_posix()}`",
        f"- Generated At: {timestamp}",
        "- Timezone: Asia/Taipei (+08:00)",
        "",
        "## Aggregated Cases",
        "",
        "| Case | Phase | Expected | Outcome | Exit | Auto Baseline (0-2) | Reviewer Delta (-1/0/+1) | Final (0-2) | Evidence | Notes |",
        "|---|---|---|---|---:|---:|---:|---:|---|---|",
    ]

    for row in rows:
        baseline = auto_score(row)
        lines.append(
            "| `{case}` | {phase} | {expected} | {outcome} | {exit_code} | {baseline} | 0 | {baseline} | `{evidence}` | {notes} |".format(
                case=row.case,
                phase=row.phase,
                expected=row.expected,
                outcome=row.outcome,
                exit_code=row.actual_exit_code,
                baseline=baseline,
                evidence=row.evidence,
                notes=row.notes or "None",
            )
        )

    total = len(rows)
    passed = sum(1 for row in rows if row.case_passed)
    failed = total - passed
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Cases: {total}",
            f"- Case Passed: {passed}",
            f"- Case Failed: {failed}",
            "",
            "## Review Rules",
            "",
            "- `Auto Baseline (0-2)`: 2 = `Outcome` 為 pass；0 = `Outcome` 為 fail。",
            "- `Reviewer Delta`: 僅允許 `-1`、`0`、`+1`，且任何非 0 都要在 Notes 補原因。",
            "- `Final`: `clamp(Auto Baseline + Reviewer Delta, 0, 2)`。",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a semi-automated red team scorecard from suite report markdown.")
    parser.add_argument("--report", required=True, help="Path to markdown report from run_red_team_suite.py --output")
    parser.add_argument("--output", default="docs/red_team_scorecard.generated.md", help="Output markdown path")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report_path = Path(args.report).resolve()
    output_path = Path(args.output).resolve()

    if not report_path.exists():
        print(f"[FAIL] report file not found: {report_path}")
        return 1

    rows = parse_report(report_path.read_text(encoding="utf-8"))
    if not rows:
        print("[FAIL] no report rows found; ensure report contains the markdown table generated by run_red_team_suite.py")
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_scorecard(rows, report_path), encoding="utf-8")
    print(f"[OK] scorecard written: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
