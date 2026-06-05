# council-forge ↔ LINE-BOT 治理映射

> 本檔為**索引映射，非再造**（map, don't recreate）。LINE-BOT 於 2026-06-05 以 additive overlay
> 納入 council-forge artifact-first 治理（brownfield retrofit）。LINE-BOT 既有之豐富治理文件
> **原封保留**，本檔僅標其與 council-forge artifact 類型之對應，使二治理體系並存而不重複。

## 1. Retrofit Record

- **日期**：2026-06-05
- **repo 性質**：**已存之 git repo**（branch `main`，有 remote `origin`/GitHub），活躍開發中（R5–R9 security 整改史）。**不 git init**；overlay 落於新 branch `council-forge/retrofit-overlay`（**本地，絕不 push**）。
- **方法**：`scaffold_downstream.py --retrofit`（copy-missing-only，絕不覆蓋既有檔）；brownfield marker。
- **技術棧**：ASP.NET Core（C#/.NET）LINE Messaging webhook bot；與 Sentinel 同 .NET 家族（異於 Tauri 之 Verso/Vero）。
- **唯一既有檔變動**：`.gitignore`（additively 補 `.omc/`，免瞬態工具態入庫）。其餘既有 tracked 檔（`README.md`、`README.zh-TW.md`、`AGENTS.md`、`appsettings*.json`、`Program.cs`、`Controllers/`、`Services/`、`Models/` 等）**byte 不變**（`git diff` 證之，僅 .gitignore 一筆 M）。
- **機密**：appsettings.json 之 secrets 皆 placeholder（`<YOUR_*>`）；render.yaml 用 `sync:false`（機密由 Render env 注入）；源碼啟動即拒空 secret。**無真機密入庫。**
- **reconciliation**（Sentinel 範式——LINE-BOT 有自有雙語 README + LICENSE，overlay 皆不補不剪）：
  - 剪 council-forge `TASK-900..951` 種子範例（潔淨 lifecycle）。
  - ⚠ **剪 council-forge 之 4 GitHub Actions workflows**（`quarterly-threat-model`/`security-scan`/`weekly-council-audit`/`workflow-guards`），**存其自有 `docker-publish.yml`**——LINE-BOT 有活躍 remote，不擅改其 CI 面（workflow-guards 跑 Python guard 於 .NET repo 恐紅）。**此 4 workflow 仍備於 council-forge，主公若欲 opt-in council-forge 安全 CI，可日後自行取回。**

## 2. 雙入口並存（AGENTS.md ↔ CLAUDE.md）

| 入口 | 來源 | 職司 |
|---|---|---|
| `AGENTS.md` | LINE-BOT 自有（保留） | repo 專屬 review rules：webhook 簽章驗證、AI failover、dedup、throttle 等紅線 |
| `CLAUDE.md` | council-forge overlay | artifact-first 協調者：嚴格流程、STOP 觸發、Build Guarantee、routing |

二者並存：`CLAUDE.md` 治 artifact-first 生命週期；`AGENTS.md` 治 LINE-BOT 專屬 review/security 紀律。新工作之 plan §Risks 宜納 AGENTS.md「Critical Review Areas」既有紅線。

## 3. 既有治理文件 → council-forge artifact 類型（映射，不再造）

| LINE-BOT 既有 | 類型 | council-forge 對應 | 處置 |
|---|---|---|---|
| `threat-model-20260417-013953/`（STRIDE：assessment/architecture/threatmodel/stride/findings/inventory） | 威脅模型 | research + verify（security evidence）；premortem 來源 | 保留；安全分析之核心 |
| `SECURITY_REVIEW.md`、`SECURITY_DEPLOYMENT.md` | 安全審查/部署 | verify / security evidence | 保留 |
| `CODE_REVIEW_DETAILED.md` | 詳細碼審 | reviews | 保留 |
| `MATURITY_ASSESSMENT.md` | 成熟度評估 | improvement / verify | 保留 |
| `OPTIMIZATION_PLAN.md`、`LINE_INTEGRATION_PLAN.md` | 計畫 | plan | 保留 |
| `CHANGELOG.md` | 變更史 | improvement / PROCESS_LEDGER | 保留 |
| `DEPLOYMENT_MANUAL.md` | 部署手冊 | runbook / verify | 保留 |
| `USER_GUIDE.md`、`USER_GUIDE_NON_ENGINEER*.zh-TW.md` | 使用指引 | docs（user-facing） | 保留 |
| `FINAL_REVIEW_CHECKLIST.md`、`DELIVERY_SUMMARY.md`、`PR_DESCRIPTION.md` | 交付/審查 | verify / decision | 保留 |
| `Dockerfile`、`render.yaml`、`web.config`、`.github/workflows/docker-publish.yml` | 部署/CI | runbook / 既有 CI（保留不動） | 保留 |

## 4. 自此以後（forward）

- 新工作循 council-forge artifact-first 生命週期於 `artifacts/`（task→plan→research→code→test→verify→decision→status）；plan §Risks 須含事前驗屍，承 AGENTS.md 既有 review 紅線與 threat-model findings。
- 既有 LINE-BOT 文件**不重寫**為 council-forge 格式；以本映射橋接（映射而非再造）。
- per-task 細映射（如 threat-model findings → 對應 verify/decision）可俟首個 governed task 漸次深化；今為 index 層映射。
- **CI**：保留自有 `docker-publish.yml`；council-forge 4 workflows 已剪但仍備於母本，可 opt-in。
- **Build Guarantee**：.NET 專案以 `dotnet build`/`LineBotWebhook.Tests` 之測試結果 + Docker 映像為 verify 佐證。
