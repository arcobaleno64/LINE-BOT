---
description: Run a Codex Council-of-models review on the current diff and produce a triaged summary
argument-hint: "[--diff-source staged|unstaged|all|HEAD] [--dry-run]"
allowed-tools: Bash, Read, Write
---

# /codex-review — Codex Council-of-Models Review

This slash command runs a three-tier Codex review of the current git diff and produces
a triaged summary. It is the council-forge complement to `/review` (single-model Claude
review) and `/security-review` (security-focused single-model review): three independent
Codex model tiers vote, and Claude (you) merges their findings into one ranked list.

## When to use

- Before opening a PR, when you want more than one pair of eyes
- After a non-trivial refactor that may have hidden side-effects
- When the diff crosses module boundaries and a single reviewer's blind spots concern you

## When NOT to use

- For style-only diffs — reach for `/review` instead
- For security-only diffs — `/security-review` is the right entry point
- For very large diffs (≥ ~6000 chars cumulative) — see Limitations below; prefer
  reviewing commit-by-commit with `--diff-source HEAD`

## Council members

Three Codex model tiers act as independent reviewers. Each receives the same diff and
emits its own findings; Claude reconciles them.

| Member | Model        | Reasoning effort | Strength                                  |
|--------|--------------|------------------|-------------------------------------------|
| Junior | gpt-5.4-mini | high             | Fast, surface-level issues, naming        |
| Senior | gpt-5.4      | high             | Standard correctness, side-effect tracing |
| Architect | gpt-5.5  | high             | Cross-module reasoning, contract drift    |

This three-tier ladder mirrors the council-forge Codex routing in
`feedback_codex_model_tier_v2` (see auto-memory) and the `Council of Three` philosophy
in `.github/skills/quality-playbook/SKILL.md` File 5.

## Protocol

### Step 1: Parse args

Parse the user's command line for two optional flags:

- `--diff-source <staged|unstaged|all|HEAD>` — defaults to `all`
- `--dry-run` — defaults to false

If the user passed neither, ask which `--diff-source` they want before invoking the
orchestrator. Default to `all` only if they explicitly confirm.

### Step 2: Invoke the orchestrator

Run, via the Bash tool:

```
pwsh -File artifacts/scripts/Invoke-CodexReview.ps1 -DiffSource <X> [-DryRun]
```

The orchestrator dispatches three Codex calls (one per Council member) and writes each
member's response to `artifacts/reviews/<timestamp>-<model>.md` with a frontmatter that
records `model`, `effort`, `diff_source`, `commit_anchor`, `generated_at`, `exit_code`.

If `-DryRun` was passed, the orchestrator prints the dispatch arguments only — no Codex
call is made and no review files are written. In that case, stop after Step 2 and
report the dry-run output.

### Step 3: Read the three review files

After the orchestrator exits 0, read all three `artifacts/reviews/<timestamp>-*.md`
files using the Read tool.

If any file's `exit_code` frontmatter is non-zero, surface that to the user and skip
that member during triage; note in the final report that the Council was incomplete.

### Step 4: Triage findings

For each finding across the three reviews, classify by inter-member agreement:

- **Agreement** — all three Council members raised the same finding. Promote to at
  least `high` severity even if individual members rated it lower.
- **Majority** — exactly two of three members raised it. Keep the highest individual
  severity; mark `agreement: 2/3`.
- **Dissent** — only one member raised it. Mark `agreement: 1/3` and name the source
  member; do not auto-promote severity.

Two findings count as "the same" when they reference the same file:line (or the same
section) AND describe the same root cause. Do not merge findings that happen to share
a severity tag but point at unrelated locations.

### Step 5: Output

Emit a single triaged report to the user as a markdown table:

```
| Severity | Agreement | Source models    | Location          | Issue          | Suggested fix |
|----------|-----------|------------------|-------------------|----------------|---------------|
| high     | 3/3       | mini, 5.4, 5.5   | foo.ps1:42        | unbound var    | declare $X    |
| medium   | 2/3       | 5.4, 5.5         | docs/x.md §2      | drift vs spec  | re-anchor     |
| low      | 1/3       | mini             | bar.py:17         | unused import  | remove        |
```

Sort by severity (critical → info), then by agreement (3/3 first), then by location.

### Step 6: Recommend next steps

After the table, list 2-4 concrete next actions tied to the highest-severity findings.
Examples:

- "Address the 3/3 high finding at foo.ps1:42 before commit"
- "Open an ADR for the 2/3 medium contract-drift finding in docs/x.md"
- "Dismiss the 1/3 low dissent on bar.py:17 unless others escalate"

Do not auto-apply fixes. The user decides which findings to act on.

## Limitations

- Single-vendor: All three Council members are Codex tiers. This is a tiered-reasoning
  Council, not a multi-vendor one. For genuine cross-vendor audits, see
  `.github/skills/quality-playbook/SKILL.md` File 5.
- cmd 8191 char limit: Underlying `Invoke-CodexAgent.ps1` passes the prompt as a
  positional arg; very large diffs (~ ≥ 6000 chars) may truncate or fail silently. This
  is a known wrapper bug tracked in TASK-1053. Workaround: pass `--diff-source HEAD` to
  review one commit at a time, or split the diff manually.
- No e2e dispatch in this batch: TASK-1052 itself ships only the orchestrator + this
  protocol; the first real Council run happens after TASK-1053 lands the prompt-size
  fix.
- No automatic fix application: Triage produces a ranked report; applying fixes is the
  user's call.

## Triggers

This skill is appropriate when the user says any of:

- "run a codex review"
- "codex council"
- "multi-model review"
- "/codex-review"
- "review my diff with codex"

## Output format contract

Every successful invocation must end with the markdown triage table and the recommended
next-steps list. Never end with raw Codex output without triage.
