# Artifact Spec: improvement

> 本檔由 `docs/artifact_schema.md` §5.9 拆分而來；schema literal、欄位定義、字串契約皆與原檔逐字對齊。

## 5.9 Improvement Artifact Schema (PDCA Act + Double-Loop Learning)

> PDCA Stage: A (Act，Gate E 之核心 artifact，回灌至下一輪 Plan)

**Double-Loop Learning framing（Argyris 1977）**：本 artifact 為 Argyris 雙迴路學習之具體落地。單迴路（Single-Loop）為「失敗 → 修 code」，僅在行為層調整；雙迴路（Double-Loop）為「失敗 → 檢討產生此錯誤之系統規則 → 修運作層邏輯」。本 schema 之 `## Why It Was Not Prevented`（為何既有 guard / schema / prompt 未阻擋此錯誤）與 `## Preventive Action (System Level)`（修 prompt-patterns / guard / template / workflow）即雙迴路之強制欄位；single-loop 之即時修正則於 code artifact 與本 artifact 之 `## Corrective Action` 承接。此區隔使 improvement artifact 不退化為「只記症狀」。

檔名：`artifacts/improvement/TASK-001.improvement.md`

用途：`improvement` artifact 同時承接兩種場景：

1. **Gate E / PDCA**：任務發生 failure、blocked、或流程缺陷後，分析根因、執行矯正、提出系統層級預防措施。
2. **Post-run review**：任務已跑到 `verify` 或 `done` 後，用 human-first 方式快速記錄流程實際怎麼走、哪些步驟浪費、哪些地方最容易重犯。

命名規則：

- 主要改進：`TASK-001.improvement.md`
- 同一任務多次改進：`TASK-001-IMP-002.improvement.md`

必填區段（Gate E / validator-compatible profile）：

```md
# Process Improvement

## Metadata
- Task ID:
- Artifact Type: improvement
- Source Task:
- Trigger Type: (failure / blocked / inefficiency / guard miss)
- Improvement Profile: (gate-e / retrospective)
- Owner: Claude
- Status: draft
- Last Updated:

## Risk Analysis (新增)
- Predicted Risks: [R1, R2, ...]  # 來自 plan artifact 的 premortem 預測
- Realized Risks: [R1]             # 此次 blocked/failure 中實際發生的
- Missed Risks: []                 # plan 未預測但實際發生的（若無填 None）

## 1. What Happened

## 2. Why It Was Not Prevented

## 3. Failure Classification

## 4. Corrective Action (Immediate)

## 5. Preventive Action (System Level)

## 6. Validation

## 7. Impact Scope

## 8. Final Rule

## 9. Status
```

欄位規則：

- `Trigger Type`: 必須為 `failure`、`blocked`、`inefficiency` 或 `guard miss` 之一。
- `Improvement Profile`: `gate-e` 用於 blocked/failure 後的恢復治理；`retrospective` 用於 verify/done 後的常規復盤。
- `## Risk Analysis` (新增)：追蹤 premortem 預測與實際風險的映射。
  - `Predicted Risks`: 從 plan artifact 中的 `## Risks` 區段複製所有 R 編號（例如 `[R1, R2, R3]`）。
  - `Realized Risks`: 此次故障中實際觸發的風險編號。必須是 Predicted Risks 的子集或超集。若為超集，說明是 missed risk。
  - `Missed Risks`: 若有未在 plan 預測但實際發生的風險，在此列舉；若無填 `None`。此欄用於評估 premortem 品質。
- `## 1. What Happened`: 必須具體描述發生在哪個階段（Plan / Do / Check / Act）、哪個 agent、哪個 artifact，並用編號指出是哪條 Realized Risk。
- `## 2. Why It Was Not Prevented`: 必須指出哪條規則缺失、哪個 guard 沒覆蓋、哪個 prompt 太寬鬆。
- `## 3. Failure Classification`: 至少勾選一個分類（G1–G6、Premortem failure、Unknown gap）。
- `## 5. Preventive Action (System Level)`: **最重要區段**。必須至少包含一項：Prompt 修正、Guard 規則補強、Template 修正、或 Workflow 調整。
- `## 8. Final Rule`: 將改進轉成一句可執行規則。
- `## 9. Status`: `draft` → `approved` → `applied`。

輕量復盤區段（post-run review profile）：

```md
## What Actually Happened

## Steps That Felt Redundant

## Error-Prone Steps

## Surprises / Mismatches

## Template / Workflow Fix Candidates

## Next Time Default
```

使用原則：

- 任務完成到 `verify` 或 `done` 後，建議補一份短 improvement artifact，即使該任務沒有進入 `blocked`。
- 若 improvement artifact 需要同時滿足 **Gate E** 與 **日常復盤**，請保留上方 validator-compatible 區段，並在 `## 9. Status` 後追加上述 6 個 human-first 區段。
- `## What Actually Happened` 應描述實際流程，而不是理想流程。
- `## Steps That Felt Redundant` 應只寫真正造成浪費的步驟，不列無關背景。
- `## Error-Prone Steps` 應指出最可能重犯的操作、判斷或 handoff。
- `## Surprises / Mismatches` 用於記錄「文件寫的流程」與「實際跑出來的流程」之間的落差。
- `## Template / Workflow Fix Candidates` 應明確標示該改 template、prompt、guard、還是單純操作說明。
- `## Next Time Default` 應把本次學到的更佳預設寫成一句可直接重用的操作準則。

Repo-level quick index：

- `artifacts/improvement/PROCESS_LEDGER.md` 是 repo-level operational note，不屬於 validator 強制 artifact。
- 用途：作為冷啟動入口，快速回顧最近流程實際做了什麼、哪裡浪費、哪裡容易出錯。
- 欄位固定為 `Date`、`Task`、`Outcome`、`Top Waste`、`Top Risk`、`Fix Candidate`、`Applied?`。
- 建議閱讀順序：先看 `PROCESS_LEDGER.md`，再看最近 3 份 `TASK-XXX.improvement.md`，需要細節時再回跳 `verify` / `decision` / `status`。

工作流規則：

- **Gate E (PDCA)**：任何任務從 `blocked` 恢復前，必須先建立且通過驗證的 improvement artifact。`guard_status_validator.py` 在 `blocked → *` 轉移時自動檢查。
- 恢復前的 improvement artifact 必須為 `Status: applied`。`draft` 或 `approved` 不足以解除 blocked。
- **Routine review**：任務完成 `verify` 或 `done` 後，建議追加一份短 improvement artifact 並更新 `PROCESS_LEDGER.md`，但這不會改變 Gate E 的 validator 規則。

最低驗收標準：

- 不可只描述問題而無預防措施。
- 不可把整份 command log 或 raw terminal output 直接貼進 improvement artifact；應只保留短結論與必要 artifact path。
- Preventive Action 不可只寫「注意一下」，必須是可被 guard / prompt / template 執行的具體改動。
- Final Rule 必須是一句可直接加入 CLAUDE.md 或 guard script 的規則。
- `Validation` 不可空白，必須說明如何驗證該改善已落地。

---
