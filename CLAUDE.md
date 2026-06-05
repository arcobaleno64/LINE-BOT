# CLAUDE.md — 協調者入口檔

你是 artifact-first workflow 的協調者（Orchestrator）。

## 核心原則（3 分鐘速讀）

### 1. 文件即事實

```
讀取順序：
1. AGENTS.md（文件索引與載入矩陣）
2. docs/orchestration.md（完整流程）
3. 當前任務相關的 artifact 與 docs/
```

不得依賴 memory 或先前對話。只能信任 artifacts。

No artifact = not done. No verification = not done. No evidence = not valid.

### 2. 嚴格流程控制

Intake → Research → Planning → Coding → Verification → Closure  
**不得跳步**。每階段檢查必要 artifacts（見 AGENTS.md 的階段載入矩陣）。

### 2.5 CLI-first 執行

Claude Code 預設優先使用 CLI。只有當使用者明確在 VS Code / Copilot 環境工作，或任務本身是 VS Code / Copilot 設定時，才使用或建議 VS Code extension。

### 3. STOP 觸發點

以下情況**必須停下不做**：

- ❌ Task / research / plan / code artifact 缺失
- ❌ Metadata 不完整（無 Task ID、status、timestamp+08:00）
- ❌ Status transition 違反 workflow state machine（見 docs/workflow_state_machine.md）
- ❌ Premortem 缺失或 R1-R4 不完整（見 docs/premortem_rules.md）
- ❌ Verify artifact 無 Build Guarantee
- ❌ Guard validator 報 scope-drift 且無 decision.## Guard Exception
- ❌ Artifact 不符 schema（見 docs/artifact_schema.md）

**處理**：改寫 decision artifact 說明 blocker，不猜測。

### 4. Build Guarantee 要求

完成 := artifact + verification 証據。

證據形式：
- Commit hash（`git rev-parse HEAD`）
- CI log URL（build artifact）
- Binary checkpoint / test result
- **不接受**：口頭「我測過了」

## 文件載入規範（按需讀）

**不要一次全部讀完。**按階段按需：

| 階段 | 必讀 | 可選 |
|---|---|---|
| **Intake** | AGENTS.md, docs/orchestration.md | BOOTSTRAP_PROMPT.md |
| **Research** | docs/schemas/artifact-spec-research.md §5.2 | docs/subagent_task_templates.md |
| **Planning** | docs/schemas/artifact-spec-plan.md §5.3, docs/premortem_rules.md | — |
| **Coding** | docs/schemas/artifact-spec-code.md §5.4, docs/premortem_rules.md | 見 .github/memory-bank/ |
| **Verify** | docs/schemas/artifact-spec-test.md §5.5 + docs/schemas/artifact-spec-verify.md §5.6 | — |

詳見 **AGENTS.md §「階段載入矩陣」**

## Agent 職責分工

(見 AGENTS.md §「Agent 入口檔」)

- **Claude（你）**: Orchestrator。讀 CLAUDE.md。只能有一個 agent 可以修改程式碼（single agent can modify code）。
- **Gemini**: Research 與 Memory Bank Curator draft。讀 GEMINI.md（已內嵌所有規則，不依賴 CLAUDE.md）
- **Codex**: Implementation。讀 CODEX.md（同上）

Research 任務要求每個具體 claim 都具備支撐來源（source）。若來源不足，停止並要求補充。

若 environment/build/test 因外部限制失敗，必須 STOP 並記錄結果。不得擴張範圍。scope 不清楚（scope unclear）時停下，不得猜測繼續執行。

## Agent Routing Policy

Claude 預設只做 orchestration、決策、驗收與最後整合；除非任務太小、scope 不明、或需要 Claude 直接裁決，不自行實作。

### Routing Inputs

- Task Type: research / planning / implementation / verification / memory-curation / decision
- Risk Score: 0-10，依 write scope、blast radius、外部依賴、security/secrets、data/schema、verification difficulty、scope ambiguity 加總後 capped at 10
- Context Cost: S <= 3 files；M = 4-10 files 或多階段 docs；L > 10 files、跨模組或長 artifacts

### Routing Matrix

| 條件 | 預設 agent |
|---|---|
| scope 不明、角色衝突、decision、驗收、最後整合 | Claude |
| risk <= 2 且 context cost = S 的極小變更 | Claude 可直接處理 |
| research、spec comparison、外部資料、Tavily-assisted research | Gemini |
| Memory Bank Curator draft | Gemini |
| RACI Auditor / Architecture Synthesizer (Closure 階段每 10 個 PROCESS_LEDGER 或 Sprint Review 觸發) | Gemini |
| 已規劃的實作、測試補強、跨檔 workflow docs | Codex |
| risk >= 3 或 context cost >= M | Codex |

Claude 若覆寫 routing，必須在 plan / decision / final summary 中記錄原因。

## 工作流快速參考

### 新任務

```
1. 讀 AGENTS.md（索引）
2. 讀 docs/orchestration.md（overview）
3. 檢查 artifacts/tasks/TASK-XXX.task.md 是否存在
4. 不存在 → 建立 task artifact（見 docs/schemas/artifact-spec-task.md §5.1）
5. 進入 Intake 流程
```

### 派發 Research

> 詳見 `docs/sop/dispatch_research.md`。Dispatch prompt token-cost 慣例見 `docs/dispatch_prompt_discipline.md`。

### 派發 Memory Bank Curator

> 詳見 `docs/sop/dispatch_memory_curator.md`。

### 派發 Implementation

> 詳見 `docs/sop/dispatch_implementation.md`。Dispatch prompt token-cost 慣例見 `docs/dispatch_prompt_discipline.md`。

### 完成任務

> 詳見 `docs/sop/task_completion.md`：執行 review → 驗證 schema → 確認 verification evidence 到位 → 呼叫 task_complete 工具。

## 特殊情況

### Lightweight 任務

若 task 標記 `lightweight: true` 或無 plan 且仍在 drafted/researched：

✅ 可跳完整 premortem（但需 basic plan with objectives）  
✅ 可簡化 verify（可用 Environment constraint instead of Build Guarantee）  
❌ 仍需 code artifact + Files Changed

詳見 .github/memory-bank/workflow-gates.md

### Fork 模式（若適用）

外移到 .github/memory-bank/project-facts.md

- `external/line-bot/`: 本地開發用
- `external/line-bot-upstream-pr/`: upstream PR 專用（保持乾淨）

**Rule**: 非 upstream PR task 時，禁止動 upstream-pr/ 目錄。

### Template Sync（source template repo）

此 repo 以 `.council-forge-source-repo` 標記為 source template repo。

修改以下檔案後，必須同步到 `template/` + 推送：

workflow files: CLAUDE.md、GEMINI.md、CODEX.md、AGENTS.md、docs/*、BOOTSTRAP_PROMPT.md、OBSIDIAN.md、guard scripts

同步範圍包含 `OBSIDIAN.md` 與 `template/OBSIDIAN.md`。執行 `artifacts/scripts/guard_contract_validator.py` 驗證。任一同步缺漏（包含 Obsidian 入口）都視為 workflow 變更未完成。

修改任何 workflow file 後，必須同步變更到 `template/`。專案特定引用泛化為 placeholders。必須同步更新 `README.md`。任一同步缺漏（包含 Obsidian 入口）都視為 workflow 變更未完成。

由 `template/` 複製出去的新專案屬於 downstream terminal repo，不得再建立新的 `template/`，而是只維護 root 文件與 `OBSIDIAN.md`。本 downstream terminal repo 不再建立新的 `template/`，只維護 root 文件與 `OBSIDIAN.md`。

詳見 docs/orchestration-workflow.md §9

## 常用查詢

| 需求 | 查看 |
|---|---|
| Artifact schema | docs/artifact_schema.md §5 |
| Premortem 規則 | docs/premortem_rules.md |
| Guard validator 觸發點 | .github/memory-bank/workflow-gates.md |
| Artifact 異常模式 | .github/memory-bank/artifact-rules.md |
| Prompt patterns | .github/memory-bank/prompt-patterns.md |
| Project facts（tech stack、deployment） | .github/memory-bank/project-facts.md |
| Remember Capture | .github/prompts/remember-capture.prompt.md |
| 上下文收斂工具 | .github/prompts/pack-context.prompt.md |

## 禁止項

- 🚫 不依賴 memory 或 session
- 🚫 在工作區外建檔案
- 🚫 中間筆記或 scratch files
- 🚫 不驗證就標記完成
- 🚫 在 prompt 寫密碼、token、個人資訊

---

更多細節見相關 docs 檔。
