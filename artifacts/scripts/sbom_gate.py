#!/usr/bin/env python3
"""sbom_gate.py — fail-closed CycloneDX SBOM gate.

Validates a CycloneDX JSON SBOM's well-formedness, presence, and DIRECT-dependency identity,
turning a generator's output into a hard pass/fail exit code. Read-only, pure parsing — it
does NOT execute any SBOM generator (no subprocess), matching sca_gate.py / sast_gate.py.

FAIL-CLOSED (exit 1) on ANY of —
  - JSON that is malformed / empty,
  - ``bomFormat`` != exactly "CycloneDX" (the CycloneDX JSON schema defines it as a ``const``;
    a non-exact value — wrong case, missing, non-string — is a spec violation, NOT folded),
  - a ``specVersion`` that is absent / non-string / not a supported value (schema-drift
    discipline, mirroring sca_gate's int-version and sast_gate's str-version checks),
  - a ``version`` (BOM revision) present but not an int >= 1,
  - a ``components`` shape that is not a list, or a component without a non-empty string name
    or with a ``type`` not valid FOR THAT BOM's specVersion (a single union type-set would
    fail-open: an older-spec BOM carrying a newer-only type like ``cryptographic-asset``
    would otherwise pass),
  - fewer than ``--min-components`` components (default 1, so an empty/missing components
    array fails closed; ``--min-components 0`` is the explicit opt-out for zero-dep projects),
  - a ``--require-components`` direct-dependency name that is absent from the SBOM (identity:
    a count-only floor can be satisfied by unrelated components, so we also assert the
    declared direct dependencies are actually present).

HONESTY BOUNDARY (explicit, accepted risk): this gate verifies well-formedness + presence +
DIRECT-dependency identity. It does NOT — and no gate can, without re-deriving the graph or
trusting another enumerator whose own completeness is unverifiable (infinite regress) — verify
EXHAUSTIVE transitive completeness vs the true dependency graph. That residual is an
EXPLICITLY ACCEPTED RISK, mitigated by a resolved-environment generation recipe (captures
transitive by construction), an unmissable advisory printed on EVERY run, and a non-blocking
periodic audit (a defined follow-up). The gate never fails on the un-knowable: it is not a
build-break to acknowledge a standing limitation.

Source-only + mirrored into template/ (and EXACT_SYNC) so retrofitted downstream repos can
call it from their opt-in SBOM workflow.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

EXIT_OK = 0      # valid + presence + direct-dependency identity satisfied
EXIT_FAIL = 1    # fail-closed (malformed / schema-drift / below min / missing required dep)
EXIT_USAGE = 2   # usage / IO error, OR --require-components given but empty (no silent degrade)

# bomFormat is a JSON-schema ``const`` in CycloneDX: exactly "CycloneDX". A non-exact value is
# a spec violation, failed CLOSED (lower-casing would admit spec-violating SBOMs).
BOM_FORMAT = "CycloneDX"

# Supported CycloneDX JSON spec versions. Unknown -> fail-closed (schema-drift discipline).
# Includes 1.7 so a native-1.7 generator (e.g. the .NET tool) is not force-downgraded with
# data loss; the fields this gate inspects are stable across 1.2-1.7.
SUPPORTED_CYCLONEDX_VERSIONS = frozenset({"1.2", "1.3", "1.4", "1.5", "1.6", "1.7"})

# Component ``type`` enum is VERSION-DEPENDENT. A single union would fail-open (an older-spec
# BOM with a newer-only type would pass), so each component's type is checked against the set
# defined by that BOM's specVersion.
_BASE8 = frozenset({
    "application", "framework", "library", "container",
    "operating-system", "device", "firmware", "file",
})
_V15 = _BASE8 | {"platform", "device-driver", "machine-learning-model", "data"}
_V16 = _V15 | {"cryptographic-asset"}
TYPES_BY_VERSION: Dict[str, FrozenSet[str]] = {
    "1.2": _BASE8, "1.3": _BASE8, "1.4": _BASE8,
    "1.5": _V15, "1.6": _V16, "1.7": _V16,
}

NORMALIZATIONS = ("exact", "pep503")
_PEP503_RUN = re.compile(r"[-_.]+")

# Unmissable standing advisory, printed on EVERY run (incl. pass) and into --summary-file.
COMPLETENESS_ADVISORY = (
    "[ADVISORY] sbom_gate verifies well-formedness + presence + DIRECT-dependency identity, "
    "NOT exhaustive transitive completeness vs the true dependency graph. A well-formed SBOM "
    "missing transitive components will still PASS — ensure the generation recipe is correct "
    "for your ecosystem (Python resolved-env, Rust all-members, Node pnpm->cdxgen) or "
    "transitive-dependency vulnerabilities may be missed."
)


def normalize_name(name: str, mode: str) -> str:
    """Normalize a component / required-dependency name for identity comparison."""
    if mode == "pep503":  # PyPI: lower-case, runs of - _ . collapse to a single -
        return _PEP503_RUN.sub("-", name).lower()
    return name  # exact: preserve punctuation / scope / case (npm, Cargo, NuGet)


def parse_required(raw: Optional[str], mode: str) -> Tuple[Optional[FrozenSet[str]], Optional[str]]:
    """Parse --require-components. Returns (normalized_set, error).

    None (flag absent) -> empty set (identity check skipped). A flag given but yielding no
    names (empty / comma-only) -> error, so a manifest parser-failure cannot silently degrade
    the job back to a count-only check.
    """
    if raw is None:
        return frozenset(), None
    names = [token.strip() for token in raw.split(",")]
    names = [name for name in names if name]
    if not names:
        return None, "--require-components was given but contains no names (refusing to degrade to count-only)"
    return frozenset(normalize_name(name, mode) for name in names), None


def evaluate(
    payload: object,
    *,
    min_components: int,
    required: FrozenSet[str],
    normalization: str,
) -> Tuple[int, str]:
    """Validate a parsed CycloneDX document. Returns ``(exit_code, message)``; fail-closed."""
    if not isinstance(payload, dict):
        return EXIT_FAIL, "unexpected SBOM: top-level is not an object"
    bom_format = payload.get("bomFormat")
    if bom_format != BOM_FORMAT:  # exact const; rejects missing / wrong-case / non-string
        return EXIT_FAIL, f"unexpected bomFormat {bom_format!r} (must be exactly {BOM_FORMAT!r})"
    spec = payload.get("specVersion")
    if type(spec) is not str or spec not in SUPPORTED_CYCLONEDX_VERSIONS:
        return EXIT_FAIL, f"unsupported CycloneDX specVersion {spec!r} — verify schema then update sbom_gate"
    version = payload.get("version")  # BOM revision; optional, but strict if present
    if version is not None and (type(version) is not int or version < 1):
        return EXIT_FAIL, f"unexpected BOM version {version!r} (must be an int >= 1)"
    components = payload.get("components", [])
    if components is None:  # an absent / null components array means zero components
        components = []
    if not isinstance(components, list):
        return EXIT_FAIL, "unexpected SBOM: 'components' is not a list"

    allowed_types = TYPES_BY_VERSION[spec]
    names: List[str] = []
    for component in components:
        if not isinstance(component, dict):
            return EXIT_FAIL, "unexpected SBOM: a component is not an object"
        name = component.get("name")
        if not isinstance(name, str) or not name:
            return EXIT_FAIL, "unexpected SBOM: a component has no non-empty string name"
        component_type = component.get("type")
        if not isinstance(component_type, str):
            return EXIT_FAIL, "unexpected SBOM: a component 'type' is not a string"
        if component_type not in allowed_types:
            return EXIT_FAIL, f"component type {component_type!r} is not valid for CycloneDX {spec}"
        names.append(name)

    if len(names) < min_components:
        return EXIT_FAIL, f"only {len(names)} component(s) (< --min-components {min_components}) — failing closed"

    if required:
        present = {normalize_name(name, normalization) for name in names}
        missing = sorted(name for name in required if name not in present)
        if missing:
            return EXIT_FAIL, f"required direct dependencies absent from SBOM: {', '.join(missing)}"

    return EXIT_OK, f"valid CycloneDX {spec}; {len(names)} component(s); direct-dependency identity satisfied"


def render_summary_markdown(payload: object) -> str:
    """Markdown summary (+ standing advisory) for $GITHUB_STEP_SUMMARY. Best-effort, no crash."""
    spec = payload.get("specVersion") if isinstance(payload, dict) else None
    components = payload.get("components") if isinstance(payload, dict) else None
    if not isinstance(components, list):
        components = []
    lines = ["", "### SBOM (CycloneDX) — sbom_gate", "", f"specVersion: `{spec}`; components: {len(components)}", ""]
    if components:
        lines.append("| Name | Type |")
        lines.append("|---|---|")
        for component in components[:20]:
            if isinstance(component, dict):
                name = str(component.get("name", "")).replace("|", "\\|")
                component_type = str(component.get("type", "")).replace("|", "\\|")
                lines.append(f"| {name} | {component_type} |")
    lines.append("")
    lines.append(f"> {COMPLETENESS_ADVISORY}")
    return "\n".join(lines) + "\n"


def append_summary(path: str, payload: object) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(render_summary_markdown(payload))


def load_json(text: str) -> Tuple[Optional[object], Optional[str]]:
    """Parse JSON text. Returns (payload, error). Empty/malformed -> error set."""
    if not text.strip():
        return None, "empty output"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"malformed JSON: {exc}"


def read_source(path: str) -> str:
    """Read the SBOM from a file path, or stdin when path is '-'."""
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed CycloneDX SBOM gate.")
    parser.add_argument("--sbom", required=True, help="Path to CycloneDX JSON, or '-' for stdin.")
    parser.add_argument(
        "--min-components",
        type=int,
        default=1,
        help="Fail closed if fewer than N components (default 1; 0 allows an empty SBOM).",
    )
    parser.add_argument(
        "--require-components",
        help="Comma-separated direct-dependency names that MUST be present in the SBOM "
        "(identity check; a manifest-derived list the CI job supplies).",
    )
    parser.add_argument(
        "--name-normalization",
        choices=list(NORMALIZATIONS),
        default="exact",
        help="Name comparison for --require-components: exact (default; npm/Cargo/NuGet) or "
        "pep503 (PyPI: case- and -_.-insensitive).",
    )
    parser.add_argument(
        "--summary-file",
        help="Append a markdown summary (+ standing advisory) to this file (e.g. $GITHUB_STEP_SUMMARY).",
    )
    return parser.parse_args(argv)


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    required, req_error = parse_required(args.require_components, args.name_normalization)
    if req_error is not None:
        print(f"[FAIL] sbom_gate: {req_error}", file=sys.stderr)
        return EXIT_USAGE
    try:
        text = read_source(args.sbom)
    except OSError as exc:
        print(f"[FAIL] cannot read SBOM: {exc}", file=sys.stderr)
        return EXIT_USAGE
    payload, error = load_json(text)
    if error is not None:
        print(f"[FAIL] sbom_gate: {error} — failing closed", file=sys.stderr)
        return EXIT_FAIL
    code, message = evaluate(
        payload,
        min_components=args.min_components,
        required=required,
        normalization=args.name_normalization,
    )
    if args.summary_file:
        try:
            append_summary(args.summary_file, payload)
        except OSError as exc:
            print(f"[FAIL] cannot write summary file: {exc}", file=sys.stderr)
            return EXIT_USAGE
    stream = sys.stderr if code != EXIT_OK else sys.stdout
    print(f"[{'OK' if code == EXIT_OK else 'FAIL'}] sbom_gate: {message}", file=stream)
    print(COMPLETENESS_ADVISORY, file=stream)  # unmissable on every run, incl. pass
    return code


def main() -> int:  # pragma: no cover - thin CLI glue
    return run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
