#!/usr/bin/env python3
"""security_txt_gate.py — fail-closed RFC 9116 (security.txt) gate.

Turns a ``security.txt`` file into a hard pass/fail exit code: it is FAIL-CLOSED (exit 1) on
ANY of —
  - a file that is empty or not valid UTF-8,
  - a non-blank, non-comment line that is not ``Name: value``,
  - a field name not in the RFC 9116 IANA registry (snapshot below) — unknown -> fail-closed,
    mirroring the schema-drift discipline of sca/sast/sbom_gate,
  - a URI-valued field whose value is not a structurally valid URI, or is an ``http://`` web
    URI (RFC 9116 §2.7.2: web URIs MUST use https), or an ``https`` URI with no host, or a
    ``mailto:`` with no address, or a ``tel:`` with no number,
  - a ``Bug-Bounty`` value that is not ``True``/``False`` (it is a boolean, not a URI),
  - ``Expires`` absent, present more than once, not a valid RFC 3339 date-time, without a
    timezone, in the PAST (the file is then stale), or more than ``--max-validity-days`` out,
  - ``Expires``/``Preferred-Languages``/``Bug-Bounty`` appearing more than once (IANA
    "multiple: no"), or ``Contact`` absent (RFC 9116 requires it).

HONESTY BOUNDARY (printed as a standing advisory on every run): this gate validates SYNTAX,
URI structure, required fields, and Expires freshness. It CANNOT verify that the Contact
reaches a monitored, responsible party, that Policy/Canonical URLs resolve or are
non-malicious, or that an OpenPGP signature is valid — those are HUMAN-REVIEW concerns (PR
review of security.txt changes + the disclosure-policy owner). And Expires is only checked as
of *now*, so the gate MUST run on a schedule (cron) to catch the file silently going stale.

Source-only + mirrored into template/ (and EXACT_SYNC). Read-only, pure parsing — no subprocess
and no network (it does NOT fetch Policy/Canonical URLs), matching sca/sast/sbom_gate.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

EXIT_OK = 0
EXIT_FAIL = 1   # fail-closed (malformed / unknown field / bad URI / Expires absent·stale·etc.)
EXIT_USAGE = 2  # usage / IO error

# RFC 9116 IANA "security.txt Fields" registry. Snapshot date recorded so the allowlist's
# provenance is explicit: a newly IANA-registered field requires a deliberate gate update
# (same bump-cadence discipline as the pinned tool versions). Unknown field -> fail-closed.
REGISTRY_SNAPSHOT = "2026-06-08"
SUPPORTED_FIELDS = frozenset({
    "acknowledgments", "bug-bounty", "canonical", "contact", "csaf",
    "encryption", "expires", "hiring", "policy", "preferred-languages",
})
# The URI-valued fields (per the registry). Bug-Bounty is a boolean; Expires is a timestamp;
# Preferred-Languages is a language list — none of those are URIs.
URI_FIELDS = frozenset({"acknowledgments", "canonical", "contact", "csaf", "encryption", "hiring", "policy"})
# Fields the registry marks "multiple: no" (MUST NOT appear more than once).
NO_REPEAT = frozenset({"expires", "preferred-languages", "bug-bounty"})

COMPLETENESS_ADVISORY = (
    "[ADVISORY] security_txt_gate verifies the file is well-formed, has the required fields, "
    "uses valid https/mailto/tel URIs, and has a non-expired Expires. It CANNOT verify that the "
    "Contact reaches a monitored, responsible party, that Policy/Canonical URLs resolve or are "
    "non-malicious, or that any signature is valid — those are HUMAN-REVIEW concerns (PR review "
    "of security.txt changes + the disclosure-policy owner). Expires is only checked as of now, "
    "so this gate MUST run on a schedule (cron) to catch the file silently going stale."
)


def validate_uri(value: str) -> Optional[str]:
    """Structural URI validation per RFC 9116. Returns an error string, or None if valid."""
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if not scheme:
        return f"missing URI scheme: {value!r}"
    if scheme == "http":
        return f"web URIs MUST use https, not http (RFC 9116 §2.7.2): {value!r}"
    if scheme == "https":
        if not parts.netloc:
            return f"https URI has no host: {value!r}"
    elif scheme == "mailto":
        if "@" not in parts.path:
            return f"mailto URI has no address: {value!r}"
    elif scheme == "tel":
        if not parts.path:
            return f"tel URI has no number: {value!r}"
    elif not (parts.netloc or parts.path):  # other schemes (dns:, openpgp4fpr:, ...) need a target
        return f"URI scheme {scheme!r} has no target: {value!r}"
    return None


def parse_expires(value: str) -> Tuple[Optional[datetime], Optional[str]]:
    """Parse an RFC 3339 date-time. Returns (datetime, error)."""
    text = value
    if text.endswith(("Z", "z")):  # RFC 3339 'Z' / the RFC's lowercase 'z' example -> offset
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None, f"Expires is not a valid RFC 3339 date-time: {value!r}"
    if parsed.tzinfo is None:
        return None, f"Expires must include a timezone offset (RFC 3339): {value!r}"
    return parsed, None


def parse_fields(text: str) -> Tuple[Optional[List[Tuple[str, str]]], Optional[str]]:
    """Parse security.txt into (name_lower, value) pairs. Returns (fields, error)."""
    fields: List[Tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            return None, f"malformed line (expected 'Name: value'): {raw_line!r}"
        name, _, value = line.partition(":")
        name = name.strip().lower()
        value = value.strip()
        if not name or not value:
            return None, f"malformed line (empty name or value): {raw_line!r}"
        if name not in SUPPORTED_FIELDS:
            return None, f"unknown field {name!r} (not in RFC 9116 IANA registry, snapshot {REGISTRY_SNAPSHOT})"
        fields.append((name, value))
    return fields, None


def evaluate(text: str, *, now: datetime, max_validity_days: int) -> Tuple[int, str]:
    """Validate a security.txt document. Returns ``(exit_code, message)``; fail-closed."""
    fields, error = parse_fields(text)
    if error is not None:
        return EXIT_FAIL, error

    counts = Counter(name for name, _ in fields)
    for name in NO_REPEAT:
        if counts[name] > 1:
            return EXIT_FAIL, f"field {name!r} MUST NOT appear more than once (RFC 9116)"
    if counts["contact"] < 1:
        return EXIT_FAIL, "Contact field is required (RFC 9116) and is missing"

    for name, value in fields:
        if name in URI_FIELDS:
            uri_error = validate_uri(value)
            if uri_error is not None:
                return EXIT_FAIL, f"{name}: {uri_error}"
        elif name == "bug-bounty" and value.lower() not in ("true", "false"):
            return EXIT_FAIL, f"Bug-Bounty must be True or False, got {value!r}"

    expires_values = [value for name, value in fields if name == "expires"]
    if len(expires_values) != 1:
        return EXIT_FAIL, "Expires field is required exactly once (RFC 9116)"
    expires, error = parse_expires(expires_values[0])
    if error is not None:
        return EXIT_FAIL, error
    if expires <= now:
        return EXIT_FAIL, f"Expires is in the past ({expires.isoformat()}) — security.txt is stale"
    days_out = (expires - now).days
    if days_out > max_validity_days:
        return EXIT_FAIL, f"Expires is {days_out} days out (> --max-validity-days {max_validity_days}) — RFC 9116 RECOMMENDS < 1 year"

    return EXIT_OK, f"valid security.txt; {len(fields)} field(s); Expires {expires.isoformat()} ({days_out}d out)"


def read_source(path: str) -> str:
    """Read security.txt from a file path, or stdin when path is '-'."""
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed RFC 9116 security.txt gate.")
    parser.add_argument("--file", required=True, help="Path to security.txt, or '-' for stdin.")
    parser.add_argument(
        "--max-validity-days",
        type=int,
        default=365,
        help="Fail closed if Expires is more than N days out (RFC 9116 RECOMMENDS < 1 year; default 365).",
    )
    return parser.parse_args(argv)


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        text = read_source(args.file)
    except OSError as exc:
        print(f"[FAIL] cannot read security.txt: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except UnicodeDecodeError:
        print("[FAIL] security_txt_gate: file is not valid UTF-8 — failing closed", file=sys.stderr)
        return EXIT_FAIL
    if not text.strip():
        print("[FAIL] security_txt_gate: empty security.txt — failing closed", file=sys.stderr)
        return EXIT_FAIL
    code, message = evaluate(text, now=datetime.now(timezone.utc), max_validity_days=args.max_validity_days)
    stream = sys.stderr if code != EXIT_OK else sys.stdout
    print(f"[{'OK' if code == EXIT_OK else 'FAIL'}] security_txt_gate: {message}", file=stream)
    print(COMPLETENESS_ADVISORY, file=stream)  # standing advisory on every run
    return code


def main() -> int:  # pragma: no cover - thin CLI glue
    return run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
