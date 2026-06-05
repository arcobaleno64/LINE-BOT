# Artifact Spec: verify

> 本檔由 `docs/artifact_schema.md` §5.6 拆分而來；schema literal、欄位定義、字串契約皆與原檔逐字對齊。

## 5.6 Verify Artifact Schema

> PDCA Stage: C (Check，含 Build Guarantee)

檔名：`artifacts/verify/TASK-001.verify.md`

用途：對照 acceptance criteria 做最終驗收。

必填區段：

```md
# Verification: TASK-001

## Metadata
- Task ID:
- Artifact Type: verify
- Owner:
- Status:
- Last Updated:

## Verification Summary

## Acceptance Criteria Checklist

## Overall Maturity

## Deferred Items

## Evidence

## Evidence Refs

## Decision Refs

## Build Guarantee

## TAO Trace

## Pass Fail Result

## Remaining Gaps

## Recommendation
```

欄位規則：

- `Acceptance Criteria Checklist`: 必須逐條對照 task artifact。
- `Acceptance Criteria Checklist` item schema: `required_fields_by_assurance`
  - `POC`: `criterion`, `method`, `evidence`, `result`
  - `MVP`: `criterion`, `method`, `evidence`, `result`
  - `Production`: `criterion`, `method`, `evidence`, `result`, `reviewer`, `timestamp`
- `Acceptance Criteria Checklist` item `result` 必須使用：`verified`、`unverified`、`unverifiable`、`deferred`。
- 若 `result` 為 `unverified`、`unverifiable` 或 `deferred`，必須同時記錄 `decision_ref` 或 `reason_code`。
- `Acceptance Criteria Checklist` item `reason_code` 與 disallowed results 必須讀 resolved policy，不得在 validator / migration script 各自維護另一套清單。
- `Acceptance Criteria Checklist` item schema: `timestamp` 必須為 `Asia/Taipei` 的 ISO 8601 並帶 `+08:00`。
- `Verification Summary`: 用一段短文交代本次 verify 的覆蓋範圍與主要限制。
- `Overall Maturity`: 目前允許 `poc`、`mvp`、`production-blocked`、`production-ready`。
- `Deferred Items`: 沒有時寫 `None`；若有 deferred/unverifiable 項目，需與 checklist / decision refs 對應。
- `Deferred Items` 與 `status.open_verification_debts` 必須能由 checklist item 中落在 `status_debt_results` 的 `result` 推導；不得再用 `Remaining Gaps` 承載正式 debt 狀態。
- `Evidence`: 指向 code/test/research/decision artifacts。
- `Evidence Refs`: 列 repo-relative artifact path，方便機器檢查存在性。
- `Decision Refs`: 列 repo-relative decision path；沒有時寫 `None`。
- `Build Guarantee` (FUP-2)：針對本 task 修改過的**每一個** build 單元，明列 build 指令、exit code、與 output tail。
  - .NET 任務：對每個被修改的 `.csproj` 執行 `dotnet build <csproj> -c Debug` 並貼出結尾段落（含「建置成功/錯誤」或等價 summary）。
  - 非 .NET 任務（python / node / etc.）：列對應 build / type-check / lint 指令與結果。
  - 若本 task 未修改任何 `.csproj` 或等價 build 單元，寫 `None (no .csproj modified)` 並簡述原因（例如純文件變更、python-only 任務）。
  - **禁止**以「測試專案 build 成功」替代「被測專案 build 成功」—— 兩者不等價。若發生此類事故，應建立 decision artifact 記錄根因與修正。
- `Pass Fail Result`: 只能填 `pass` 或 `fail`。
- `TAO Trace`: risk ≥ 3 之 verifier dispatch **必填**；其他可寫 `None`。schema 與必填欄位見 [docs/agentic_execution_layer.md §2](agentic_execution_layer.md)。回填既有 verify artifact 時須以 `Reconstructed from artifact history` 開頭。
- `Remaining Gaps`: 沒有時寫 `None`。
- `status.verification_readiness` 與 `status.open_verification_debts` 必須能由 verify artifact 的 structured checklist 推導，不可脫鉤。
- root repo tracked artifacts 不得依賴 legacy verify/status compatibility fallback；fallback 只保留給外部或歷史輸入。
- `artifacts/scripts/migrate_artifact_schema.py` 預設以 `--input-mode root-tracked` 執行；此模式只允許對 root tracked artifacts 做 deterministic normalization，不得把 heuristic import 當成日常治理路徑。
- 若要匯入外部 legacy artifact，必須顯式使用 `--input-mode external-legacy`。此模式允許 heuristic mapping，但 migration report 必須揭露 strategy / confidence / unresolved fields。
- `external-legacy` 模式下，只有已具 structured checklist 的 verify artifact 可直接保留原結果；heading block、checkbox list 與無法辨識的 legacy verify 一律必須降為 manual-review / deferred 路徑，不得直接升成 authoritative `pass`。

最低驗收標準：

- 未逐條對照 acceptance criteria 的 verify artifact 不合法。
- 若有未完成條件，不可標 `pass`。
- 缺少 `## Build Guarantee` 區段的 verify artifact 不合法；`guard_status_validator.py` 會在 `required_markers["verify"]` 擋下。

---
