# LIGHTWEIGHT_MODE_RULES

本文件定義小型任務的簡化流程，避免 artifact-first 系統變成官僚地獄。

lightweight mode 的 assurance baseline 一律對應 `POC + generic`，不得再維護獨立於 resolved policy 的口語規則。
auto-classify 只保留為入口便利與升級判定；required artifacts、verify obligations、`verification_readiness` 一律走 resolved policy。

## 1. 適用條件

僅當符合以下全部條件時可使用：

- 修改範圍非常小（單一檔案或明確區塊）
- 不涉及外部 API 或新知識
- 不涉及架構變更
- 不影響多模組

若任一不符合，禁止使用 lightweight mode

## 2. 最小必要 artifacts

即使是小任務，仍必須有：

- task artifact
- code artifact
- status artifact
- verify artifact（若任務需要進入 `done` 狀態）

## 3. 可省略或精簡內容

在 lightweight mode 中可省略或精簡：

- research artifact（若 resolved policy 在當前 state 未要求，且任務不需查資料）
- test artifact（若 resolved policy 在當前 state 未要求，且既有驗證已足夠）
- verify artifact 的內容密度（低風險時可維持 `POC + generic` 的最小 required fields，但 structured checklist 不可省略）

> **重要**：`guard_status_validator.py` 對 `done` 狀態仍以 resolved policy 強制要求 verify artifact，且 verify 必須提供 structured checklist 與可推導的 `verification_readiness` / `open_verification_debts`。
> 若省略 verify artifact，任務將無法透過 validator 合法轉移至 `done`。
> 「可精簡」是指 verify artifact 的內容可以簡短，而不是整份文件不存在。
> verify checklist 的 `result` / `reason_code` / `Overall Maturity` 仍必須遵守 resolved policy，只是 `POC + generic` 的 required fields 較少。

## 3.5 範本規模適用矩陣

下表定義依工作型態 × 規模之必填範本（屬 docs convention，不擴 `guard_status_validator.py` 之 required_artifacts policy）。

允許之 scale 值：`lightweight | standard | full | both | all`。`both` 與 `all` 為 wildcard（`discover_templates.py --scale` 視為對所有 scale 命中）。

| 工作型態 | lightweight 必填 | standard 加增 | full 加增 |
|---|---|---|---|
| Bug fix | task + code + verify + Bug report | + Debug runbook | + RTM（影響範圍 ≥3 模組時） |
| Feature | task + plan + code + verify + Feature request + PR description | + SRS（lightweight subset）+ ADR（若架構變動） | + SRS（full）+ RTM |
| PR (對外) | task + code + verify + PR description | + decision（若架構變動） | + ADR |
| Refactor | task + plan + code + verify | + ADR（若架構變動） | + RTM（影響範圍重新計算） |

說明：

- 「lightweight 必填」指任一工作型態於 lightweight scale 下不可缺之最小範本集。
- 「+ X」表示由前一級 scale 加上之新範本，不重列前級已含項目。
- ADR 適用於跨多 task 之長期架構決策；單 task 內之 gate-blocking 決策請改用 `artifacts/decisions/{{TASK_ID}}.decision.md`。
- Debug runbook 為事件中 transient 紀錄，事件結束後須轉為 improvement artifact 留底。
- SRS / RTM 之 full 形式適用於跨模組功能；lightweight 形式可省略 SRS（task §AC 即足）並省略 RTM。

## 4. 不可省略

- acceptance criteria
- scope 定義
- files changed

## 5. 流程

```text
1. Claude 建立 task（state: drafted）
2. Claude 建立簡化 plan（state: planned；若不需 research 可直接從 drafted 跳至 planned）
3. Implementer 修改（state: coding）
4. 產出 code artifact（state: verifying）
5. Claude 更新 status 至 done
```

狀態路徑範例：

```text
drafted -> planned -> coding -> verifying -> done
```

## 6. 強制限制

- 不可因為是小任務就不記錄範圍
- 不可直接在主 thread 宣稱完成
- 不可跳過 code artifact

## 7. 何時升級為完整模式

以下情況必須升級：

- 發現需要查文件
- 發現修改範圍擴大
- 測試失敗
- 出現副作用或風險

## 8. 設計原則

lightweight mode 的目標是降低負擔，而不是降低紀律

如果你用它來偷懶，那這套系統會在一週內崩掉

