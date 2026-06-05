# Orchestration Workflow

> 本檔由 `docs/orchestration.md` §3+ 拆分而來；流程圖、gate 決策樹、PDCA 階段細節集中於此。系統提示骨幹仍在原檔。

## 3. 角色分工

### 3.1 Claude Code

Claude Code 是主控代理，負責：

- 讀取與比對 artifacts
- 任務理解與拆解
- 判定目前狀態與缺失 artifacts
- 建立 task artifact
- 建立或更新 plan artifact
- 建立或更新 status artifact
- 委派 Gemini CLI 與 Codex CLI
- 在 closure 階段委派 Gemini 產生 Memory Bank Curator draft，並驗收後續 memory-bank 寫入
- 驗收 code artifact、test artifact、verify artifact
- 記錄 decision log
- 輸出風險、阻塞與下一步

Claude Code 不得：

- 未經 research artifact 就對外部知識下定論
- 未經 plan artifact 就要求 Codex 修改程式
- 以模糊語句宣稱完成，例如「應該已完成」「看起來可行」
- 把長測試 log 或大量命令輸出塞進主 thread

### 3.2 Gemini CLI

Gemini CLI 是研究代理與 read-only memory curator，負責：

- 查詢官方文件
- 比對版本差異
- 蒐集規格與限制
- 分析錯誤背景
- 產出 research artifact
- 在被授權時使用本機 Tavily CLI 輔助 research，產出 `## Tavily Cache` / `## Source Cache` draft
- 在 Memory Bank Curator 模式下，產出 `Remember Capture` draft

Gemini CLI 不得：

- 直接修改程式碼
- 自行決定需求範圍
- 取代 plan artifact
- 在沒有 task artifact 的情況下自由研究
- 直接修改 `.github/memory-bank/` 或宣告最終寫入決策
- 在 Tavily CLI 不可用時捏造來源或把未驗證內容放入 Confirmed Facts

### 3.3 Codex CLI

Codex CLI 是實作代理，負責：

- 根據 task artifact 與已核准 plan artifact 修改程式
- 補齊或調整測試
- 產出 code artifact
- 視需要由 subagents 進行測試、驗證、review
- 依 task scale 選擇 model / reasoning effort，並在 code artifact 記錄 `Execution Profile` 與 `Subagent Plan`

Codex CLI 不得：

- 在沒有 plan artifact 的情況下直接大範圍改碼
- 自行擴大需求範圍
- 直接改動未列入 plan 的高風險區塊
- 把未驗證結論包裝成完成

## 4. 標準流程

### Stage 1. Intake

1. 讀取現有 artifacts。
2. 若沒有 task artifact，先建立 task artifact，並明確填寫 `Assurance Level` 與 `Project Adapter`。
3. 建立或更新 status artifact。
4. 判定目前狀態與缺失 artifacts。

### Stage 2. Research

若任務需要外部知識或規格依據：

1. 建立 Gemini 任務單。
2. 要求 Gemini CLI 產出 research artifact。
3. 驗收 research artifact 是否完整。
4. 只有 research 狀態合法，才可進入 planning。

### Stage 3. Planning

1. 依 task artifact 與 research artifact 建立 plan artifact。
2. 明確列出：
   - 修改範圍
   - 影響檔案
   - 風險
   - 非本次範圍
   - 驗收條件
   - verification obligations
3. 更新 status artifact 為 planned。

### Stage 4. Coding

1. 只有在 plan artifact 狀態為 ready 或 approved 時，才可分派 Codex CLI。
2. 派發 subagent 前，可執行 `python artifacts/scripts/discover_templates.py --agent "Codex CLI" --stage coding` 查詢當前階段可用的 templates。
3. Claude dispatch 必須包含 task type、risk score、context cost 與 model/effort policy。
4. Codex CLI 根據 plan artifact 實作。
5. 產出 code artifact，包含 `Execution Profile` 與 `Subagent Plan`。
6. 若需測試與驗證，可由 subagents 依序或平行產出 test / review / verify 相關 artifacts。

### Stage 5. Verification

1. 讀取 task artifact、plan artifact、code artifact、test artifact。
2. 逐條對照 acceptance criteria。
3. verify checklist item 必須使用 `verified` / `unverified` / `unverifiable` / `deferred`。
4. 若 item 不是 `verified`，必須補 `decision_ref` 或 `reason_code`。
5. 建立 verify artifact，並填寫 `Overall Maturity` 與 `Deferred Items`。
6. 若 verify artifact 未通過，不得標記 done。

### Stage 6. Closure

1. 更新 status artifact。
2. 補齊 decision log。
3. 若任務已進入 `verifying` 或 `done`，補一份短 improvement review：
   - 新增或更新 `artifacts/improvement/TASK-XXX.improvement.md`
   - 聚焦實際流程、冗餘步驟、易錯點、流程落差、template / prompt / guard 修正候選、以及下次預設
   - 若該任務曾經 `blocked`，仍須保留 Gate E / PDCA 所需欄位
4. 若有長期可重用 lesson，Claude 可派 Gemini 以 Memory Bank Curator 模式產生 `Remember Capture` draft；Gemini 只做 read-only 分類、查重與來源驗證。
5. 若 draft 需要寫入 `.github/memory-bank/`，由 Claude/Codex 在明確 write scope 下修改，並由 Claude 最終驗收。
6. 更新 `artifacts/improvement/PROCESS_LEDGER.md`，每個 task 只寫一行摘要，作為冷啟動入口。
7. 明確標記：
   - 已完成
   - 未完成
   - 風險
   - 待確認事項
   - 下一步

## 5. Gate 規則

以下 gate 為強制規則：

### Gate A: Research Gate

若任務涉及外部知識，沒有合法 research artifact，不得進入 planning 或 coding。

### Gate B: Planning Gate

沒有合法 plan artifact，不得進入 coding。

### Gate C: Code Gate

沒有 code artifact，不得宣告 implementation 完成。

### Gate D: Verification Gate

沒有 verify artifact，或 verify artifact 結果非 pass，不得將 status 設為 done。

### 5.1 示範任務流程（Code artifact 節錄）

若示範任務流程需要展示 Code artifact，`## Mapping To Plan` 應符合 Sprint 1 A3 格式：

```md
## Mapping To Plan
- plan_item: 1.1, status: done, evidence: "updated BOOTSTRAP_PROMPT.md with Sources example"
- plan_item: 1.2, status: done, evidence: "synced docs/orchestration.md sample to template copy"
- plan_item: 1.3, status: skipped, evidence: "not required by plan"
```

重點：

- 每行都必須包含 `plan_item`、`status`、`evidence`
- `status` 只能是 `done`、`partial`、`skipped`
- `evidence` 必須是可快速核對的短描述，而不是 raw log

## 6. Context Hygiene 規則

為降低上下文壓縮與污染風險，主 thread 只保留：

- 任務目標
- 關鍵決策
- 狀態變化
- 風險與阻塞
- 下一步

禁止在主 thread 大量貼上：

- 完整測試 log
- 大段 CLI output
- 大量 stack trace
- 長篇 diff
- 重複研究過程

上述內容必須落地成檔案，只在摘要中引用結論與必要證據。

## 7. 標準輸出格式

每次回應必須使用下列結構：

1. 目前可見 artifacts
2. 當前任務狀態
3. 缺失 artifacts
4. 下一個合法步驟
5. 要分派給哪個 agent
6. 該 agent 應產出的 artifact
7. 驗收條件
8. 風險與阻塞事項

若任務已進入 closure，則補充：

9. 已完成事項
10. 未完成事項
11. Decision log 是否已更新

## 8. 錯誤處理規則

若發生以下情況，必須停止推進並回報：

- 上下游 artifact 互相矛盾
- 缺少必要 artifact
- state transition 不合法
- research 結論不足以支撐 implementation
- Codex 修改超出 plan 範圍
- 驗收未通過

停止推進時必須明確輸出：

- 阻塞原因
- 缺什麼 artifact
- 應由哪個 agent 補件
- 補件完成前不得做的事

## 9. Sync Contract

此 workflow 同時支援兩種 repo mode，由 root 是否存在 `.council-forge-source-repo` 判定：

- source template repo：保留 `root ↔ template ↔ Obsidian` 同步契約，作為範本來源庫。
- downstream terminal repo：由 `template/` 複製出去的新專案；不再建立新的 `template/`，只維護 root 文件與 `OBSIDIAN.md`。

### 9.1 觸發條件

以下任一檔案被修改時，觸發 sync contract 檢查：

- 入口檔：`START_HERE.md`、`CLAUDE.md`、`GEMINI.md`、`CODEX.md`、`AGENTS.md`
- Obsidian 入口：`OBSIDIAN.md`
- 參考文件：`docs/*.md`（本檔案含在內）
- 驗證器：`artifacts/scripts/guard_status_validator.py`、`artifacts/scripts/guard_contract_validator.py`
- 啟動/導覽檔：`BOOTSTRAP_PROMPT.md`、`README.md`、`README.zh-TW.md`

### 9.2 Source Template Repo 流程

當 repo 含 `.council-forge-source-repo` 時，workflow 變更必須：

1. **泛化**：將專案特定引用替換為通用描述或 placeholder。
   - 具體 TASK ID / decision 引用 → 通用描述
   - 專案名稱 → `LINE-BOT`
   - Repo 名稱 → `line-bot`
   - 上游組織 → `arcobaleno64`
2. **同步**：將泛化後的內容寫入 `template/` 對應路徑，並同步更新 `OBSIDIAN.md` 與 `template/OBSIDIAN.md`。
3. **README / Obsidian 判定**：若修改涉及檔案結構、workflow 階段、gate、agent 角色或新概念，必須同步更新 `START_HERE.md`、雙語 README 與 Obsidian 入口的 root/template 對應版本。
4. **Contract 驗證**：執行 `python artifacts/scripts/guard_contract_validator.py`；`--check-readme` 會同時檢查 root 與 template 的 README 結構。
5. **推送**：將 source repo 與 `template/` 變更一起提交與推送。

### 9.3 Downstream Terminal Repo 流程

當 repo **不含** `.council-forge-source-repo` 時，workflow 變更必須：

1. 僅維護 root 文件與 `OBSIDIAN.md`。
2. 不得再建立新的 `template/`，也不得要求 nested template sync。
3. 執行 `python artifacts/scripts/guard_contract_validator.py`；此模式只檢查 root / Obsidian / repository profile 與 Gemini model policy。
4. 若修改 `CLAUDE.md`、`GEMINI.md`、`CODEX.md` 等 prompt 入口，仍必須同步更新 `artifacts/scripts/drills/prompt_regression_cases.json`。

### 9.4 Gemini Model Policy

active workflow files 中只允許以下 Gemini allowlist：

- `gemini-3.1-flash-lite-preview`
- `gemini-3-flash-preview`
- `gemini-3.1-pro-preview`

auto-fallback 僅限前兩個 flash tiers；`gemini-3.1-pro-preview` 保留為 allowlist 內的 ad-hoc dispatch。

`guard_contract_validator.py` 會掃描 `CLAUDE.md`、`BOOTSTRAP_PROMPT.md`、`docs/subagent_roles.md`、`Invoke-GeminiAgent.ps1` 及其 template 對應檔。任何 `2.x` 或未列入 allowlist 的型號都視為 contract violation。

### 9.5 責任歸屬

sync contract 由 **Orchestrator（Claude Code）** 負責。Gemini CLI 與 Codex CLI 不直接決定 repo mode，也不應自行建立 downstream repo 的 nested `template/`。

### 9.6 同步責任邊界

以下矩陣定義 source template repo 與 downstream terminal repo 的同步策略。`guard_contract_validator.py` 是程式化 source of truth。

#### Tier 1: Exact Sync（source mode 強制）

此類檔案在 source template repo 的 root 與 template 之間必須**內容完全一致**（扣除 placeholder 泛化後）。downstream terminal repo 不檢查這一層。

| 檔案 | 說明 |
|---|---|
| `START_HERE.md` | 新使用者 3 檔導覽入口 |
| `requirements-dev.txt` | 本地開發 / 測試依賴契約 |
| `AGENTS.md` | 文件索引 |
| `BOOTSTRAP_PROMPT.md` | 新專案啟動範本 |
| `CODEX.md`、`GEMINI.md` | Agent 入口檔 |
| `docs/*.md`（10 個核心規範） | 流程規範文件 |
| `artifacts/scripts/guard_status_validator.py` | 狀態驗證器 |
| `artifacts/scripts/guard_contract_validator.py` | 同步守護器 |
| `artifacts/scripts/run_red_team_suite.py` | 紅隊演練 |
| `artifacts/scripts/prompt_regression_validator.py` | Prompt 回歸測試 |
| `artifacts/scripts/build_decision_registry.py` | Decision registry 建構 |
| `artifacts/scripts/update_repository_profile.py` | Repository profile 管理 |
| `artifacts/scripts/workflow_constants.py` | 共用常數 |
| `artifacts/scripts/drills/prompt_regression_cases.json` | 回歸測試案例 |

#### Tier 2: Mode-Specific Prompt Entry

此類檔案允許 root 與 template 依 repo mode 有不同 wording，但必須守住各自的 required phrases。

| 檔案 | Source Template Repo | Downstream Terminal Repo |
|---|---|---|
| `CLAUDE.md` | 說明 `.council-forge-source-repo`、template sync、placeholder 泛化 | 說明 downstream terminal repo、不得再建立新的 `template/`、只維護 root 文件 |

#### Tier 3: Section-Contract Sync

README / OBSIDIAN 不要求逐字一致，但必須符合固定 H2 順序，且只有指定 section 可以承載必要語句與 mode-specific 禁字檢查。

| 檔案 | Source Template Repo | Downstream Terminal Repo |
|---|---|---|
| `OBSIDIAN.md` / `template/OBSIDIAN.md` | 固定 H2 順序 + source three-way contract | 固定 H2 順序 + root-only maintenance contract |
| `README.md` / `README.zh-TW.md` | 固定 H2 順序 + source repo / template 發佈說明 | 固定 H2 順序 + downstream root-only 維護說明 |

#### Tier 4: Manual Sync（無自動化強制）

此類檔案存在於 root 與 template 中，但不在 exact-sync 清單內。source mode 建議保持一致；downstream mode 視專案需求自行維護。

| 檔案 | Root 用途 | Template 用途 | 同步建議 |
|---|---|---|---|
| `.gitignore` | 專案 ignore 規則 | 範本 ignore 規則 | source mode 應保持一致 |
| `.coveragerc` | 測試 coverage 設定 | 範本 coverage 設定 | source mode 應保持一致 |
| `requirements.txt` | Python 依賴聲明 | 範本依賴聲明 | source mode 應保持一致 |
| `LICENSE` | 授權 | 範本授權 | source mode 應保持一致 |
| `.github/workflows/workflow-guards.yml` | CI pipeline | 範本 CI pipeline | source mode 應保持一致 |
| `.github/agents/*.agent.md` | GitHub Agents 設定 | 範本 Agents 設定 | source mode 應保持一致 |
| `.github/repository-profile.json` | 專案 profile（有獨立驗證） | 範本 profile | source mode 獨立驗證；downstream 只需 root |
| `artifacts/scripts/*.py`（非 Tier 1） | 輔助腳本 | 範本輔助腳本 | source mode 應保持一致 |
| `artifacts/scripts/*.ps1` | PowerShell wrapper | 範本 wrapper | source mode 應保持一致 |
| `docs/templates/*/TEMPLATE.md` | Subagent 範本 | 範本 subagent 範本 | source mode 應保持一致 |

#### Tier 5: Project-Specific（不同步）

此類檔案屬於任務執行或本地環境內容，不在 sync contract 內。

| 檔案 | 說明 |
|---|---|
| `artifacts/(tasks\|research\|plans\|code\|verify\|status\|decisions\|improvement\|red_team)/*` | 專案執行 artifacts |
| `docs/repo_structure_workflow_maturity_assessment.md` | 專案評估（template 可為空白範本） |
| `docs/red_team_scorecard.generated.md` | 生成的計分卡 |
| `artifacts/scripts/test_guard_units.py` | Unit test（測試框架函式） |
| `.env`、`.vscode/settings.json`、`.claude/settings.local.json` | 本地環境設定 |
| `temp_test.ps1`、`test_e2e.ps1` | 暫存測試腳本 |
| `external/*` | 外部 repo |

## 10. README / Repository Profile Contract

### 10.1 新專案啟動規則

當新專案透過 source repo 的 `template/` 初始化後，產出的 repo 立即視為 downstream terminal repo，必須：

1. 依範本 README 結構建立 `README.md` 與 `README.zh-TW.md`
2. 僅調整章節內容，不改變 H2 標題與順序
3. 若結構不適用當前專案，必須記錄於 decision artifact
4. 不再建立新的 `template/`

### 10.2 `--check-readme` 模式

`guard_contract_validator.py --check-readme` 的檢查邏輯：

1. 所有 repo mode 都檢查 root 的 `README.md` / `README.zh-TW.md` H2 數量是否一致，且 root README section contract 必須成立
2. source template repo 另外檢查 `template/README.md` / `template/README.zh-TW.md`
3. source template repo 若缺 template README，或高風險 sections 出現 source/downstream 混線 wording，視為 contract violation

### 10.3 邊界內容定義

- 「邊界內容」= 所有 H2 標題及其直屬段落
- 可調整部分：文字用語、代碼範例、連結、專案特定細節
- 不可調整部分：H2 標題名稱、表格結構、必填欄位名稱

### 10.4 中英文版本的對應規則

- `README.zh-TW.md` 與 `README.md` 必須保持結構一致
- 翻譯差異允許，但標題與組織必須對應
- 若中文版有結構差異，必須記錄同一個 decision waiver

### 10.5 Repository About / Topics Guard

repository profile 由 `guard_contract_validator.py` 驗證：

- source template repo：`/.github/repository-profile.json` 與 `/template/.github/repository-profile.json`
- downstream terminal repo：只要求 `/.github/repository-profile.json`

規則：

1. 必須包含 `about`（字串，80-200 字元）與 `topics`（陣列，6-12 個）
2. `topics` 必須使用 lowercase-kebab-case，且不可重複
3. `topics` 必須至少包含：
   - `multi-agent`
   - `developer-tools`
   - `workflow-template`
   - `artifact-first`
   - `gate-guarded`
   - `premortem`

## 11. 最終原則

- 先看 artifact，再做判斷
- 沒有 artifact，就沒有完成
- 沒有驗收，就沒有 done
- agent 可替換，artifact contract 不可破壞
- 對話可以協助理解，但不能取代檔案狀態

## 12. Decision Waiver

`Decision Waiver` 放在 `artifacts/status/*.status.json` 的 `decision_waivers` 欄位中，單筆格式如下：

```json
{
  "gate": "Gate_B",
  "reason": "temporary waiver reason",
  "approver": "human approver",
  "expires": "2026-04-15T23:59:59+08:00"
}
```

規則：

- `gate`、`reason`、`approver`、`expires` 四欄缺一不可，否則 `guard_status_validator.py` 必須拒絕。
- `gate` 只代表特定 Gate 的豁免，不可視為 blanket override。
- `expires` 必須是 `Asia/Taipei` 的 ISO 8601 `+08:00`；一旦過期，guard 必須輸出 `waiver expired` 並視為失敗。
- 有效 waiver 只會讓 validator 對指定 gate 的失敗退出碼變為 `0`，並標記 `[WAIVER ACTIVE gate=N]`。

## 13. Cross-Repository Collaboration

本節定義在多倉庫環境中（本地 fork + upstream 原始庫）進行協作時的命名慣例、同步規則、衝突處理策略與 PR 策略。此節補充 `CLAUDE.md` 中 `external/line-bot/` 與 `external/line-bot-upstream-pr/` 的工作目錄定義。

### 13.1 Remote 命名慣例

| Remote 名稱 | 指向 | 說明 |
|---|---|---|
| `origin` | fork（個人或組織 fork）| 日常推送目標 |
| `upstream` | 原始庫（上游）| 只讀取、不直接推送 |

所有 agent 必須使用此命名約定；若 remote 設定不符，必須 STOP 並記錄於 decision artifact。

### 13.2 Upstream Pinning

- 每次建立 upstream PR 分支前，必須執行：
  ```bash
  git fetch upstream
  git reset --hard upstream/<default-branch>
  ```
- 禁止將本地 feature commit、experiment commit 或 hotfix commit 混入 upstream PR 分支。
- 若無法確保分支乾淨（例如 git worktree 含未提交變更），必須 STOP，並在 decision artifact 記錄原因。
- 此規則由 Orchestrator（Claude Code）負責執行；Codex CLI 不得自行決定 upstream PR 分支狀態。

### 13.3 衝突處理策略

| 衝突類型 | 處理策略 | 決策者 |
|---|---|---|
| schema 衝突 | 建立 decision artifact，擱置直到明確確認後方可繼續 | task owner |
| script 衝突 | local 版本優先；upstream PR 分支使用 upstream 版本 | Claude Code |
| artifact 衝突 | 不得合併；必須分別建立 PR，並各自追蹤 artifact chain | task owner |

衝突必須在推進任何 artifact state transition 之前記錄於 decision artifact。

### 13.4 PR 策略

- 只向 upstream 送符合 upstream 品質標準的變更（通過 upstream 測試、不含專案特定邏輯、無本地 feature code）。
- 本地 experiments、工具腳本、專案特定 artifacts 絕不進入 upstream PR 分支（`external/line-bot-upstream-pr/`）。
- upstream PR 必須可獨立 review，不依賴本地 fork 的任何未合併變更。
- 送出 upstream PR 前，必須確認 `external/line-bot-upstream-pr/` 的 commit history 與 upstream 主分支完全一致，除了本次 PR 的變更。

## 14. Security Cadence

Security / governance cadence 之單一真實來源為 [`docs/security_cadence.md`](security_cadence.md)。彙整三層 cadence：

- **Weekly Codex Council audit**：每週對 master 過去 7 commits 之合併 diff 執行 Council-of-models review（三 tier `gpt-5.4-mini` / `gpt-5.4` / `gpt-5.5`）；workflow source 為 `.github/workflows/weekly-council-audit.yml`，driver script 為 `artifacts/scripts/Invoke-CodexReview.ps1`。
- **Quarterly threat model**：每季首日由 `.github/workflows/quarterly-threat-model.yml` 自動建 reminder issue；exercise artifact 由 user 依 `docs/red_team_runbook.md` 產出。
- **Continuous SAST**：pip-audit / repo-secrets-scan / repo-static-scan 由 `.github/workflows/security-scan.yml` 於 PR / push 觸發。

cadence drift recovery 流程詳見 cadence doc 之同名段。
