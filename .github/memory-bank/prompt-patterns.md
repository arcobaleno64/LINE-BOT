# Prompt Patterns — 本 Repo 的寫作範式

**Reference**: AGENTS.md, BOOTSTRAP_PROMPT.md  
**Last Updated**: 2026-04-24 +08:00

## Agent Dispatch Pattern

派發子代理時使用的 prompt 結構。每個 dispatch 都要嵌入對應 agent 的規則摘要。

### To Gemini (Research Agent / Memory Curator)

```
你是 research agent。任務：【describe】
範圍：【問題範圍】
模式：【research | Tavily-assisted research | Memory Bank Curator draft】
要求：
1. 找至少 2 個權威來源
2. 每個源都要 URL + 120 字摘述
3. 最後給 comparative analysis（how they differ）
4. 若啟用 Tavily-assisted research，先確認本機 Tavily CLI 可用；記錄 command、query、retrieved date、URLs；不可用時回報 blocked / UNVERIFIED
5. 若是 Memory Bank Curator，只能產出 Remember Capture draft，不得寫入 `.github/memory-bank/`
GEMINI.md 的規則：【embed key rules】
完成後輸出 Research artifact（see docs/schemas/artifact-spec-research.md §5.2）
```

Tavily 結果只能放在 research artifact draft 的 `## Tavily Cache` / `## Source Cache`；是否沉澱到 memory-bank 必須由 Claude/Codex 透過 Remember Capture 篩選。memory-bank 只收長期、可追蹤、非顯而易見、非短期排障且未過時的知識。

### To Codex (Implementation Agent)

```
你是 implementation agent。任務：【describe】
Routing inputs:
- Task Type: 【docs/code/test/workflow/security】
- Risk Score: 【0-10】
- Context Cost: 【S/M/L】
Task Scale: 【tiny | docs-only | standard | high-risk | cross-module | critical | security | architecture】
Model / Effort: 【model】 / 【reasoning effort】
先決條件：
- 已有 Plan artifact（位於 artifacts/plans/TASK-XXX.plan.md）
- Premortem 已完成，風險 R1-R4 都在
- 環境變數已設定（列舉必要的）
要求：
1. 實作【功能描述】
2. 通過【測試條件】
3. 輸出 Code artifact（see docs/schemas/artifact-spec-code.md §5.4），必須含 Execution Profile 與 Subagent Plan
4. 輸出 Verify artifact with Build Guarantee
5. 若使用 Codex subagent，scope check、test planning、implementation、regression verification 必須分工清楚；未使用時寫 `Subagent Plan: None` 與理由
範圍：【明確不做什麼】
CODEX.md 的規則：【embed key rules】
```

## Artifact Output Pattern

Artifact 範本。Status 值必須符合 docs/artifact_schema.md §4.2 的合法清單。

### Research Artifact Header

```markdown
# Research -- TASK-XXX
## Objective
【一句話：要回答什麼問題】
## Sources
- Source 1: Title | URL | 【120-word summary】
- Source 2: ...
## Analysis
【Comparative synthesis】
## Metadata
- Task ID: TASK-XXX
- Status: ready
- Last Updated: 2026-04-16T14:30:00+08:00
```

Plan artifact 範本以 `docs/artifact_schema.md` §5.3 為準；風險必須有 Risk / Trigger / Detection / Mitigation / Severity。

## 常見模式

Guard validator 或流程中常見的結構化輸出範本。

### 缺少前置 Artifact

當 research / plan / code 缺失時，停下並報告：

```
BLOCKED: TASK-XXX cannot proceed.
Missing artifact: artifacts/plans/TASK-XXX.plan.md
Required for: coding phase gate check
Action: Complete planning phase first (see docs/schemas/artifact-spec-plan.md §5.3)
```

### Scope 漂移

當 code.Files Changed 不是 plan.Files Likely Affected 的子集時：

```
SCOPE DRIFT DETECTED: TASK-XXX
Planned: [src/foo.py, tests/]
Changed: [src/foo.py, src/bar.py, src/config.py]
Decision:
Option A: Revert bar.py / config.py
Option B: Create decision artifact with Guard Exception
Option C: Abort and refile as sub-task
```
## 禁止項

- Artifact 不按 schema 寫 — see docs/artifact_schema.md §5
- 使用非標準 status 值 — see docs/artifact_schema.md §4.2
- Metadata 缺時間戳（ISO 8601 +08:00）或 owner
- Risk 區段只寫結論，不寫 trigger / detection / mitigation
