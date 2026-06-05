# Artifact Rules — 已知觸發點與避免

**Reference**: CLAUDE.md §3, docs/artifact_schema.md §5  
**Last Updated**: 2026-04-16 +08:00

## Task Artifact

- 檔名必須嚴格遵循 `artifacts/tasks/TASK-XXX.task.md`（guard 只認此格式）
- Metadata 區段必須包含 `Task ID`、`Status`、`Owner`、`Last Updated`
- `Status` 只能用標準值：`drafted`, `approved`, `blocked`, `done` — see docs/artifact_schema.md §4.2

注意：自訂檔名（如 `task-notes.md`）會被 guard 忽略。

## Plan Artifact

- 進入 coding 前，`## Risks` 區段必須有至少 R1-R4 四條編號風險
- 若沒有 `## Risks` 或只有單句模糊敘述，guard 會拒絕進入 coding gate
- 每個 risk 須包含：Trigger、Detection、Mitigation、Severity

注意：R1-R3 沒有問題，但缺 R4，guard 會報 incomplete。

## Code Artifact

- `## Files Changed` 中列出的檔案必須在 plan 的 `## Files Likely Affected` 中也出現
- 若 code artifact 改了 status.json，plan 也要把 status.json 列進去，否則視為 scope drift

注意：改了 10 個檔案，但 plan 只列了 8 個加 status.json，會被 guard 標記。

## Verify Artifact

- 必須包含 `## Build Guarantee` 或等效的驗收憑證
- 若執行環境無法測試（如跨平台 GUI），要在 `## Environment Constraint` 中明確說明
- 票據形式：commit hash、CI log URL、或附檔（binary / checkpoint）

注意：只有「我測試過」，沒有 build log 或 commit，會被視為 UNVERIFIED。

## 例外流程

若需跳過或修改上述規則，decision artifact 必須包含：
- `## Guard Exception`
- `Exception Type: [allow-scope-drift | skip-premortem | ...]`
- `Scope Files` 或 `Justification`
- Guard 會在執行時檢查並允許(ALLOWED via decision)
