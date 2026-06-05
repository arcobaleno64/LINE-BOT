# Bootstrap Prompt — 新專案開局範本

> 將以下內容複製到新的 Claude Code 對話串的第一則訊息。
> 用你的專案資訊替換 `【...】` 區塊後送出。

---

```
我要使用 artifact-first multi-agent workflow 開始一個新專案。

## 1. 專案資訊

- 專案名稱：【填入專案名稱，例如 MyApp】
- 專案根目錄：【填入絕對路徑，例如 C:\Users\me\Projects\MyApp】
- 專案簡述：【一句話描述專案目的】
- 主要語言/框架：【例如 C# / .NET 8 / UWP、Python / FastAPI、TypeScript / Next.js】
- 版控：Git（已初始化 / 尚未初始化）

## 2. 上游 Fork 模式（若無 fork 可刪除此段）

- Upstream repo：【例如 github.com/original-author/repo-name】
- 我的 fork：【例如 github.com/myuser/repo-name】
- GitHub CLI 帳號：【例如 myuser】

## 3. 範本來源

Workflow template 位於：【填入 artifact-harness repo clone 路徑，或直接在專案目錄中 clone】
請從該目錄複製完整架構到專案根目錄，然後：
1. 替換 CLAUDE.md 中的 placeholder（LINE-BOT, line-bot, arcobaleno64）
2. 若無 fork 模式，移除 CLAUDE.md 的 "Repository boundaries" 區段
2a. 複製完成後，此 repo 視為 downstream terminal repo，不需要也不得再產生新的 `template/`
2b. 小任務可用 `python artifacts/scripts/guard_status_validator.py --task-id TASK-900 --auto-classify` 試跑判定流程。
   當 task 含 `lightweight: true`，或沒有 plan artifact 且仍在 `drafted` / `researched`，guard 會走 lightweight gate。
   一旦偵測 `premortem:` 或 plan 的 `## Risks` 非空，guard 會自動升級回 full gate。
3. 更新 repository About/topics profile：
  - 執行 `python artifacts/scripts/update_repository_profile.py --project-name "【專案名稱】" --project-summary "【專案簡述】"`
  - 若需要客製 topics，可加 `--topics "multi-agent,developer-tools,workflow-template,..."`
4. **新增**：確認 README.md 與 README.zh-TW.md 版本都存在且結構遵循範本 README 結構
  - 執行 `python artifacts/scripts/guard_contract_validator.py --check-readme` 確認 README 結構合規
5. 執行 `python artifacts/scripts/guard_status_validator.py --task-id TASK-900` 確認 [OK]
6. 執行 `python artifacts/scripts/guard_contract_validator.py` 確認 contract 未漂移
  - source template repo（含 `.council-forge-source-repo`）會檢查 root / template / Obsidian / repository profile
  - downstream terminal repo 只檢查 root / Obsidian / repository profile，不再要求 nested `template/`
7. 執行 `python artifacts/scripts/prompt_regression_validator.py --root .` 確認 Prompt regression 測例通過
8. 若要做完整流程壓力測試，可再執行 `python artifacts/scripts/run_red_team_suite.py --phase all`

## 4. Agent 配置

- Orchestrator：Claude Code（你；CLI-first，預設負責 orchestration、決策、驗收與最後整合）
- Research / Memory Curator agent：Gemini CLI
  - 模型：`gemini-3.1-flash-lite-preview`（預設），有問題時依序升級至 `gemini-3-flash-preview`、`gemini-3.1-pro-preview`（auto-fallback tier 3）
  - 只允許上述 allowlist，不得降回 2.x 或其他更舊模型
  - 認證方式：由 CLI 內部 OAuth 處理，不依賴 `GEMINI_API_KEY` 環境變數（若未登入請先執行 `gemini auth`）
  - 呼叫方式：gemini -m gemini-3.1-flash-lite-preview --approval-mode=yolo -p "<prompt>"
  - 入口檔：GEMINI.md（品質硬規則與 Memory Bank Curator draft-only 邊界已內嵌，不需額外載入）
- Tavily-assisted research：只有 dispatch 明確允許時才能由 Gemini 間接使用本機 Tavily CLI；需先確認 CLI 可用並記錄 command、query、retrieved date、URLs；不可用時標記 blocked / UNVERIFIED
- Implementation agent：Codex CLI（已規劃實作、測試補強、跨檔 workflow docs 預設交給 Codex）
  - 入口檔：CODEX.md
  - Task scale / model policy：`tiny` / `docs-only` → `gpt-5.4-mini` `high`；`standard`（文件中的 `standard implementation`）→ `gpt-5.4` `high`；`high-risk` / `cross-module` / `critical` / `security` / `architecture` → `gpt-5.5` `high`
  - Code artifact 必須記錄 `Execution Profile` 與 `Subagent Plan`

## 5. 工作規範

- 遵循 CLAUDE.md 的所有規則（artifact-first、gate-guarded、premortem）
- Claude Code 預設 CLI-first；只有明確 VS Code / Copilot 環境或任務本身涉及 VS Code / Copilot 設定時，才使用或建議 VS Code extension
- Routing 依 Task Type、Risk Score 0-10、Context Cost S/M/L 判斷；risk >= 3 或 context cost >= M 預設交給 Codex，research / spec comparison / Tavily-assisted research / Memory Bank Curator draft 預設交給 Gemini
- Claude 只在 scope 不明、角色衝突、decision、驗收、最後整合，或 risk <= 2 且 context cost = S 的極小變更時直接實作
- 文件按需載入：參考 AGENTS.md 的階段載入矩陣，不要一次讀完所有 docs/
- 每個 task 必須走完 Intake → Research → Planning → Coding → Verification 流程
- Research 外包 Gemini CLI 時，dispatch prompt 必須包含 GEMINI.md 的品質規則；Memory Bank Curator 外包 Gemini 時只能要求 read-only `Remember Capture` draft，不得要求其寫入 `.github/memory-bank/`
- Tavily 結果只能保存在 research artifact draft 的 `## Tavily Cache` / `## Source Cache`；是否寫入 `.github/memory-bank/` 必須再經 Remember Capture 與 Claude 驗收
- 進入 coding 前必須完成 premortem 分析（docs/premortem_rules.md）
- 完成後必須有 verify artifact 含 Build Guarantee
- source template repo 的 workflow 規則變更必須同步更新 `template/` 對應文件、`OBSIDIAN.md` 與 `template/OBSIDIAN.md`
- downstream terminal repo 的 workflow 規則變更只維護 root 文件與 `OBSIDIAN.md`
- 紅隊演練入口固定為 `docs/red_team_runbook.md`，重跑命令固定為 `python artifacts/scripts/run_red_team_suite.py`
- Prompt regression 固定命令為 `python artifacts/scripts/prompt_regression_validator.py --root .`
- 長期維護 Markdown 以繁體中文（臺灣）為主；命令、路徑、環境變數、schema literal 與 placeholder 保持英文

## 6. 第一個任務

【描述你的第一個任務，例如：】
TASK-001：【任務目標】
- 背景：【為什麼要做這件事】
- 預期產出：【具體要改什麼 / 做什麼】
- 驗收條件：【怎樣算完成】

請先執行 Intake（讀範本、建立 task artifact 和 status artifact），然後按流程推進。
```

---

## 使用說明

### 最小版（無 fork、無 Gemini）

如果專案不需要 fork 模式也不需要 Gemini，可以精簡為：

```
我要使用 artifact-first workflow 開始新專案。

專案：【名稱】，位於 【路徑】，使用 【語言/框架】。

範本來源：【填入 artifact-harness repo clone 路徑，或直接在專案目錄中 clone】
請複製範本到專案、移除 CLAUDE.md 的 fork 區段、確認它成為 downstream terminal repo、驗證 TASK-900，並執行 contract guard。

第一個任務：【描述】
```

### 構建你的第一個 Research artifact

若第一個 task 需要 Research，至少要讓 `## Sources` 符合 Sprint 1 A1 的最小格式：

```md
## Sources
[1] Example Org. "Primary spec." https://example.com/spec (2026-04-15 retrieved)
[2] Example Org. "Secondary reference." https://example.com/reference (2026-04-15 retrieved)
```

重點：

- 每筆都要有編號 `[N]`
- 必須同時包含 `Author/Org`、`"Title."`、`URL`、`(YYYY-MM-DD retrieved)`
- 至少 2 筆；缺少 `## Sources` 會被 `guard_status_validator.py` 直接擋下

### 注意事項

1. **範本路徑**：若 template 已搬移到其他位置，更新路徑即可。
2. **Gemini 認證**：Gemini CLI 使用 OAuth 登入，不需要 API Key。若未登入請先執行 `gemini auth`。
3. **第一個任務**：建議從一個小任務開始（例如 TASK-001: 確認 build 正常），驗證整個流程跑得通後再做大任務。
4. **Lightweight mode**：極小型任務可搭配 `guard_status_validator.py --auto-classify` 自動判定 lightweight / full gate。
