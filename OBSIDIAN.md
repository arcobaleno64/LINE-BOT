# Obsidian 入口筆記

本檔是此 vault 的 Markdown 文件入口，提供文件語言規範、閱讀順序與同步範圍摘要。完整 workflow 規則仍以 `START_HERE.md`、`AGENTS.md`、`CLAUDE.md` 與 `docs/` 內文件為準；任何 workflow 規則變更若未同步本檔，視為未完成。

## 文件語言規範

- 長期維護的 workflow、template 與入口類 Markdown 文件以繁體中文（臺灣）為主。
- 專有名詞、檔名、CLI 指令、環境變數、placeholder、schema literal、狀態值保留英文原字。
- 不得更動會被 agent、validator、腳本依賴的精確字串，例如 `## Metadata`、`Task ID`、`Artifact Type`、`Owner`、`Status`、`Last Updated`。
- 所有紀錄時間、`Last Updated` 與相關時間戳一律使用 `Asia/Taipei`，採 ISO 8601 並帶 `+08:00`。
- source template repo 中，root、`template/` 與 Obsidian 入口文件必須保持語義一致；由 `template/` 複製出的 downstream terminal repo 只維護 root 文件與 `OBSIDIAN.md`。

## 建議閱讀順序

1. `START_HERE.md`
2. `AGENTS.md`
3. `CLAUDE.md`
4. `docs/orchestration.md`
5. `docs/artifact_schema.md`
6. `BOOTSTRAP_PROMPT.md`
7. `docs/red_team_runbook.md`

## 導覽目錄

- `Start Here` → `START_HERE.md`
- `Lightweight Mode` → `docs/lightweight_mode_rules.md`
- `Workflow Orchestration` → `docs/orchestration.md`
- `Artifact Schema` → `docs/artifact_schema.md`
- `Process Ledger` → `artifacts/improvement/PROCESS_LEDGER.md`
- `Decision Registry` → `artifacts/registry/decision_registry.json`
- `Metrics` → `artifacts/metrics/`
- `Red Team Runbook` → `docs/red_team_runbook.md`
- `Workflow Orchestration Details` → `docs/orchestration-workflow.md`
- `RACI Matrix` → `docs/raci-matrix.md`
- `Artifact Specs` → `docs/schemas/`

## 同步範圍

- downstream terminal repo 只維護 root 文件與 `OBSIDIAN.md`。
- workflow 與 prompt 變更時，同步更新 root 文件與 prompt regression cases，且不再建立新的 `template/`。
- 不追溯改寫：`artifacts/` 內歷史任務記錄、`template/experiments/` 產出、外部 repo 與備份目錄中的 Markdown。

## Workflow 摘要

- Claude Code 預設 CLI-first，只有明確 VS Code / Copilot 情境或任務本身涉及 VS Code / Copilot 設定時，才使用或建議 VS Code extension。
- Agent routing 依 Task Type、Risk Score 0-10、Context Cost S/M/L 判斷；Claude 預設負責 orchestration、決策、驗收與最後整合，research / Tavily-assisted research / Memory Bank Curator draft 交給 Gemini，已規劃實作、測試補強與跨檔 workflow docs 交給 Codex。
- Research artifact 是 fact-only 契約，不得包含 `Recommendation` 或 solution 設計。
- Gemini 可在 Memory Bank Curator 模式下產生 `Remember Capture` draft；不得直接寫入 `.github/memory-bank/`，實際寫入由 Claude/Codex 執行並由 Claude 驗收。若使用 Tavily CLI，結果只保存在 research artifact draft 的 `## Tavily Cache` / `## Source Cache`。
- Codex CLI 是 implementation lead，可依 task scale 選 model / reasoning effort，且 code artifact 必須記錄 `Execution Profile` 與 `Subagent Plan`。
- task artifact 應明確宣告 `Assurance Level` 與 `Project Adapter`；status guard 會依 profile 計算最低 required artifacts。
- `blocked` 任務恢復前，必須先有 `Status: applied` 的 improvement artifact；status.json 新增 `Gate_E_passed`, `Gate_E_evidence`, `Gate_E_timestamp` 欄位追蹤 Gate E 驗證狀態。
- verify checklist item 現在使用 `verified` / `unverified` / `unverifiable` / `deferred`；若不是 `verified`，必須有 `decision_ref` 或 `reason_code`。
- 任務完成 `verify` 或 `done` 後，建議補一份短 improvement review，並更新 `artifacts/improvement/PROCESS_LEDGER.md`；冷啟動時先看 ledger，再看最近 3 份 improvement artifact。
- README 結構規則（見 `docs/orchestration.md` §10）：新專案必須同時產生 README.md 與 README.zh-TW.md，結構須遵循 template 並只調整內容；`guard_contract_validator.py` 提供 `--check-readme` 檢查合規性。
- plan/code scope drift 預設由 status guard 視為 fail；若 task 專屬檔案位於 dirty worktree，guard 會直接比對實際 git changed files；若 task 已 clean，則可用帶有 pinned commits、Changed Files Snapshot 與 Snapshot SHA256 的 `commit-range` diff evidence 重放 historical diff、在 git objects 遺失時改走 archive fallback，或用 `github-pr` evidence 透過 GitHub PR files API 重建 changed files。private / rate-limited GitHub 存取可使用 `GITHUB_TOKEN` / `GH_TOKEN`；只有附顯式 decision waiver 時才可使用 `--allow-scope-drift`，且僅能降級真正的 drift。
- `CLAUDE.md` / `GEMINI.md` / `CODEX.md` 有變更時，必須同步更新 `artifacts/scripts/drills/prompt_regression_cases.json`。
- 本 repo 不建立 nested `template/`。
- downstream terminal repo 的 workflow 規則變更後，只維護 root 文件與 `OBSIDIAN.md`，並通過 contract guard。
- 紅隊演練入口是 `docs/red_team_runbook.md`，重跑命令是 `python artifacts/scripts/run_red_team_suite.py`；靜態案例現新增邊界版本測試（如 RT-004B）確保防治邏輯合理。
- `python artifacts/scripts/run_red_team_suite.py` 預設會在每次執行後清理 `.codex-red-team/` fixture；若需要保留現場供除錯，可加上 `--keep-temp`。
- Prompt regression 固定入口是 `python artifacts/scripts/prompt_regression_validator.py --root .`，固定測例在 `artifacts/scripts/drills/prompt_regression_cases.json`。
- 固定 Prompt regression 測例目前涵蓋 artifact-only truth/completion、workflow sync completeness、research blocked preconditions、Gemini memory-bank curator read-only boundaries、Claude CLI-first routing boundaries、Codex model/effort selection 與 subagent separation、Gemini Tavily draft/cache-only boundaries、memory-bank librarian quality filter、implementation summary discipline、conflict-to-decision routing、decision schema integrity、external failure STOP、decision-gated scope waiver、historical diff evidence contract、pinned diff evidence integrity、GitHub provider-backed diff evidence 與 archive retention fallback。

## Decision Registry

- registry 檔案位置：`artifacts/registry/decision_registry.json`
- 重新產生命令：`python artifacts/scripts/build_decision_registry.py --root .`

| 欄位 | 說明 |
|---|---|
| `task_id` | decision artifact 對應的 task id，來自檔名 |
| `decision_type` | 優先讀 `## Decision Type` / `Type:`，缺少時 fallback 為 `guard_exception` 或 `general_decision` |
| `parse_status` | 欄位在 explicit + fallback 後是否完整，值為 `complete` 或 `partial` |
| `plan_refs` | 與 decision 關聯的 plan artifact 路徑陣列，格式固定為 repo-relative path |

## GitHub / Template 對應

- GitHub 對外入口：`START_HERE.md`、`README.md`、`README.zh-TW.md`
- 本 repo 不建立 nested `template/`
