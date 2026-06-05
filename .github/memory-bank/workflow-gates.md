# Workflow Gates — Guard Validator 觸發條件

**Reference**: artifacts/scripts/guard_status_validator.py  
**Last Verified**: 2026-04-25 +08:00

## Intake 自 Research 轉換

- Task artifact 必須存在且 status ∈ {`drafted`, `approved`, `blocked`} — see docs/artifact_schema.md §4.2
- 若無 research artifact，guard 自動建議進入 lightweight mode
- Lightweight mode 不要求 premortem，只需 basic plan

## Research 自 Planning 轉換

- Research artifact 必須包含 `## Sources`（至少 2 條來源）
- 每個源必須附 URL 或 internal reference
- 若只有摘述，缺少原始連結，guard 會警告但不擋

## Planning 自 Coding 轉換

```
IF task.lightweight == true:
    SKIP premortem, allow direct to coding
ELSE:
    REQUIRE plan.## Risks with R1-R4
    IF plan.## Risks is empty or contains <2 entries:
        BLOCK with "incomplete_premortem"
    ELSE IF any risk lacks Trigger/Detection/Mitigation:
        WARN but allow (can fix in code phase)
```

## Pre-Coding Context Review（可選）

在 Planning → Coding 之間，可執行 `context-review.prompt.md` 對 plan 的 Files Likely Affected 做檔案級預檢。
詳見 `.github/prompts/context-review.prompt.md`。

建議觸發條件：
- 任務觸及 5+ 檔案
- 跨模組修改
- 需求仍有模糊點

此步驟非強制 gate，不阻擋流程。目的是在派發 Codex 前補強檔案級就緒度，減少 scope-drift。

## Coding 自 Review 轉換

- Code artifact 存在且包含 Files Changed
- Plan 的 Files Likely Affected 包含 Code 的 Files Changed
- 若 code 改了未計劃的檔案，設 status = scope-drift-detected
- 可用 decision 的 Guard Exception override

## Review 自 Verification 轉換

- Verify artifact 必須包含 `## Environment` 和 `## Build Guarantee`
- Build Guarantee 至少 1 條：commit hash、CI log URL、binary checkpoint

## Blocked 自 Recovery 轉換（Gate E — PDCA Act → Plan 回灌）

任何 blocked 任務恢復前必須通過 Gate E：

- 必有 [improvement artifact](../../artifacts/improvement/) 且 `Status: applied`（見 [docs/schemas/artifact-spec-improvement.md](../../docs/schemas/artifact-spec-improvement.md)）
- improvement artifact 必含 `## What Happened`、`## Why It Was Not Prevented`、`## Preventive Action (System Level)`
- status.json 之 `Gate_E_evidence` 須引用 improvement / decision artifact 路徑
- status.json 之 `Gate_E_timestamp` 必填

**PDCA Act → Plan 回灌語意**：Gate E 即 PDCA 之 Act 階段觸點。`Preventive Action (System Level)` 條目即為下一輪 Plan 階段之輸入；下一個觸發相同 risk 之 task，其 plan 之 `## Risks` 應引用 prior improvement 為 mitigation 來源。詳見 [docs/orchestration.md §2.8](../../docs/orchestration.md) 兩層架構章節。

未通過 Gate E 即試圖恢復 blocked 任務，[guard_status_validator.py](../../artifacts/scripts/guard_status_validator.py) 會 hard fail。

## Lightweight Mode

自動觸發條件：
- Task 小（`lightweight: true` in task.metadata）
- 或 task 在 `drafted` / `researched` 且無 plan artifact 且無 code artifact

輕量級標準：
- 不要求 R1-R4 premortem
- 需要 basic plan with objectives
- 需要 code artifact with Files Changed
- 需要 verify with Environment

重量級標準（預設）：
- 需要完整 premortem (R1-R4+)
- 需要 verify with Build Guarantee

升級條件：若任務變複雜，自動升級回 full gate（guard 會偵測）
