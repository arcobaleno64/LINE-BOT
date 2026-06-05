---
applyTo: "**"
---

# Pack Context — 大型任務上下文收斂工具

## 何時用

- 任務涉及 3 個以上的 artifacts
- 需要跨多個 docs 文件查詢
- 在一次性大工作前想快速整理思路

## 輸入

提示詞範本：

```
我需要執行一個大任務。在實作前，請幫我整理上下文。
- 任務名稱：TASK-XXX
- 相關 artifacts：task.md、plan.md、research.md
- 涉及的 docs：artifact_schema.md §5.3, premortem_rules.md
- 主要問題：（描述關鍵問題）
```

## 輸出格式

```
## Context Pack — TASK-XXX

### 1. 任務核心
- 目標：（提煉目標）
- 輸入：（已有的 artifacts 或資料）
- 輸出：（要產生什麼）
- 驗收標準：（怎樣算完成）

### 2. 依賴與先決條件
- Artifact 依賴：（哪些 artifact 必須先完成）
- 文件引用：（涉及的 docs 章節）
- 外部依賴：（環境變數、工具、服務）

### 3. 關鍵規則
- Rule 1：（從 docs 摘錄的硬規則）
- Rule 2：（從 memory-bank 提取的經驗法則）
- Rule 3：（從 premortem 識別的風險）

### 4. 快速檢查清單
- [ ] 所有 artifacts 到位
- [ ] 所有 docs 都讀了摘要
- [ ] 所有風險都識別了
- [ ] 所有依賴都就位了

### 5. 進入點
- 若所有檢查通過，執行：（具體第一步）
- 若缺失 artifact，停在：（哪個 artifact needs rebuild）
```

## 範例

任務：完成 TASK-903（Guard Contract Validator 改進）。

```
相關 artifacts：
- artifacts/decisions/TASK-903.decision.md
- artifacts/plans/TASK-903.plan.md
- artifacts/research/TASK-903.research.md

涉及的 docs：
- docs/schemas/artifact-spec-verify.md §5.6（verify schema）
- docs/premortem_rules.md（風險）

請先幫我整理上下文。
```

## CLI Mode — code2prompt 整合（雙軌）

### Path A — CLI available

若環境中有 `code2prompt`，產生可執行命令：

```bash
code2prompt . \
  --include="artifacts/tasks/TASK-XXX*,artifacts/plans/TASK-XXX*,docs/artifact_schema.md" \
  --exclude=".git/**,bin/**,obj/**,node_modules/**,dist/**,.cache/**,*.env,*.pfx,*.key,secrets/**" \
  --tokens \
  --json \
  --output=".cache/context-pack.json"
```

輸出 token estimate。若超過 8K tokens，建議拆成 2-3 個 context packs。

### Path B — CLI unavailable

若無 `code2prompt`，改為手動模式：

- 輸出 include/exclude 清單（人可讀、可複製）
- 按上方 Context Pack 格式產生草案
- 標註「token 估算不可用，建議安裝 code2prompt 或手動控制檔案數量」

### 預設 Exclude 清單

以下路徑在兩種模式下都排除：

- `.git/**`
- `bin/**`, `obj/**`
- `node_modules/**`, `dist/**`
- `.cache/**`
- `*.env`, `*.pfx`, `*.key`
- `secrets/**`

### 安裝 code2prompt（附註）

```bash
# Rust（推薦）
cargo install code2prompt

# 或 Python
pip install code2prompt
```

code2prompt 為 optional tool，未安裝不影響手動模式。

## 限制

- 不要一次把整個 repo 全量打包
- 排除所有 secrets、憑證與個資
- 若無法確認某檔是否安全，先列入排除並提示人工確認
