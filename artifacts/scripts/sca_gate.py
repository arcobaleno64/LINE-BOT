#!/usr/bin/env python3
"""sca_gate.py — fail-closed Software Composition Analysis (SCA) gate.

Turns a scanner's machine-readable output into a hard pass/fail exit code, closing
the known false-pass traps of raw shell heuristics. Currently supports the .NET
``dotnet list package --vulnerable --include-transitive --format json`` output, whose
notorious gotcha is that it exits 0 even when vulnerable packages are present — so a
naive ``grep`` gate silently passes vulnerable dependency sets.

This gate is FAIL-CLOSED: it exits non-zero (1) on ANY of —
  - at least one package (top-level or transitive) carrying a non-empty
    ``vulnerabilities`` array,
  - JSON that is malformed / empty,
  - the expected schema being absent or the wrong shape (a future SDK format drift
    must NOT silently read as "no vulnerabilities"),
  - an empty ``projects`` list (a restore/build failure produces no projects).
It exits 0 ONLY when the output is the expected shape AND no package is vulnerable.

Source-only + mirrored into template/ (and EXACT_SYNC) so retrofitted downstream repos
can call it from their opt-in security-scan workflow. Read-only, pure parsing — it does
NOT execute the scanner (no subprocess), matching the same architectural boundary as
ssdf_mapping_validator.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional, Sequence, Tuple

EXIT_OK = 0
EXIT_VULN = 1   # vulnerabilities found OR fail-closed (malformed/unexpected/empty)
EXIT_USAGE = 2  # usage / IO error

# Supported values of the dotnet ``--format json`` report ``version`` field. An unknown
# version is failed CLOSED (not silently read as the version-1 schema): a future SDK
# could keep ``projects`` a list while renaming/moving the ``vulnerabilities`` field,
# which would otherwise read as "no vulnerabilities". Add a new value only after the
# new schema has been verified and the parser updated.
SUPPORTED_DOTNET_REPORT_VERSIONS = frozenset({1})


def _fail(reason: str) -> Tuple[int, str]:
    return EXIT_VULN, reason


def evaluate_dotnet(payload: object) -> Tuple[int, str]:
    """Evaluate a parsed ``dotnet list package --vulnerable --format json`` document.

    Returns ``(exit_code, message)``. Fail-closed: any schema surprise -> EXIT_VULN.
    """
    if not isinstance(payload, dict):
        return _fail("unexpected schema: top-level is not an object")
    if "version" not in payload:
        return _fail("unexpected schema: missing 'version' field")
    # Exact int typing BEFORE membership: Python treats ``True == 1``, so a bare
    # ``payload["version"] in {1}`` would accept JSON ``true`` as version 1. ``type() is
    # int`` excludes the ``bool`` subclass; a string "1" is rejected too. Unknown -> closed.
    report_version = payload["version"]
    if type(report_version) is not int or report_version not in SUPPORTED_DOTNET_REPORT_VERSIONS:
        return _fail(
            f"unsupported dotnet report version {report_version!r} — verify schema then update sca_gate"
        )
    projects = payload.get("projects")
    if not isinstance(projects, list):
        return _fail("unexpected schema: 'projects' is not a list")
    if not projects:
        return _fail("no projects in output (restore/build likely failed) — failing closed")

    vulnerable: List[str] = []
    for project in projects:
        if not isinstance(project, dict):
            return _fail("unexpected schema: a project entry is not an object")
        frameworks = project.get("frameworks", [])
        if not isinstance(frameworks, list):
            return _fail("unexpected schema: 'frameworks' is not a list")
        for framework in frameworks:
            if not isinstance(framework, dict):
                return _fail("unexpected schema: a framework entry is not an object")
            for bucket in ("topLevelPackages", "transitivePackages"):
                packages = framework.get(bucket, [])
                if not isinstance(packages, list):
                    return _fail(f"unexpected schema: '{bucket}' is not a list")
                for package in packages:
                    if not isinstance(package, dict):
                        return _fail(f"unexpected schema: a {bucket} entry is not an object")
                    vulns = package.get("vulnerabilities")
                    if vulns:
                        if not isinstance(vulns, list):
                            return _fail("unexpected schema: 'vulnerabilities' is not a list")
                        pkg_id = package.get("id", "<unknown>")
                        vulnerable.append(f"{pkg_id} ({len(vulns)} advisory/-ies)")

    if vulnerable:
        return EXIT_VULN, "vulnerable packages: " + ", ".join(sorted(vulnerable))
    return EXIT_OK, "no vulnerable packages"


def load_json(text: str) -> Tuple[Optional[object], Optional[str]]:
    """Parse JSON text. Returns (payload, error). Empty/malformed -> error set."""
    if not text.strip():
        return None, "empty output"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"malformed JSON: {exc}"


def read_source(path: str) -> str:
    """Read the scan output from a file path, or stdin when path is '-'."""
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed SCA gate for scanner output.")
    parser.add_argument("tool", choices=["dotnet"], help="Scanner whose output to gate.")
    parser.add_argument("--json", required=True, help="Path to the scanner JSON output, or '-' for stdin.")
    return parser.parse_args(argv)


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        text = read_source(args.json)
    except OSError as exc:
        print(f"[FAIL] cannot read scan output: {exc}", file=sys.stderr)
        return EXIT_USAGE
    payload, error = load_json(text)
    if error is not None:
        print(f"[FAIL] {args.tool} SCA gate: {error} — failing closed", file=sys.stderr)
        return EXIT_VULN
    code, message = evaluate_dotnet(payload)
    stream = sys.stderr if code != EXIT_OK else sys.stdout
    print(f"[{'FAIL' if code else 'OK'}] {args.tool} SCA gate: {message}", file=stream)
    return code


def main() -> int:  # pragma: no cover - thin CLI glue
    return run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
