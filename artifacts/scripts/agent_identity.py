"""Canonical agent identity registry for RACI Auditor v2 (TASK-1007)."""
from __future__ import annotations

CANONICAL_IDENTITIES: frozenset[str] = frozenset({
    "Claude Code",
    "Gemini CLI",
    "Codex CLI",
    "Implementer",
    "Tester",
    "Verifier",
    "Reviewer",
})

# Migration-debt aliases — not canonical proof.
# Resolved only when compatibility_mode=True; rejected in root strict mode.
ALIAS_MAP: dict[str, str] = {
    "Claude": "Claude Code",
    "Gemini": "Gemini CLI",
    "Codex": "Codex CLI",
}


class AliasRejectedError(ValueError):
    """Raised when an alias is used in strict mode without compatibility_mode."""

    def __init__(self, alias: str, canonical: str) -> None:
        super().__init__(
            f"Alias '{alias}' is migration debt, not canonical. "
            f"Use '{canonical}'. "
            f"Strict mode rejects alias resolution without --compatibility-mode."
        )
        self.alias = alias
        self.canonical = canonical


class UnknownIdentityError(ValueError):
    """Raised when agent_str is neither a canonical identity nor a known alias."""

    def __init__(self, agent_str: str) -> None:
        super().__init__(
            f"Unknown agent identity '{agent_str}'. "
            f"Canonical identities: {sorted(CANONICAL_IDENTITIES)}. "
            f"Known aliases (migration debt): {sorted(ALIAS_MAP)}."
        )
        self.agent_str = agent_str


def resolve_identity(
    agent_str: str,
    *,
    compatibility_mode: bool = False,
    strict: bool = True,
) -> tuple[str, bool]:
    """
    Resolve agent_str to a canonical identity string.

    Returns (canonical_identity, was_aliased).

    Raises AliasRejectedError if an alias is used in strict mode without
    compatibility_mode (root strict mode: aliases are migration debt).
    Raises UnknownIdentityError if agent_str is neither canonical nor a known alias.
    """
    if agent_str in CANONICAL_IDENTITIES:
        return agent_str, False

    if agent_str in ALIAS_MAP:
        canonical = ALIAS_MAP[agent_str]
        if strict and not compatibility_mode:
            raise AliasRejectedError(agent_str, canonical)
        import warnings
        warnings.warn(
            f"Alias '{agent_str}' resolved to '{canonical}' (migration debt). "
            "Update callers to use the canonical name.",
            stacklevel=2,
        )
        return canonical, True

    raise UnknownIdentityError(agent_str)
