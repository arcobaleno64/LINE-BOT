# RACI Matrix

> 本檔由 `docs/subagent_roles.md` §2 拆分而來；RACI 與 agent capability 矩陣集中於此。

## 2. 角色總表

| 角色 | 類型 | R (主執行) | A (最終問責) | C (諮詢) | I (通知) | 主要輸入 | 主要輸出 |
|---|---|---|---|---|---|---|---|
| Claude Code | 主控代理 | task / plan / decision / status | task / plan / verify / decision / status / improvement | research / code / verify | -- | 全部合法 artifacts | task, plan, verify, decision, status |
| Gemini CLI | 研究 + memory curator | research / Tavily Cache / Remember Capture draft | -- (Claude A) | task | closure events | task, 研究相關文件, memory-bank 讀取範圍 | research, Tavily Cache draft, Remember Capture draft |
| Codex CLI | 實作主代理 | code | -- (Claude A) | plan / research | -- | task, research, plan | code |
| Implementer | Codex subagent | code (實檔修改) | -- (Codex/Claude A) | plan | -- | task, plan, research | code |
| Tester | Codex subagent | test | -- (Codex/Claude A) | code | -- | task, plan, code | test |
| Verifier | Codex subagent 或 Claude 控制下代理 | verify | -- (Claude A) | code / test | -- | task, code, test | verify |
| Reviewer | Codex subagent | review notes | -- (Claude A) | plan / code | -- | task, plan, code | review 摘要或 decision 建議 |
| Codex Reviewer (Council) | Codex subagent (Council) | review notes (3 model votes) | Claude（triage） | plan / code / git diff | -- | git diff | `artifacts/reviews/<timestamp>-<model>.md` |

註：若你想維持最小集合，可先不建立獨立 review artifact，而把 reviewer 結果納入 decision log 或 verify artifact 的 evidence 區段。

### 2.1 TAO Trace 必要程度（執行層）

每位 subagent 在 dispatch 時須依下表決定是否填寫 TAO Trace（Thought-Action-Observation 微循環紀錄）。完整 schema 與 mismatch 處理見 [docs/agentic_execution_layer.md](agentic_execution_layer.md)。

| 角色 | TAO Trace 必要程度 | 觸發門檻 | 落點 artifact |
|---|---|---|---|
| **Implementer** | 必填 | task risk ≥ 3（plan `## Risks` 任一條 `Severity: blocking`） | code artifact `## TAO Trace` |
| **Verifier** | 必填 | task risk ≥ 3 | verify artifact `## TAO Trace` |
| **Tester** | 建議 | 任意；risk ≥ 3 強烈建議 | test artifact 或 code artifact `## TAO Trace` |
| **Reviewer** | 建議 | 任意 | verify artifact 或 decision artifact `## TAO Trace` |
| **Memory Curator (Gemini)** | 免 | -- | -- (Curator 之內隱循環已由 [`.github/prompts/remember-capture.prompt.md`](../.github/prompts/remember-capture.prompt.md) 規範) |

**Lightweight 任務、risk ≤ 2 之微改動、純文件變更**：TAO Trace 全部可省，artifact 對應欄位寫 `None`。

**Mismatch 處理（Observation 與 Thought 預期不符）**：subagent 須產 `Observation: mismatch — <對比>`，並設 `Next-Step Decision: halt`。不得自行 retry 或繼續，回管理層由 Claude 決定是否 escalate 至 mini-PDCA 子循環。詳見 [docs/agentic_execution_layer.md §3](agentic_execution_layer.md)。
