---
applyTo: "**"
---

# Context Review — 修改前預檢

## 何時用

Plan artifact 完成後、派發實作前。
在 `## Files Likely Affected` 的每個檔案上做檔案級分析，確保進入 Coding 階段時上下文清晰。

建議觸發條件：
- 任務觸及 5 個以上檔案
- 跨模組修改
- 需求仍有模糊點
- 上一次同類任務曾出現 scope-drift

不建議用於：單檔修改、lightweight mode 的小任務。

## 輸入

Plan artifact 路徑（例：`artifacts/plans/TASK-XXX.plan.md`）

## 流程

### Step 1 — 讀取 Files Likely Affected

從 plan artifact 的 `## Files Likely Affected` 取得檔案清單。

### Step 2 — 逐檔分析

對每個檔案檢查：

| 檢查項 | 方法 | 風險信號 |
|---|---|---|
| 存在性 | 確認檔案存在 | 檔案不存在 = 新建檔，需確認是否在 plan 中已說明 |
| Import graph | 讀取 import/using/require 語句 | 高扇出 = 修改波及範圍大 |
| Companion test | 搜尋對應測試檔（`test_*.py`, `*_test.py`, `*.test.ts` 等） | 無測試 = 覆蓋率缺口 |
| 近期 churn | `git log --oneline -5 <file>` | 近期頻繁修改 = 可能有進行中的平行工作 |
| 已知 gotcha | 比對 `memory-bank/artifact-rules.md` 與 `project-facts.md` | 命中已知規則 = 提前標記 |

### Step 3 — 交叉比對

- 比對 plan 的 `## Risks` (R1-R4) 是否涵蓋了 Step 2 發現的風險
- 若有 Step 2 發現但 plan 未列的風險，標記為 Gap

## 輸出格式

固定使用以下結構：

```
## Context Review — TASK-XXX

### Files
| File | Exists | Imports | Test Companion | Recent Churn | Gotcha |
|---|---|---|---|---|---|
| path/to/file.py | Yes | 3 imports | test_file.py | 2 commits in 7d | None |

### Dependencies
- [列出跨檔案的 import 關係圖要點]

### Tests
- [列出受影響的測試檔案]
- [標記無測試覆蓋的檔案]

### Reference Patterns
- [從 memory-bank 或既有程式碼中找到的可參考實作]

### Risk Assessment
- [Step 2 發現的風險]
- [與 plan R1-R4 的 gap 分析]

### Missing Information
- [模糊點、無法確認的依賴、需人工補充的資訊]
```

## 重要限制

- 此 prompt 僅做分析，不修改任何檔案
- 不展開整個 repo，只分析 plan 列出的檔案及其直接依賴
- 若任務描述模糊，把模糊點列在 Missing Information，不猜測
- 不取代 premortem（premortem 是專案級風險，context review 是檔案級就緒度）
