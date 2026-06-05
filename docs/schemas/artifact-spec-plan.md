# Artifact Spec: plan

> 本檔由 `docs/artifact_schema.md` §5.3 拆分而來；schema literal、欄位定義、字串契約皆與原檔逐字對齊。

## 5.3 Plan Artifact Schema

> PDCA Stage: P (Plan，含 premortem R1-R4+)

檔名：`artifacts/plans/TASK-001.plan.md`

用途：將需求與研究轉成可控實作範圍。

必填區段：

```md
# Plan: TASK-001

## Metadata
- Task ID:
- Artifact Type: plan
- Owner:
- Status:
- Last Updated:

## Scope

## Files Likely Affected

## Proposed Changes

## Risks

## Validation Strategy

## Verification Obligations

## Out of Scope

## Ready For Coding
```

欄位規則：

- `Scope`: 明確描述此次計畫包含哪些內容。
- `Files Likely Affected`: 至少列出模組、目錄或檔案群。若 task 專屬 artifact 仍位於 dirty git worktree 中，`guard_status_validator.py` 也會用實際 git changed files 自動比對這個欄位。
- `Proposed Changes`: 條列具體改動。
- `Risks`: 不可省略。必須執行 premortem 分析（見 `docs/premortem_rules.md`）。每條風險必須包含 R 編號 + Risk / Trigger / Detection / Mitigation / Severity 五欄位。Severity 只能填 `blocking` 或 `non-blocking`。一般任務至少 2 條風險；安全性 / 依賴升級 / upstream PR 至少 4 條且至少 1 條 blocking。品質規則見 `docs/premortem_rules.md` §4。`guard_status_validator.py` 在 `planned → coding` 時會自動檢查。
- `Validation Strategy`: 必須說明如何驗證成功。
- `Verification Obligations`: 明列這個 task 在 `verify` 與 `status.open_verification_debts` 層需要結清或明示 deferred 的驗證責任。
- `Ready For Coding`: 只能填 `yes` 或 `no`。

最低驗收標準：

- 未列影響範圍的 plan 不可進 coding。
- `Ready For Coding` 為 `yes` 前，必須已有對應 task artifact。
- 若 task 需要 research，則 plan 建立前必須已有 research artifact。

---
