# Red Team Scorecard (Semi-Auto)

此檔由 `artifacts/scripts/aggregate_red_team_scorecard.py` 依 red-team report 自動產生。

## Metadata
- Source Report: `C:/Users/Arcobaleno/Documents/Code/consilium-fabri/artifacts/red_team/latest_report.md`
- Generated At: 2026-04-19T19:20:48+08:00
- Timezone: Asia/Taipei (+08:00)

## Aggregated Cases

| Case | Phase | Expected | Outcome | Exit | Auto Baseline (0-2) | Reviewer Delta (-1/0/+1) | Final (0-2) | Evidence | Notes |
|---|---|---|---|---:|---:|---:|---:|---|---|
| `RT-001` | static | fail | pass | 1 | 2 | 0 | 2 | `must not contain ## Recommendation` | [ERROR] Validation failed |
| `RT-002` | static | fail | pass | 1 | 2 | 0 | 2 | `must include an inline citation` | [ERROR] Validation failed |
| `RT-003` | static | fail | pass | 1 | 2 | 0 | 2 | `must start with UNVERIFIED:` | [ERROR] Validation failed |
| `RT-004` | static | fail | pass | 1 | 2 | 0 | 2 | `requires at least 1 blocking risks` | [ERROR] Validation failed |
| `RT-005` | static | fail | pass | 1 | 2 | 0 | 2 | `requires an improvement artifact` | [ERROR] Validation failed |
| `RT-006` | static | fail | pass | 1 | 2 | 0 | 2 | `requires an improvement artifact with Status: applied` | [ERROR] Validation failed |
| `RT-007` | static | fail | pass | 1 | 2 | 0 | 2 | `Contract drift detected` | template workflow state machine drift |
| `RT-008` | static | fail | pass | 1 | 2 | 0 | 2 | `missing required phrase: template/OBSIDIAN.md` | Obsidian GitHub/Template section lost required template mapping |
| `RT-009` | static | fail | pass | 1 | 2 | 0 | 2 | `BOOTSTRAP_PROMPT.md missing required phrase: guard_contract_validator.py` | bootstrap lost contract-guard step |
| `RT-010` | static | fail | pass | 1 | 2 | 0 | 2 | `missing required ## Sources section` | [ERROR] Validation failed |
| `RT-011` | static | pass | pass | 0 | 2 | 0 | 2 | `Mapping To Plan entry must match` | [OK] Validation passed |
| `RT-012` | static | pass | pass | 0 | 2 | 0 | 2 | `missing reviewer field` | [OK] Validation passed |
| `RT-013` | static | fail | pass | 1 | 2 | 0 | 2 | `git-backed scope check found actual changed files not listed` | [ERROR] Validation failed |
| `RT-014` | static | fail | pass | 1 | 2 | 0 | 2 | `commit-range scope check found diff files not listed` | [ERROR] Validation failed |
| `RT-015` | static | fail | pass | 1 | 2 | 0 | 2 | `--allow-scope-drift requires a decision artifact with ## Guard Exception` | [ERROR] Validation failed |
| `RT-016` | static | pass | pass | 0 | 2 | 0 | 2 | `[OK] Validation passed` | [OK] Validation passed |
| `RT-017` | static | fail | pass | 1 | 2 | 0 | 2 | `Snapshot SHA256 does not match Changed Files Snapshot` | [ERROR] Validation failed |
| `RT-018` | static | fail | pass | 1 | 2 | 0 | 2 | `github-pr scope check found diff files not listed` | [ERROR] Validation failed |
| `RT-019` | static | fail | pass | 1 | 2 | 0 | 2 | `commit-range archive fallback found diff files not listed` | [ERROR] Validation failed |
| `RT-020` | static | fail | pass | 1 | 2 | 0 | 2 | `Archive SHA256 does not match archive file` | [ERROR] Validation failed |
| `RT-021` | static | pass | pass | 0 | 2 | 0 | 2 | `lightweight candidate` | [OK] Validation passed |
| `RT-022` | static | pass | pass | 0 | 2 | 0 | 2 | `[AUTO-UPGRADE]` | auto_upgrade_log written to status.json |
| `RT-023` | static | fail | pass | 1 | 2 | 0 | 2 | `waiver expired` | [ERROR] Validation failed |
| `RT-024` | static | fail | pass | 1 | 2 | 0 | 2 | `API Base URL host '127.0.0.1' is not allowed` | [ERROR] Validation failed |
| `RT-025` | static | pass | pass | 0 | 2 | 0 | 2 | `[OK] Validation passed` | [OK] Validation passed |
| `RT-026` | static | fail | pass | 1 | 2 | 0 | 2 | `Text file too large` | [FAIL] Text file too large: C:\Users\Arcobaleno\Documents\Code\consilium-fabri\.codex-red-team\RT-026-be3a17bc\artifacts\plans\TASK-976.plan.md exceeds size ceiling of 524288 bytes |
| `RT-027` | static | fail | pass | 1 | 2 | 0 | 2 | `exceeds replay byte cap` | [ERROR] Validation failed |
| `RT-028` | static | fail | pass | 1 | 2 | 0 | 2 | `exceeds replay byte cap` | [ERROR] Validation failed |
| `RT-029` | static | fail | pass | 1 | 2 | 0 | 2 | `template/README.md section 'Architecture Snapshot' contains forbidden phrase: template/ + .github/ + OBSIDIAN.md + external/` | template README architecture snapshot regressed to source-only wording |
| `RT-030` | static | pass | pass | 0 | 2 | 0 | 2 | `fail-closed external legacy import confirmed` | unparseable external legacy verify stays deferred with open verification debt |
| `RT-LIVE-950` | live | pass | pass | 0 | 2 | 0 | 2 | `[OK] Validation passed` | TASK-950 live drill should stay valid after decision / improvement closure |
| `RT-LIVE-951` | live | pass | pass | 0 | 2 | 0 | 2 | `[OK] Validation passed` | TASK-951 live drill should prove Gate E before resume |
| `PR-001` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | CLAUDE/CODEX prompts should enforce STOP or blocked behavior under ambiguous or invalid inputs |
| `PR-002` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Prompt contracts should prevent role overreach across Claude/Gemini/Codex |
| `PR-003` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Research prompt should enforce claim-level citation and anti-fabrication rules |
| `PR-004` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Research prompt should isolate upstream truth source from local fork assumptions |
| `PR-005` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Research prompt should explicitly forbid recommendation or architecture design outputs |
| `PR-006` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Implementation prompt should keep blocked criteria explicit and avoid optimistic ambiguity |
| `PR-007` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Implementation prompt should enforce premortem quality before coding |
| `PR-008` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Claude prompt should rely only on artifacts and reject completion without artifacts, verification, and evidence |
| `PR-009` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Workflow prompt should distinguish source template repos from downstream terminal repos |
| `PR-010` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Gemini prompt should block bad research inputs and keep active workflow files on the allowlisted Gemini models |
| `PR-011` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Codex prompt should preserve approved-plan discipline, summary artifacts, and single-writer behavior |
| `PR-012` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Workflow contract should route conflicts into a recorded decision log before progress continues |
| `PR-013` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Workflow contract should define when a decision artifact is mandatory for conflicts, tradeoffs, and validation failures |
| `PR-014` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Decision artifacts should preserve the chain from issue to follow-up rather than a single conclusion |
| `PR-015` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Claude prompt should stop and record external environment, build, or test failures without expanding scope |
| `PR-016` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Workflow contract should require an explicit decision waiver before --allow-scope-drift can downgrade failures |
| `PR-017` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Workflow contract should define commit-range diff evidence for clean-task historical reconstruction |
| `PR-018` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Workflow contract should require pinned commits plus snapshot checksum for immutable historical replay |
| `PR-019` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Workflow contract should define GitHub PR files evidence, API base override, and token boundary for provider-backed replay |
| `PR-020` | prompt | pass | pass | 0 | 2 | 0 | 2 | `Prompt Regression Report` | Workflow contract should define archive-backed fallback and archive integrity checks when git objects are no longer available |

## Summary

- Cases: 52
- Case Passed: 52
- Case Failed: 0

## Review Rules

- `Auto Baseline (0-2)`: 2 = `Outcome` 為 pass；0 = `Outcome` 為 fail。
- `Reviewer Delta`: 僅允許 `-1`、`0`、`+1`，且任何非 0 都要在 Notes 補原因。
- `Final`: `clamp(Auto Baseline + Reviewer Delta, 0, 2)`。
