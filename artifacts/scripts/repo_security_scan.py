#!/usr/bin/env python3
"""Repo-local secrets and focused static risk scanner."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

MAX_FILE_BYTES = 1_000_000

TEXT_SUFFIXES = {
    ".cfg",
    ".cmd",
    ".env",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".txt",
    ".toml",
    ".yaml",
    ".yml",
}

STATIC_TARGETS = {
    ".github/workflows/": {".yml": "workflow", ".yaml": "workflow"},
    "template/.github/workflows/": {".yml": "workflow", ".yaml": "workflow"},
    "artifacts/scripts/": {".py": "python", ".ps1": "powershell"},
    "template/artifacts/scripts/": {".py": "python", ".ps1": "powershell"},
}

EXCLUDED_PREFIXES = (
    ".claude/",
    ".git/",
    ".venv/",
    "__pycache__/",
    "coverage-report/",
    "external/",
)

PLACEHOLDER_MARKERS = (
    "abc123",
    "changeme",
    "dummy",
    "example",
    "fake",
    "placeholder",
    "redacted",
    "replace-me",
    "sample",
    "test",
    "xxxxx",
    "xxxx",
    "zzz",
)

GENERIC_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|token|secret|password|passwd|client[_-]?secret|access[_-]?token)\b"
    r"\s*[:=]\s*[\"'](?P<secret>[^\"'\n]{16,})[\"']"
)

STRUCTURED_SECRET_PATTERNS = (
    ("github-pat-classic", "high", re.compile(r"\bgh[pousr]_(?P<secret>[A-Za-z0-9]{20,})\b"), "Possible GitHub personal access token"),
    ("github-pat-fine-grained", "high", re.compile(r"\bgithub_pat_(?P<secret>[A-Za-z0-9_]{20,})\b"), "Possible GitHub fine-grained personal access token"),
    ("aws-access-key-id", "high", re.compile(r"\bAKIA(?P<secret>[0-9A-Z]{16})\b"), "Possible AWS access key ID"),
    ("openai-style-key", "high", re.compile(r"\bsk-(?P<secret>[A-Za-z0-9]{20,})\b"), "Possible OpenAI-style API key"),
    ("private-key-block", "critical", re.compile(r"-----BEGIN (?:(?:RSA|EC|OPENSSH|DSA) )?PRIVATE KEY-----"), "Private key block detected"),
)


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    path: str
    line: int
    message: str
    excerpt: str


@dataclass(frozen=True)
class StaticRule:
    rule_id: str
    severity: str
    targets: tuple[str, ...]
    pattern: re.Pattern[str]
    message: str


STATIC_RULES = (
    StaticRule(
        "workflow-unpinned-action",
        "high",
        ("workflow",),
        re.compile(r"^\s*-?\s*uses:\s*[^@\s]+/[^@\s]+@(?!(?:[0-9a-f]{40})(?:\s|$|#)).+", re.IGNORECASE),
        "GitHub Actions references should use a full 40-character commit SHA",
    ),
    StaticRule(
        "workflow-persist-credentials-true",
        "high",
        ("workflow",),
        re.compile(r"^\s*persist-credentials:\s*true\s*(?:#.*)?$", re.IGNORECASE),
        "workflow checkout should not persist credentials by default",
    ),
    StaticRule(
        "workflow-pull-request-target",
        "high",
        ("workflow",),
        re.compile(r"^\s*pull_request_target\s*:", re.IGNORECASE),
        "pull_request_target expands trust and should be avoided unless explicitly justified",
    ),
    StaticRule(
        "workflow-write-all-permissions",
        "high",
        ("workflow",),
        re.compile(r"^\s*permissions:\s*write-all\s*(?:#.*)?$", re.IGNORECASE),
        "write-all permissions are broader than least privilege",
    ),
    StaticRule(
        "workflow-secret-echo",
        "high",
        ("workflow",),
        re.compile(r"echo\s+\$\{\{\s*secrets\.", re.IGNORECASE),
        "workflow step appears to echo a secret into logs",
    ),
    StaticRule(
        "python-shell-true",
        "high",
        ("python",),
        re.compile(r"shell\s*=\s*True"),
        "subprocess shell execution increases command injection risk",
    ),
    StaticRule(
        "python-dynamic-exec",
        "high",
        ("python",),
        re.compile(r"\b(?:exec|eval)\s*\("),
        "dynamic exec/eval should not be introduced into workflow control-plane scripts",
    ),
    StaticRule(
        "python-verify-false",
        "high",
        ("python",),
        re.compile(r"\bverify\s*=\s*False\b"),
        "HTTP requests should not disable TLS verification",
    ),
    StaticRule(
        "powershell-invoke-expression",
        "high",
        ("powershell",),
        re.compile(r"\b(?:Invoke-Expression|iex)\b", re.IGNORECASE),
        "Invoke-Expression executes dynamic PowerShell text and should be avoided",
    ),
    StaticRule(
        "powershell-secret-output",
        "high",
        ("powershell",),
        re.compile(r"\b(?:Write-Host|Write-Output)\b.*\$(?:env:)?(?:GITHUB_TOKEN|GH_TOKEN)", re.IGNORECASE),
        "PowerShell script appears to print a GitHub credential",
    ),
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repo-local security scanner")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--json", action="store_true", help="Output JSON")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("secrets", help="Scan for high-confidence secrets")
    subparsers.add_parser("static", help="Scan for focused static control-plane risks")
    return parser.parse_args(argv)


def normalize_rel_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def should_exclude_path(rel_path: str) -> bool:
    if any(rel_path.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return True
    if rel_path.startswith(".github/skills/") or rel_path.startswith("template/.github/skills/"):
        return True
    if any(part.startswith("threat-model-") for part in rel_path.split("/")):
        return True
    return False


def is_text_candidate(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Dockerfile", ".env"}


def read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if len(raw) > MAX_FILE_BYTES or b"\x00" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace")


def iter_repo_files(root: Path) -> Iterator[tuple[str, Path]]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not is_text_candidate(path):
            continue
        rel_path = normalize_rel_path(path, root)
        if should_exclude_path(rel_path):
            continue
        yield rel_path, path


def iter_lines(text: str) -> Iterator[tuple[int, str]]:
    for line_number, line in enumerate(text.splitlines(), start=1):
        yield line_number, line


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    entropy = 0.0
    length = len(value)
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def is_placeholder_secret(value: str) -> bool:
    lowered = value.lower()
    if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
        return True
    if lowered.endswith("example"):
        return True
    if re.fullmatch(r"[xX*_-]{8,}", value):
        return True
    if len(set(value)) <= 4 and len(value) >= 12:
        return True
    return False


def generic_secret_is_actionable(secret_value: str) -> bool:
    return not is_placeholder_secret(secret_value) and shannon_entropy(secret_value) >= 3.0


def build_finding(rule_id: str, severity: str, rel_path: str, line_number: int, message: str, excerpt: str) -> Finding:
    return Finding(rule_id=rule_id, severity=severity, path=rel_path, line=line_number, message=message, excerpt=excerpt.strip())


def scan_secrets(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for rel_path, path in iter_repo_files(root):
        text = read_text(path)
        if text is None:
            continue

        for rule_id, severity, pattern, message in STRUCTURED_SECRET_PATTERNS:
            for match in pattern.finditer(text):
                secret_value = match.groupdict().get("secret", match.group(0))
                if rule_id == "aws-access-key-id" and match.group(0).endswith("EXAMPLE"):
                    continue
                if rule_id != "private-key-block" and is_placeholder_secret(secret_value):
                    continue
                line_number = text.count("\n", 0, match.start()) + 1
                excerpt = text.splitlines()[line_number - 1] if text.splitlines() else match.group(0)
                findings.append(build_finding(rule_id, severity, rel_path, line_number, message, excerpt))

        if path.suffix.lower() not in {".cmd", ".env", ".ini", ".json", ".ps1", ".py", ".sh", ".toml", ".yaml", ".yml"}:
            continue
        for line_number, line in iter_lines(text):
            for match in GENERIC_SECRET_ASSIGNMENT.finditer(line):
                secret_value = match.group("secret")
                if not generic_secret_is_actionable(secret_value):
                    continue
                findings.append(
                    build_finding(
                        "generic-secret-assignment",
                        "medium",
                        rel_path,
                        line_number,
                        "Possible hard-coded secret assignment",
                        line,
                    )
                )
    return dedupe_findings(findings)


def detect_static_target(rel_path: str) -> str | None:
    for prefix, suffix_map in STATIC_TARGETS.items():
        if rel_path.startswith(prefix):
            return suffix_map.get(Path(rel_path).suffix.lower())
    return None


def scan_static(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for rel_path, path in iter_repo_files(root):
        target = detect_static_target(rel_path)
        if target is None:
            continue
        text = read_text(path)
        if text is None:
            continue
        for line_number, line in iter_lines(text):
            for rule in STATIC_RULES:
                if target not in rule.targets:
                    continue
                if rule.pattern.search(line):
                    findings.append(build_finding(rule.rule_id, rule.severity, rel_path, line_number, rule.message, line))
    return dedupe_findings(findings)


def dedupe_findings(findings: Iterable[Finding]) -> list[Finding]:
    seen: set[tuple[str, str, int]] = set()
    ordered: list[Finding] = []
    for finding in findings:
        key = (finding.rule_id, finding.path, finding.line)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(finding)
    return sorted(ordered, key=lambda item: (item.path, item.line, item.rule_id))


def render_findings(findings: Sequence[Finding], as_json: bool) -> str:
    if as_json:
        return json.dumps([asdict(finding) for finding in findings], ensure_ascii=False, indent=2)
    if not findings:
        return "[OK] No findings detected"
    lines = [f"[FAIL] Detected {len(findings)} finding(s):"]
    for finding in findings:
        lines.append(
            f"- [{finding.severity.upper()}] {finding.rule_id} {finding.path}:{finding.line} — {finding.message}"
        )
        lines.append(f"  {finding.excerpt}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "secrets":
        findings = scan_secrets(root)
    else:
        findings = scan_static(root)
    print(render_findings(findings, args.json))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())