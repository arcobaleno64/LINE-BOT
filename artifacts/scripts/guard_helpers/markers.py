#!/usr/bin/env python3
from __future__ import annotations

import re
from typing import List, Sequence

CITATION_PATTERN = re.compile(
    r"(?:"
    r"https?://\S+"
    r"|`gh api [^`]+`"
    r"|`[^`\n]+\.(?:md|json|txt|py|ps1|csproj|ini|toml|yml|yaml|cfg|sh)[^`\n]*`"
    r"|[（(](?:[Ss]ource:\s*)?[^)）\n]*?[A-Za-z0-9_./\\-]+\.(?:md|json|txt|py|ps1|csproj|ini|toml|yml|yaml|cfg|sh)(?::\d+)?[^)）\n]*[)）]"
    r"|\b[A-Za-z0-9_./\\-]+\.(?:md|json|txt|py|ps1|csproj|ini|toml|yml|yaml|cfg|sh)(?::\d+)?\b"
    r")",
    re.IGNORECASE,
)

__all__ = [
    "CITATION_PATTERN",
    "_marker_present",
    "_is_v2_plan",
    "_required_markers_missing",
]

def _marker_present(text: str, marker: str) -> bool:
    """Test whether a required marker is present in `text`.

    Heading markers (starting with '#') are matched line-anchored to avoid
    false positives like '## Decision' matching '## Decision Class'. Markers
    ending in ':' allow trailing content on the same line; pure headings
    must stand alone (allowing trailing whitespace only). Non-heading markers
    (e.g. 'Task ID:', 'Artifact Type: task') keep the simple substring
    semantics used by the v1 validator.

    See docs/artifact_schema.md §5.13 for the v2 governance extension.
    """
    if marker.startswith("#"):
        if marker.endswith(":"):
            pattern = rf"^{re.escape(marker)}(\s|$)"
        else:
            pattern = rf"^{re.escape(marker)}\s*$"
        return re.search(pattern, text, re.MULTILINE) is not None
    return marker in text


def _is_v2_plan(text: str) -> bool:
    """Detect v2 governance plan format.

    v2 plans use '## Goal' / '## Approach' / '## Authorization Boundary' /
    '## Premortem' / '## Build Guarantee' / '## TAO Trace' instead of v1's
    '## Scope' / '## Proposed Changes' / '## Out of Scope' /
    '## Validation Strategy' / '## Ready For Coding'. Detection succeeds when
    any v2-only section is present, or when the v2 risk pattern (## Premortem
    without ## Validation Strategy) appears.

    See docs/artifact_schema.md §5.13 for the v2 governance extension.
    """
    if "## Authorization Boundary" in text:
        return True
    if "## TAO Trace" in text:
        return True
    return "## Premortem" in text and "## Validation Strategy" not in text


def _required_markers_missing(text: str, required: Sequence) -> List[str]:
    """Compute the list of missing markers for an artifact body.

    Each entry of `required` is either a string (single required marker) or a
    tuple of strings (any-of alternatives). For tuples, the marker is satisfied
    if at least one alternative is present. Returns human-readable labels for
    missing markers; tuple alternatives are rendered as 'A / B / C'.
    """
    missing: List[str] = []
    for marker in required:
        if isinstance(marker, tuple):
            if not any(_marker_present(text, alt) for alt in marker):
                missing.append(" / ".join(marker))
        else:
            if not _marker_present(text, marker):
                missing.append(marker)
    return missing
