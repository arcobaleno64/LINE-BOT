# Security Cadence

> 本檔為 council-forge repo 之 security / governance cadence 單一真實來源。彙整 weekly Codex Council audit、quarterly threat model、continuous SAST 三層 cadence 之 trigger / cadence / artifact destination / owner，並列 user-side setup steps 與 cadence drift recovery 流程。

任何修改 `.github/workflows/security-scan.yml`、`.github/workflows/quarterly-threat-model.yml`、`.github/workflows/weekly-council-audit.yml` 之 PR 應同步更新本檔對應段；反之亦然。doc-yml drift 屬 governance risk（per `artifacts/plans/TASK-1058.plan.md` §Risks R4 + `artifacts/plans/TASK-1063.plan.md` §Risks R4），於 weekly Codex Council audit 之 doc-sync 維度被監測。

## Weekly Codex Council Audit

| 欄位 | 內容 |
|---|---|
| Trigger | `.github/workflows/weekly-council-audit.yml`（`on.schedule.cron: '0 18 * * 0'` + `on.workflow_dispatch`） |
| Cadence | 每週 1 次（Sunday 18:00 UTC = 台灣時間週一 02:00） |
| Artifact Destination | `artifacts/reviews/weekly-<YYYY-MM-DD>/<timestamp>-<safe-model>.md`（per Council member 一檔），於 `claude/weekly-audit-<YYYY-MM-DD>` branch 經 PR 合入 master |
| Owner | CI bot (`claude-routine[bot]`) + PR reviewer |
| Source Workflow | `.github/workflows/weekly-council-audit.yml` |
| Source Script | `artifacts/scripts/Invoke-CodexReview.ps1`（三 tier `gpt-5.4-mini` / `gpt-5.4` / `gpt-5.5`，`ReasoningEffort=high`，wrapper line 55 default；workflow 不傳 `-CouncilModels` 依賴 default） |
| Diff Window | master 過去 7 commits 之合併 diff（workflow 採 `git reset --soft HEAD~7` + `-DiffSource staged` 變通；wrapper API 限制詳見 `artifacts/plans/TASK-1063.plan.md` §S1） |
| Token Cost | per run ≈ 3 tier × 7 commits 合併 diff prompt size；具體 USD 由首次跑後 review artifact 之 `prompt_size` frontmatter 校。token quota 不足或 rate-limit 觸發時，wrapper 之 best-effort capture 仍 commit partial review，PR 仍開（per workflow `Run council review` step 之 `continue-on-error: true`） |
| Account Tier | OPENAI_API_KEY 由 user 帳戶自管；workflow 不檢 plan tier；首次跑後 user 視 token 用量決是否切單 tier 模式（屬 future task） |

review 涵蓋 master 過去 7 commits 合併 diff 之 5 維度 risk tagging（severity / location / issue / suggested_fix / rationale，per `Invoke-CodexReview.ps1:117-128` 之 review prompt）。每位 Council member 輸出獨立 markdown，frontmatter 含 `model` / `effort` / `diff_source` / `commit_anchor` / `exit_code`。

## Quarterly Threat Model

| 欄位 | 內容 |
|---|---|
| Trigger | `.github/workflows/quarterly-threat-model.yml`（`on.schedule.cron: '30 5 1 1,4,7,10 *'` + `on.workflow_dispatch`） |
| Cadence | 每年 1/4/7/10 月 1 日 UTC 05:30（台灣時間 13:30）；備援 manual `workflow_dispatch` |
| Artifact Destination | reminder issue（labels `security, cadence, quarterly`）；exercise artifact 由 user 依 runbook 產出於 `artifacts/red_team/` 對應路徑 |
| Owner | user（執行 exercise）；issue close 後附 artifact link |
| Runbook | `docs/red_team_runbook.md` |
| Scorecard | `docs/red_team_scorecard.md` |
| Follow-up Backlog | `docs/red_team_backlog.md` |

issue 自動建立後 30 天為建議 deadline；workflow 不執行實際 threat model exercise，僅作 reminder。GitHub Actions schedule 於高負載時段可能延遲（per GitHub 官方文檔），故 cadence drift recovery 必須由 user 季首日 +1 日檢查 issue tracker。

## Continuous: pip-audit / repo-secrets-scan / repo-static-scan

| 欄位 | 內容 |
|---|---|
| Trigger | `.github/workflows/security-scan.yml`（`on: pull_request, push to master, workflow_dispatch`） |
| Cadence | per PR / per push to master / 手動 |
| Artifact Destination | GitHub Actions log；pip-audit 之 `pip-audit-report.json` 落於 run 之 group output |
| Owner | CI 自動 + PR reviewer |
| Components | (a) `pip-audit` 掃 `requirements.txt` CVE；(b) `repo_security_scan.py secrets` 掃 hardcoded credentials；(c) `repo_security_scan.py static` 掃 focused static rules |

continuous 層由既有 workflow 落地（前置 task TASK-* 已建立），本 task 不變動。任何 hardening（fail-on-severity threshold / SBOM 整合 / license audit）屬 future task 範圍。

## Setup Steps

### Weekly Codex Council Audit

前置條件：
1. `OPENAI_API_KEY` 已加入 GitHub Repo Secrets（Settings → Secrets and variables → Actions → New repository secret，name 字面 `OPENAI_API_KEY`）。
2. Repo permissions：Settings → Actions → General → Workflow permissions 為 `Read and write permissions`；`Allow GitHub Actions to create and approve pull requests` 須 enabled（本 workflow 之 `Open PR` step 經 `actions/github-script` 開 PR 需求）。
3. ubuntu-latest runner 預裝 pwsh 7+（per workflow `Run council review` step）+ Node.js + npm（per `Install Codex CLI` step 之 `npm install -g @openai/codex@latest`）；無須額外 setup。

步驟：

1. **確認 secret**：repo settings → Secrets and variables → Actions 之 Repository secrets 列表須含 `OPENAI_API_KEY`。secret value 由 user 自管；workflow 採 `${{ secrets.OPENAI_API_KEY }}` 經 step-level `env:` mapping 注入，不於任何 `run:` 內 echo / print。
2. **驗 PR 權限**（前置必檢，per `### 2026-05-19 Incident: PR Permission Gap` 之 lesson）：執 `gh api repos/<owner>/<repo>/actions/permissions/workflow` 確認回傳 `can_approve_pull_request_reviews: true`。若為 `false`，執 `gh api -X PUT repos/<owner>/<repo>/actions/permissions/workflow -F default_workflow_permissions=read -F can_approve_pull_request_reviews=true` 切；切後重 GET 驗。原因：yml-level `permissions: pull-requests: write`（line 8-10）須 AND repo-level toggle，二者全綠 cron 之 `Open PR` step 方可開 PR。
3. **首次驗證**：merge 後於 Actions tab → Weekly Council Audit → `Run workflow`（manual workflow_dispatch）；確認 (a) `Install Codex CLI` step 印 `codex --version` + `codex.cmd --version` 成功；(b) `Run council review` step 之 wrapper log 含 `[Council] Dispatching to gpt-5.4-mini` / `gpt-5.4` / `gpt-5.5` 三 tier；(c) review artifact 落 `artifacts/reviews/weekly-<date>/` 含 3 個 markdown 檔（per Council member 一檔）；(d) PR title 含 `[claude-routine] Weekly Audit` prefix；(e) PR body 含 source workflow / source script attribution 段。失敗則檢 Actions log 對應 step 之 stderr；若見 `HttpError: GitHub Actions is not permitted to create or approve pull requests` 即回 step 2 驗 PR 權限 toggle。
4. **巡檢**：每週一 user 檢 master 是否有 `[claude-routine] Weekly Audit` 之 PR；無則 Actions tab 之 Weekly Council Audit workflow 點 manual `Run workflow` 補跑（per §Cadence Drift Recovery）。

### Quarterly Threat Model Workflow

1. **GitHub Actions runtime 確認**：repo `Settings → Actions → General → Workflow permissions` 須為 `Read and write permissions`（既有 `security-scan.yml` 已要求）；`Allow GitHub Actions to create and approve pull requests` 不必開（本 workflow 僅建 issue）。
2. **首次手動驗證**：merge 後於 `Actions → Quarterly Threat Model Reminder` 點 `Run workflow` 手動觸發，確認 issue 正確建立、labels 套用、body 引用正確；錯誤則檢查 `actions/github-script` step 之 log。
3. **季首日確認**：每年 1/4/7/10 月 2 日（首日 +1 日）user 至 Issues tab 確認 `[Quarterly Threat Model]` issue 已建；未建則執 `workflow_dispatch:` 手動觸發。

## Cadence Drift Recovery

### 偵測

| Cadence | 偵測信號 | 偵測週期 |
|---|---|---|
| Weekly Codex Council audit | 週一檢查 master 是否有 `[claude-routine] Weekly Audit` 之 PR；或 Actions tab 確認 Weekly Council Audit workflow 上週日 18:00 UTC 之 run 為 success | 週一 |
| Quarterly threat model | 季首日 +1 日檢查 Issues tab 有無 `[Quarterly Threat Model]` issue | 季首日 +1 日 |
| Continuous SAST | PR check status / push to master 之 Actions tab 是否全綠 | 每 PR / push |

### 重啟

- **Weekly Codex Council audit 漏跑**：(a) Actions tab 之 Weekly Council Audit workflow 確認是否被 disabled（GitHub 公開 repo 60 天無活動之 schedule auto-disable 風險）/ secret `OPENAI_API_KEY` 是否失效（rotate / revoke）/ OpenAI quota 是否耗盡（per `Run council review` step 之 stderr 印 `429` / `rate_limit_exceeded`）；(b) `gh run view <id> --log-failed` 印 `HttpError: GitHub Actions is not permitted to create or approve pull requests` 則回 §Setup Steps Weekly step 2 驗 PR 權限 toggle（gh api PUT 切 `can_approve_pull_request_reviews=true`，per `### 2026-05-19 Incident: PR Permission Gap`）；(c) Actions tab 點 `Run workflow` 手動 dispatch 補跑；(d) 若連續 2 週漏跑，建 decision artifact 記 outage + root cause（如 secret rotate、quota 耗盡、cron 高負載延遲、auto-disable、repo permission drift）+ 對應 mitigation。
- **Quarterly issue 漏建**：(a) `Actions → Quarterly Threat Model Reminder` 點 `Run workflow` 手動觸發；(b) 若 cron 連續 2 季漏觸發（≥6 個月），建 decision artifact 並檢 GitHub Actions schedule disable 風險（公開 repo 60 天無活動規則於本 repo 不適用，但 schedule 高負載延遲為已知風險）。
- **Continuous SAST 紅**：依 PR check log 修；不得 force-merge bypass。

### Escalation

任何 cadence outage 之 root cause 不明、或對應 mitigation 失效時，建 `artifacts/decisions/TASK-<id>.decision.md` 記錄：(a) outage 起訖；(b) detection 路徑；(c) suspected root cause；(d) mitigation 嘗試；(e) follow-up task ID（若需）。決定 artifact 由 user 簽核後關閉。

### 2026-05-19 Incident: PR Permission Gap

| 欄位 | 內容 |
|---|---|
| Outage start | 2026-05-10 Sunday 18:00 UTC（首次失敗 cron run 為 2026-05-10T18:22:31Z，per gh run id 25636273248） |
| Outage detected | 2026-05-19（TASK-1068 push 後 audit `gh run list` 揭露兩週連續失敗） |
| Root cause | repo-level `can_approve_pull_request_reviews` 為 `false`；yml-level `permissions: pull-requests: write`（weekly-council-audit.yml line 8-10）被 repo-level toggle 覆蓋；`actions/github-script` `Open PR` step 之 GitHub API call 被拒，stderr 印 `HttpError: GitHub Actions is not permitted to create or approve pull requests`。註：repo + yml 兩 layer 為 AND 機制 |
| Detection 路徑 | `gh run list --limit 10` 查 Weekly Council Audit conclusion 為 failure；`gh run view <id> --log-failed` 印 HttpError 字面；`gh api repos/<owner>/<repo>/actions/permissions/workflow` 確認 toggle 為 false |
| Immediate mitigation | 2026-05-19 user 授權 Claude 經 `gh api -X PUT repos/<owner>/<repo>/actions/permissions/workflow -F default_workflow_permissions=read -F can_approve_pull_request_reviews=true` 切 toggle 為 true；GET verify 後值為 `{"default_workflow_permissions":"read","can_approve_pull_request_reviews":true}` |
| Affected runs | 2026-05-10 / 2026-05-17 兩 weekly cron run（review artifacts 生成 + Run council review step 成功；Open PR step fail；PR 未開） |
| Docs hardening | TASK-1069 落地：§Setup Steps Weekly 新增 step 2「驗 PR 權限」前置 gh api check；§Cadence Drift Recovery Weekly 補 PR fail signal + mitigation；本 §2026-05-19 Incident: PR Permission Gap 永留紀錄供未來 audit |
| Runtime 驗證 | 下次 weekly cron（2026-05-24 Sunday 18:00 UTC）自然 surface 為 success；user 亦可即時 manual `Run workflow` workflow_dispatch 提前驗 |
| Lessons learned | TASK-1063 落地後缺 user-side runtime verification step（doc line 55 寫了 toggle 要求但無 `gh api` enforced check）；governance gap 由本 incident 揭露。未來 docs-yml-runtime 三層 sync 須以可機械驗證之命令 codify（屬第二批 backlog 之 validator design rule cousin） |
