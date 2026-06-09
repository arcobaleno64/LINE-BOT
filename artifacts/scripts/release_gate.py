#!/usr/bin/env python3
"""release_gate.py — fail-closed release-integrity (checksums manifest) structural gate.

Turns a release-integrity checksums manifest (e.g. council-forge's own propagated-snapshot
manifest, or any downstream that emits the same schema) into a hard pass/fail exit code.
Read-only, pure parsing — it does NOT execute any generator and does NOT cryptographically
verify anything (no subprocess, no network), matching sca/sast/sbom/security_txt_gate.

FAIL-CLOSED (exit 1) on ANY of —
  - JSON that is malformed / empty,
  - a ``schema`` that is absent / non-string / not a supported value (schema-drift discipline,
    mirroring sbom_gate's specVersion and sca_gate's int-version checks),
  - an ``algorithm`` that is absent / non-string / not in the allowlist (sha256 / sha512),
  - an ``entries`` shape that is not a list, an entry that is not an object, an entry with no
    non-empty string ``path``, or a DUPLICATE entry path (coverage must be unambiguous),
  - any entry/``root`` digest that is not lowercase hex of the algorithm's exact length, or is
    an obvious placeholder/sentinel (all-same-nibble / TODO / CHANGEME / REPLACE / xxxx),
  - fewer than ``--min-entries`` entries (default 1, so an empty manifest fails closed),
  - a ``--require-paths`` path that is absent from the manifest (identity, not just a count).

HONESTY BOUNDARY (printed as a standing advisory on every run): this gate validates the
manifest/attestation STRUCTURE (schema, algorithm, digest shape, no placeholders, path
coverage). It does NOT cryptographically verify signatures, certificate trust, key/signer
identity, transparency-log inclusion, or that the digests match the real artifact bytes. Real
cryptographic verification (cosign / gh attestation verify / dotnet nuget verify / minisign -V)
and key-trust remain a separate, native-tool, human-reviewed step and an explicitly accepted
residual risk. in-toto/Sigstore/Tauri structural+crypto validation is delegated to those native
tools (map-don't-recreate), not re-implemented here.

Source-only + mirrored into template/ (and EXACT_SYNC).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

EXIT_OK = 0      # valid structure + presence + path identity satisfied
EXIT_FAIL = 1    # fail-closed (malformed / schema-drift / bad digest / placeholder / below min / missing path)
EXIT_USAGE = 2   # usage / IO error, OR --require-paths given but empty (no silent degrade)

# Allowed digest algorithms -> exact lowercase-hex length. Unknown -> fail-closed.
ALGO_ALLOWLIST: Dict[str, int] = {"sha256": 64, "sha512": 128}

# Supported manifest schema ``const`` values. Unknown -> fail-closed (schema-drift discipline);
# add a value only after the new schema is verified and the parser updated.
SUPPORTED_SCHEMA_VERSIONS = frozenset({"council-forge/release-manifest@1"})

_HEX_RE = re.compile(r"[0-9a-f]+")
# Obvious placeholders that must never read as a real digest, even if hex-shaped.
_SENTINELS = ("todo", "changeme", "replace", "xxxx")

# Unmissable standing advisory, printed on EVERY run (incl. pass) and into --summary-file.
COMPLETENESS_ADVISORY = (
    "[ADVISORY] release_gate validates the checksums-manifest STRUCTURE (schema, algorithm, "
    "digest shape, no placeholders, path coverage) — it does NOT cryptographically verify "
    "signatures, certificate trust, key/signer identity, transparency-log inclusion, or that "
    "the digests match the real artifact bytes. Real cryptographic verification (cosign / "
    "gh attestation verify / dotnet nuget verify / minisign -V) and key-trust remain a "
    "separate, native-tool, human-reviewed step and an explicitly accepted residual risk."
)


def is_str(value: object) -> bool:
    """True only for an actual str (not a bool/int/None) — type before membership."""
    return type(value) is str


def reject_placeholder(value: str) -> bool:
    """True if value is an obvious placeholder/sentinel rather than a real digest."""
    if not value:
        return True
    lowered = value.lower()
    if any(token in lowered for token in _SENTINELS):
        return True
    if len(set(value)) == 1:  # all-zero / all-f / any single repeated nibble
        return True
    return False


def validate_digest(algorithm: str, value: object) -> Optional[str]:
    """Validate a digest hex for ``algorithm``. Returns an error string, or None if valid."""
    if not is_str(value):
        return f"digest is not a string: {value!r}"
    expected_len = ALGO_ALLOWLIST[algorithm]
    if len(value) != expected_len:
        return f"{algorithm} digest must be {expected_len} lowercase-hex chars, got {len(value)}"
    if not _HEX_RE.fullmatch(value):
        return f"digest is not lowercase hex: {value!r}"
    if reject_placeholder(value):
        return f"digest is a placeholder/sentinel: {value!r}"
    return None


def parse_require_paths(raw: Optional[str]) -> Tuple[Optional[FrozenSet[str]], Optional[str]]:
    """Parse --require-paths. Returns (set, error).

    None (flag absent) -> empty set (identity check skipped). A flag given but yielding no
    paths -> error, so a caller's empty variable cannot silently degrade to no identity check.
    """
    if raw is None:
        return frozenset(), None
    paths = [token.strip() for token in raw.split(",")]
    paths = [path for path in paths if path]
    if not paths:
        return None, "--require-paths was given but contains no paths (refusing to degrade)"
    return frozenset(paths), None


def evaluate_checksums(
    payload: object,
    *,
    require_paths: FrozenSet[str],
    min_entries: int,
) -> Tuple[int, str]:
    """Validate a parsed checksums manifest. Returns ``(exit_code, message)``; fail-closed."""
    if not isinstance(payload, dict):
        return EXIT_FAIL, "unexpected manifest: top-level is not an object"
    schema = payload.get("schema")
    if type(schema) is not str or schema not in SUPPORTED_SCHEMA_VERSIONS:
        return EXIT_FAIL, f"unsupported manifest schema {schema!r} — verify then update release_gate"
    algorithm = payload.get("algorithm")
    if type(algorithm) is not str or algorithm not in ALGO_ALLOWLIST:
        return EXIT_FAIL, f"unsupported algorithm {algorithm!r} (allowed: {', '.join(sorted(ALGO_ALLOWLIST))})"
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return EXIT_FAIL, "unexpected manifest: 'entries' is not a list"

    paths: List[str] = []
    seen: set = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return EXIT_FAIL, "unexpected manifest: an entry is not an object"
        path = entry.get("path")
        if not is_str(path) or not path:
            return EXIT_FAIL, "unexpected manifest: an entry has no non-empty string path"
        if path in seen:
            return EXIT_FAIL, f"duplicate entry path: {path!r}"
        seen.add(path)
        digest_error = validate_digest(algorithm, entry.get(algorithm))
        if digest_error is not None:
            return EXIT_FAIL, f"entry {path!r}: {digest_error}"
        paths.append(path)

    if len(paths) < min_entries:
        return EXIT_FAIL, f"only {len(paths)} entr(y/ies) (< --min-entries {min_entries}) — failing closed"

    root_error = validate_digest(algorithm, payload.get("root"))
    if root_error is not None:
        return EXIT_FAIL, f"root: {root_error}"

    if require_paths:
        present = set(paths)
        missing = sorted(path for path in require_paths if path not in present)
        if missing:
            return EXIT_FAIL, f"required paths absent from manifest: {', '.join(missing)}"

    return EXIT_OK, f"valid release manifest ({schema}); {len(paths)} entr(y/ies); {algorithm}; root {payload['root'][:12]}"


def render_summary_markdown(payload: object) -> str:
    """Markdown summary (+ standing advisory) for $GITHUB_STEP_SUMMARY. Best-effort, no crash."""
    schema = payload.get("schema") if isinstance(payload, dict) else None
    algorithm = payload.get("algorithm") if isinstance(payload, dict) else None
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        entries = []
    lines = [
        "",
        "### Release integrity (checksums) — release_gate",
        "",
        f"schema: `{schema}`; algorithm: `{algorithm}`; entries: {len(entries)}",
        "",
        f"> {COMPLETENESS_ADVISORY}",
    ]
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
    """Read the manifest from a file path, or stdin when path is '-'."""
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed release-integrity (checksums manifest) gate.")
    parser.add_argument("--format", required=True, choices=["checksums"], help="Manifest format to validate.")
    parser.add_argument("--file", required=True, help="Path to the manifest JSON, or '-' for stdin.")
    parser.add_argument(
        "--require-paths",
        help="Comma-separated paths that MUST be present in the manifest (identity check).",
    )
    parser.add_argument(
        "--min-entries",
        type=int,
        default=1,
        help="Fail closed if fewer than N entries (default 1; an empty manifest fails closed).",
    )
    parser.add_argument(
        "--summary-file",
        help="Append a markdown summary (+ standing advisory) to this file (e.g. $GITHUB_STEP_SUMMARY).",
    )
    return parser.parse_args(argv)


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    required, req_error = parse_require_paths(args.require_paths)
    if req_error is not None:
        print(f"[FAIL] release_gate: {req_error}", file=sys.stderr)
        return EXIT_USAGE
    try:
        text = read_source(args.file)
    except OSError as exc:
        print(f"[FAIL] cannot read manifest: {exc}", file=sys.stderr)
        return EXIT_USAGE
    payload, error = load_json(text)
    if error is not None:
        print(f"[FAIL] release_gate: {error} — failing closed", file=sys.stderr)
        return EXIT_FAIL
    code, message = evaluate_checksums(payload, require_paths=required, min_entries=args.min_entries)
    if args.summary_file:
        try:
            append_summary(args.summary_file, payload)
        except OSError as exc:
            print(f"[FAIL] cannot write summary file: {exc}", file=sys.stderr)
            return EXIT_USAGE
    stream = sys.stderr if code != EXIT_OK else sys.stdout
    print(f"[{'OK' if code == EXIT_OK else 'FAIL'}] release_gate: {message}", file=stream)
    print(COMPLETENESS_ADVISORY, file=stream)  # unmissable on every run, incl. pass
    return code


def main() -> int:  # pragma: no cover - thin CLI glue
    return run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
