# Artifact Spec: task

> 本檔由 `docs/artifact_schema.md` §5.1 拆分而來；schema literal、欄位定義、字串契約皆與原檔逐字對齊。

## 5.1 Task Artifact Schema

> PDCA Stage: P (Intake，定義階段，先於 Plan)

檔名：`artifacts/tasks/TASK-001.task.md`

用途：任務的單一權威定義。

必填區段：

```md
# Task: TASK-001

## Metadata
- Task ID:
- Artifact Type: task
- Owner:
- Status:
- Last Updated:

## Objective

## Background

## Inputs

## Constraints

## Acceptance Criteria

## Dependencies

## Out of Scope

## Assurance Level

## Project Adapter

## Current Status Summary
```

欄位規則：

- `Objective`: 一句到數句，清楚描述任務最終目標。
- `Inputs`: 指出可用檔案、模組、文件或使用者需求。
- `Constraints`: 必須明確列出不可違反條件。
- `Acceptance Criteria`: 必須條列且可驗證。
- `Out of Scope`: 避免 Codex 擴大實作範圍。
- `Assurance Level`: 目前允許 `POC`、`MVP`、`Production`；決定最低驗證強度與 required artifacts。
- `Project Adapter`: 目前允許 `generic`、`web-app`、`backend-service`、`batch-etl`、`cli-tool`、`docs-spec`、`resource-constrained-ui`；用於承接 runtime-specific 驗證規則。

最低驗收標準：

- 驗收條件不可空白。
- 至少一條 `Out of Scope` 或明確寫 `None`。
- `Constraints` 不可省略。

### Assurance / Adapter Rule Resolution

`Assurance Level` 與 `Project Adapter` 的唯一權威規則表位於 `artifacts/scripts/workflow_constants.py`。

- resolver 固定先套 `Assurance Level` baseline，再套 `Project Adapter` override，最後產生單一 resolved policy。
- `required artifacts`、verify required fields / sections、allowed `reason_code`、`verification_readiness` 都必須讀 resolved policy，不得從 artifact 偶然存在與否反推。
- `docs-spec` 是目前唯一已明確特化的 adapter：它會在 `testing / verifying / done` 移除 `test` requirement，並允許 `NOT_APPLICABLE_BY_ADAPTER`。
- 其餘 adapter 目前都明確繼承 `generic`；若未補專屬規則，表示它們暫時只共享 generic baseline，而不是已完整驗證通用性。

---
