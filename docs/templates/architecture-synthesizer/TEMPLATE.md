---
name: architecture-synthesizer
description: Gemini SECI Architecture Synthesizer dispatch template (active scan → architecture guidance draft)
version: 1.0.0
applicable_agents:
  - Gemini CLI
applicable_stages:
  - closure
  - sprint-review
prerequisites:
  - PROCESS_LEDGER.md 累積條目達 N=10 倍數，或使用者手動觸發
---

## Role

Gemini SECI Architecture Synthesizer (Active Knowledge Externalization)。為 Memory Bank Curator 之**主動掃描**對應模式：定期讀取近 N 個 decision / improvement artifact，從碎片經驗中抽取共通模式，外化為架構指引 draft。對應 SECI 之 Externalization 階段（tacit → explicit）。

## Inputs

- 近 N=10 個（或使用者指定區間之）`artifacts/decisions/TASK-*.decision.md`
- 對應之 `artifacts/improvement/TASK-*.improvement.md`（若存在）
- `artifacts/improvement/PROCESS_LEDGER.md`（按時間排序之 closure ledger）
- `.github/memory-bank/architecture-synthesis-cache.md`（既有 cache，避免重複抽取已沉澱之模式；若不存在，視為首次掃描）
- 既有 `.github/memory-bank/{artifact-rules,workflow-gates,prompt-patterns,project-facts}.md`（避免與既有規範衝突或重複）

## Task

從輸入之 decision / improvement artifact 中**萃取共通模式**：

1. **失敗模式聚類**：將 N 份 improvement 之 `## Why It Was Not Prevented` 條目聚類，找出反覆觸發之 system-level gap（如「prompt 模糊化」「guard 規則缺漏」「artifact schema 邊界含糊」）。
2. **決策模式聚類**：將 N 份 decision 之 `## Chosen Option` 與 `## Reasoning` 聚類，識別 routing override / scope-drift waiver 之共通觸發條件。
3. **架構指引候選**：對每個聚類，產出一條候選之 system-level 修補建議（targets：prompt-patterns / guard rule / artifact schema / template / workflow doc）。

每個聚類至少 2 個 source artifact 為依據，否則視為單例不入 cache。

## Rules

- **不得直寫 `.github/memory-bank/`**：依 [GEMINI.md](../../../GEMINI.md) §Memory Bank Curator 規則，Gemini 為 read-only curator。所有輸出為 draft 寫入 `.github/memory-bank/architecture-synthesis-cache.md`，由 Claude / Codex 審核後才可進入 prompt-patterns.md 等正式 memory-bank 檔。
- **token 預算**：一次掃描限 ≤ 8 個 artifact；超出須分批；每批之間記錄 cursor（`Last Synthesized: TASK-XXX, retrieved YYYY-MM-DD`）。
- **輸出格式嚴格**：每候選 guidance 須含 cluster name / source artifacts / pattern description / proposed system-level fix / target file / **Existing Cache Match**。
- **不得替代 closure 級 Remember Capture**：本模式為 active scan，與 closure-triggered single-task curator（[`.github/prompts/remember-capture.prompt.md`](../../../.github/prompts/remember-capture.prompt.md)）並存；二者不衝突，cache 之 draft 於 sprint review 時由 Claude 整合。
- **不得跨 N 個任務之外推測未來**：本模式為 retrospective synthesis，僅描述已發生之模式，不預言未來。

## Anti-Snowball Guard（防雪球效應 — SECI Combine 階段必讀）

本 template 之 cache 為 append 結構，但若無防雪球機制，多次 dispatch 將累積重複 / 衝突 cluster，致 Claude 之 Combine 階段（SECI 第三步）負荷劇增、記憶污染、決策失準。Synthesizer dispatch 時須遵：

### 1. Pre-dispatch context load（dispatch 前必讀）

每次 Synthesizer dispatch **必先** 讀入：

- `.github/memory-bank/architecture-synthesis-cache.md` 之全部既有 Synthesis section（取最近 ≤ 5 個 sweep）
- `.github/memory-bank/{prompt-patterns,artifact-rules,workflow-gates,project-facts}.md` 之最新版（避免重複沉澱已正式進入 memory-bank 之知識）

若任一檔讀取失敗，報 `## Blocked Reason: cannot load prior cache, anti-snowball guard requires baseline`。

### 2. Reference Range 顯式聲明

每 Synthesis section 標頭 **必含** `Reference Range: TASK-XXX..TASK-YYY`（X、Y 為任務 ID 區間端點，含端）。範圍須與既有 cache section 之 Reference Range **不重疊**；若重疊，報 blocked 並提示使用者調整 sweep 區間。

### 3. Existing Cache Match 必填

每 cluster 須含欄位 `Existing Cache Match`，值為以下其一：

- `none`：cache 中無相近 pattern；本 cluster 為新增。
- `superseded-by:<section-id>`：cache 中已有相近 pattern 但本 cluster 之 evidence 更強，建議覆寫舊條目（須產生 decision artifact）。
- `duplicate-of:<section-id>`：cache 中已有相同 pattern，本 cluster 跳過（不寫入）。
- `extends:<section-id>`：本 cluster 為既有 cluster 之延伸 / 補強，須引用舊條目並標明擴張部分。

### 4. Conflict Resolution Rule

若新 cluster 之 `Proposed System-Level Fix` 與既有 cache section 之 fix **直接衝突**（如「強制 X」vs「禁止 X」），Synthesizer **不得自行決定**，須：

- 於 cluster 加 `Conflict-With: <section-id>`
- 於 output 末段加 `## Blocked Conflict` 列出全部衝突對
- 報 blocked 待 Claude 裁決，由 Claude 起 decision artifact 後再決定是否覆寫舊條目

### 5. Override 紀律

舊 cache section 之覆寫**僅由 Claude 執行**，且須：

- 對應 decision artifact（含 `Decision Class: conflict-resolution`）
- 舊 section 不刪除；改加 `Status: superseded-by:<new-section-id>` 標頭，保留歷史
- 新 section 標頭加 `Supersedes: <old-section-id>`

如此確保 cache 永遠為 append-only，歷史不被湮滅，Combine 階段可隨時回溯。

## Output

寫入：`.github/memory-bank/architecture-synthesis-cache.md`（append-only，每次掃描為一新區段，含時戳）

格式：

```md
## Synthesis YYYY-MM-DDTHH:MM:SS+08:00 (Sweep N: TASK-XXX..TASK-YYY)

### Source Artifacts
- artifacts/decisions/TASK-XXX.decision.md
- artifacts/improvement/TASK-XXX.improvement.md
- ...

### Cluster A: <短名>
- Pattern: <反覆出現之模式描述>
- Sources: TASK-AAA, TASK-BBB（≥2）
- Proposed System-Level Fix: <具體可執行之修補建議>
- Target File: <如 .github/memory-bank/prompt-patterns.md / docs/artifact_schema.md / artifacts/scripts/guard_status_validator.py>
- Existing Cache Match: none | superseded-by:<section-id> | duplicate-of:<section-id> | extends:<section-id>
- Conflict-With: <section-id>（僅當衝突時填，否則省略）

### Cluster B: ...
```

當 Synthesis section 須覆寫舊條目時（由 Claude 於 Combine 階段執行）：

```md
## Synthesis YYYY-MM-DDTHH:MM:SS+08:00 (Sweep N: TASK-XXX..TASK-YYY)
- Supersedes: <old-section-id>
- Decision: artifacts/decisions/TASK-ZZZ.decision.md (Decision Class: conflict-resolution)

...
```

舊 section 加標頭 `Status: superseded-by:<new-section-id>` 但內容保留，不刪除。

## Required Sections In Output

- Source Artifacts（至少 N 個 input artifact 路徑）
- Cluster N（≥1 個聚類，每個 ≥2 sources）
- Per cluster: Pattern, Sources, Proposed Fix, Target File

## When To Report Blocked

- N 個 input artifact 中無聚類（每個皆單例）：報 `## Blocked Reason: insufficient pattern density`，留待下次掃描
- Source 之 `## Why It Was Not Prevented` 全部空白或 `None`：報 blocked，提示 improvement artifact 品質不足以支撐 synthesis
- Cache 已含相同 cluster：跳過該 cluster，於 output 註明 `(skipped: already in cache)`

## Trigger

- 自動：[artifacts/improvement/PROCESS_LEDGER.md](../../../artifacts/improvement/PROCESS_LEDGER.md) 條目達 N=10 倍數時，由 Claude 或 ledger 計數腳本主動 dispatch。
- 手動：使用者於任意時刻請 Claude 執行（如 sprint review、季度復盤）。
