#!/usr/bin/env python3
"""sast_gate.py — fail-closed SARIF static-analysis (SAST) gate, advisory by default.

Normalizes any analyzer's SARIF 2.1.0 output into a pass/fail decision. Unlike the SCA
gate (which is enforcing), this gate is ADVISORY BY DEFAULT: valid SARIF with findings
still exits 0, because SAST is prone to false-positive avalanche and council-forge adopts
it advisory-first (findings are surfaced, not auto-failed). ``--enforce --min-level`` flips
it to a hard gate once a finding baseline exists.

It is nonetheless FAIL-CLOSED on untrustworthy input — it exits non-zero (1) on ANY of —
  - JSON that is malformed / empty,
  - a SARIF ``version`` that is absent, non-string, or not a supported value (a future
    tool/format drift must NOT silently read as "no findings"; mirrors sca_gate's
    version fail-closed discipline, with the SARIF ``version`` being a string),
  - a ``runs`` / ``results`` shape that is not the expected list-of-objects,
  - a ``result.level`` that is present but not one of the SARIF-defined levels (an unknown
    level must not be silently dropped — that would be a false-negative).
We do not "advise" on garbage: advisory applies to *findings*, never to a broken document.

``--summary-file <path>`` appends a per-finding markdown summary to the given file (in CI,
``$GITHUB_STEP_SUMMARY``) so advisory findings are durably reviewable after the job, closing
the "reporting-not-control" gap without introducing a new (unpinned) GitHub Action.

Source-only + mirrored into template/ (and EXACT_SYNC) so retrofitted downstream repos can
call it from their opt-in SAST workflow. Read-only, pure parsing — it does NOT execute any
analyzer (no subprocess), matching the same architectural boundary as sca_gate.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, NamedTuple, Optional, Sequence, Tuple

EXIT_OK = 0      # valid SARIF; advisory, OR enforce with nothing at/above the threshold
EXIT_FAIL = 1    # findings at/above --min-level (enforce) OR fail-closed (malformed/unknown)
EXIT_USAGE = 2   # usage / IO error

# Supported SARIF schema versions. An unknown version fails CLOSED rather than being read
# as 2.1.0: a future tool could keep the top-level shape while moving where findings live,
# which would otherwise read as "no findings". The SARIF ``version`` is a STRING ("2.1.0"),
# so the type check is ``is str`` (the SCA gate's analogous field is an int).
SUPPORTED_SARIF_VERSIONS = frozenset({"2.1.0"})

# SARIF result levels, ordered weakest -> strongest for ``--min-level`` comparison.
SARIF_LEVELS: Tuple[str, ...] = ("none", "note", "warning", "error")
SUPPORTED_SARIF_LEVELS = frozenset(SARIF_LEVELS)
# SARIF spec: when ``result.level`` is absent the effective level defaults to "warning"
# (after rule-default resolution, which this normalizing gate does not model). An explicit
# but unknown level is NOT defaulted — it fails closed (see extract_findings).
DEFAULT_LEVEL = "warning"


class Finding(NamedTuple):
    rule_id: str
    level: str
    message: str
    location: str


def _message_text(result: dict) -> str:
    """Best-effort extraction of result.message.text (informational; never fail-closed)."""
    message = result.get("message")
    if isinstance(message, dict):
        text = message.get("text")
        if isinstance(text, str):
            return text
    return ""


def _location(result: dict) -> str:
    """Best-effort first-location ``uri:line`` (informational; never fail-closed)."""
    locations = result.get("locations")
    if not isinstance(locations, list) or not locations:
        return "<unknown>"
    first = locations[0]
    if not isinstance(first, dict):
        return "<unknown>"
    physical = first.get("physicalLocation")
    if not isinstance(physical, dict):
        return "<unknown>"
    artifact = physical.get("artifactLocation")
    uri = artifact.get("uri") if isinstance(artifact, dict) else None
    region = physical.get("region")
    line = region.get("startLine") if isinstance(region, dict) else None
    if isinstance(uri, str) and isinstance(line, int) and not isinstance(line, bool):
        return f"{uri}:{line}"
    if isinstance(uri, str):
        return uri
    return "<unknown>"


def extract_findings(payload: object) -> Tuple[Optional[List[Finding]], Optional[str]]:
    """Parse a SARIF document into findings. Returns ``(findings, error)``.

    A non-None ``error`` signals a fail-closed condition (the caller exits non-zero). The
    security-relevant structure (version, runs, results, level) is validated strictly; the
    purely informational fields (message, location) are parsed best-effort.
    """
    if not isinstance(payload, dict):
        return None, "unexpected SARIF: top-level is not an object"
    version = payload.get("version")
    # Exact str typing BEFORE membership (mirrors sca_gate's exact-int discipline): reject a
    # missing/None/numeric/bool version, and any unrecognised string, as fail-closed.
    if type(version) is not str or version not in SUPPORTED_SARIF_VERSIONS:
        return None, f"unsupported SARIF version {version!r} — verify schema then update sast_gate"
    runs = payload.get("runs")
    if not isinstance(runs, list):
        return None, "unexpected SARIF: 'runs' is not a list"

    findings: List[Finding] = []
    for run in runs:
        if not isinstance(run, dict):
            return None, "unexpected SARIF: a run entry is not an object"
        results = run.get("results", [])
        if results is None:  # SARIF allows an absent/null results array (no findings)
            results = []
        if not isinstance(results, list):
            return None, "unexpected SARIF: 'results' is not a list"
        for result in results:
            if not isinstance(result, dict):
                return None, "unexpected SARIF: a result entry is not an object"
            rule_id = result.get("ruleId", "<unknown>")
            if not isinstance(rule_id, str):
                return None, "unexpected SARIF: 'ruleId' is not a string"
            level = result.get("level", DEFAULT_LEVEL)
            if not isinstance(level, str) or level not in SUPPORTED_SARIF_LEVELS:
                return None, f"unknown SARIF result level {level!r} — failing closed"
            findings.append(Finding(rule_id, level, _message_text(result), _location(result)))
    return findings, None


def _level_rank(level: str) -> int:
    return SARIF_LEVELS.index(level)


def summarize(findings: Sequence[Finding]) -> str:
    if not findings:
        return "no SARIF findings"
    highest = max(findings, key=lambda finding: _level_rank(finding.level)).level
    return f"{len(findings)} SARIF finding(s); highest level: {highest}"


def decide(findings: Sequence[Finding], *, enforce: bool, min_level: str) -> Tuple[int, str]:
    """Map parsed findings to ``(exit_code, message)``. Advisory unless ``enforce``."""
    summary = summarize(findings)
    if not enforce:
        return EXIT_OK, summary
    threshold = _level_rank(min_level)
    blocking = [finding for finding in findings if _level_rank(finding.level) >= threshold]
    if blocking:
        return EXIT_FAIL, f"{len(blocking)} finding(s) at or above '{min_level}' (enforce) — {summary}"
    return EXIT_OK, f"no findings at or above '{min_level}' (enforce) — {summary}"


def render_summary_markdown(findings: Sequence[Finding]) -> str:
    """Per-finding markdown for $GITHUB_STEP_SUMMARY (durable advisory exposure)."""
    lines = ["", "### SAST (SARIF) findings — advisory", ""]
    if not findings:
        lines.append("No SARIF findings.")
    else:
        lines.append(f"Total: {len(findings)} finding(s).")
        lines.append("")
        lines.append("| Level | Rule | Location | Message |")
        lines.append("|---|---|---|---|")
        for finding in findings:
            message = finding.message.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {finding.level} | {finding.rule_id} | {finding.location} | {message} |")
    return "\n".join(lines) + "\n"


def append_summary(path: str, findings: Sequence[Finding]) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(render_summary_markdown(findings))


def load_json(text: str) -> Tuple[Optional[object], Optional[str]]:
    """Parse JSON text. Returns (payload, error). Empty/malformed -> error set."""
    if not text.strip():
        return None, "empty output"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"malformed JSON: {exc}"


def read_source(path: str) -> str:
    """Read SARIF from a file path, or stdin when path is '-'."""
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed SARIF SAST gate (advisory by default).")
    parser.add_argument("--sarif", required=True, help="Path to SARIF 2.1.0 JSON, or '-' for stdin.")
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Fail (exit 1) when a finding reaches --min-level. Default is advisory (exit 0).",
    )
    parser.add_argument(
        "--min-level",
        choices=["error", "warning"],
        default="error",
        help="Enforce threshold, used only with --enforce (default: error).",
    )
    parser.add_argument(
        "--summary-file",
        help="Append a per-finding markdown summary to this file (e.g. $GITHUB_STEP_SUMMARY) "
        "for durable advisory exposure.",
    )
    return parser.parse_args(argv)


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        text = read_source(args.sarif)
    except OSError as exc:
        print(f"[FAIL] cannot read SARIF: {exc}", file=sys.stderr)
        return EXIT_USAGE
    payload, error = load_json(text)
    if error is not None:
        print(f"[FAIL] SAST gate: {error} — failing closed", file=sys.stderr)
        return EXIT_FAIL
    findings, parse_error = extract_findings(payload)
    if parse_error is not None:
        print(f"[FAIL] SAST gate: {parse_error} — failing closed", file=sys.stderr)
        return EXIT_FAIL
    if args.summary_file:
        try:
            append_summary(args.summary_file, findings)
        except OSError as exc:
            print(f"[FAIL] cannot write summary file: {exc}", file=sys.stderr)
            return EXIT_USAGE
    code, message = decide(findings, enforce=args.enforce, min_level=args.min_level)
    stream = sys.stderr if code != EXIT_OK else sys.stdout
    label = "FAIL" if code else ("ADVISORY" if findings else "OK")
    print(f"[{label}] SAST gate: {message}", file=stream)
    return code


def main() -> int:  # pragma: no cover - thin CLI glue
    return run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
