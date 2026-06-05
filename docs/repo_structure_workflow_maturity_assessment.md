# Repo 結構與工作流成熟度評估

## 評估範圍

本報告根據目前 repo 內可見結構與代表性文件進行靜態評估，主要依據如下：

- `README.md`、`README.zh-TW.md`
- `AGENTS.md`、`BOOTSTRAP_PROMPT.md`、`OBSIDIAN.md`
- `docs/orchestration.md`
- `docs/artifact_schema.md`
- `docs/workflow_state_machine.md`
- `docs/subagent_roles.md`
- `docs/lightweight_mode_rules.md`
- `docs/subagent_task_templates.md`
- `.github/workflows/workflow-guards.yml`
- `artifacts/scripts/guard_status_validator.py`
- `artifacts/scripts/guard_contract_validator.py`
- `artifacts/red_team/latest_report.md`
- 代表性 task artifacts
- 目前 git worktree 狀態與目錄分布

## 一、Repo 結構概覽

此 repo 不是以應用程式原始碼為中心，而是以 workflow framework 與 governance artifacts 為中心。

| 區塊 | 主要內容 | 角色 |
|---|---|---|
| 根目錄 | `README*`、`AGENTS.md`、`CLAUDE.md`、`GEMINI.md`、`CODEX.md`、`BOOTSTRAP_PROMPT.md`、`OBSIDIAN.md` | 專案入口、agent 入口、bootstrap 指引 |
| `docs/` | orchestration、schema、state machine、premortem、red team、lightweight mode | 流程規範與制度文件 |
| `docs/templates/` | `implementer/`、`tester/`、`verifier/`、`reviewer/`、`parallel/`、`blocking/` | subagent 任務模板 |
| `artifacts/` | `tasks/`、`research/`、`plans/`、`code/`、`verify/`、`status/`、`decisions/`、`improvement/`、`scripts/` | 流程執行痕跡與自動化腳本 |
| `.github/` | workflow、agents、repository profile | CI 與 GitHub 展示層 |
| `template/` | 幾乎完整鏡像 root 結構 | 新專案 bootstrap 範本 |
| `.obsidian/` | vault 設定 | 文件工作區整合 |
| `external/`、暫存目錄 | 外部內容與測試/演練殘留 | 非核心但會影響工作樹衛生 |

從結構上看，repo 已明確區分出三個層次：

1. 規則層：`docs/`、`AGENTS.md`、各 agent 入口檔。
2. 執行層：`artifacts/` 與 validator / red-team scripts。
3. 發佈層：`README*`、`.github/`、`template/`、`OBSIDIAN.md`。

這種分層清楚，對「可審核」、「可移植」、「可 bootstrap 到新 repo」很有幫助。

## 二、工作流機制盤點

目前 repo 內的工作流能力不是只有文件宣告，而是已經有相當程度的落地。

| 能力 | 證據 | 評語 |
|---|---|---|
| Artifact-first | `docs/orchestration.md`、`docs/artifact_schema.md`、`artifacts/*` | 核心設計完整，且已有多個實際 task 留痕 |
| 狀態機管理 | `docs/workflow_state_machine.md` | 狀態與轉移規則明確，非法跳轉有明文禁止 |
| 角色分工 | `docs/subagent_roles.md`、`CLAUDE.md`、`GEMINI.md`、`CODEX.md` | 主控、研究、實作責任切分清楚 |
| Gate 驗證 | `guard_status_validator.py` | 不只是 soft guideline，而是可自動檢查 |
| Contract drift 防護 | `guard_contract_validator.py` | root / template / Obsidian / README 同步有機制保護 |
| Prompt regression | `.github/workflows/workflow-guards.yml`、對應 validator | 顯示 repo 已把 prompt 視為可回歸測試的資產 |
| Red-team | `docs/red_team_runbook.md`、`artifacts/red_team/latest_report.md` | 有演練機制，不只停在靜態規則 |
| Lightweight mode | `docs/lightweight_mode_rules.md` | 顯示流程已開始考慮效率與治理平衡 |
| Template discovery | `artifacts/scripts/discover_templates.py`、`docs/templates/` | 顯示系統已從人工引用模板走向可發現化 |

<!-- 在此填入代表性 task artifact 的觀察結果 -->

## 三、成熟度評估

本報告以 5 級制評估：

- Level 1: Initial
- Level 2: Repeatable
- Level 3: Defined
- Level 4: Managed
- Level 5: Optimizing

### 3.1 Repo 結構成熟度

| 維度 | 評分 | 判斷 |
|---|---:|---|
| 目錄分層 | _/5 | <!-- 填入判斷 --> |
| 文件入口清晰度 | _/5 | <!-- 填入判斷 --> |
| 範本化程度 | _/5 | <!-- 填入判斷 --> |
| 可發現性 | _/5 | <!-- 填入判斷 --> |
| 工作樹衛生 | _/5 | <!-- 填入判斷 --> |

Repo 結構整體評級：**Level _ / ___**。

### 3.2 工作流成熟度

| 維度 | 評分 | 判斷 |
|---|---:|---|
| 流程定義完整度 | _/5 | <!-- 填入判斷 --> |
| Artifact schema 完整度 | _/5 | <!-- 填入判斷 --> |
| 自動化驗證 | _/5 | <!-- 填入判斷 --> |
| 實際採用程度 | _/5 | <!-- 填入判斷 --> |
| CI 整合廣度 | _/5 | <!-- 填入判斷 --> |
| 治理閉環能力 | _/5 | <!-- 填入判斷 --> |
| 持續最佳化能力 | _/5 | <!-- 填入判斷 --> |

工作流整體評級：**Level _ / ___**。

## 四、主要優勢

<!-- 列出 repo 的主要優勢，建議 3-5 項 -->

## 五、主要風險與缺口

<!-- 列出主要風險與缺口，建議 3-5 項 -->

## 六、整體判斷

### 總結評級

- Repo 結構成熟度：**_/5**
- 工作流成熟度：**_/5**
- 綜合評估：**Level _ / ___**

### 判斷摘要

<!-- 填入整體判斷摘要 -->

## 七、建議優先事項

<!-- 列出建議優先事項，建議 3-5 項 -->

---

## 八、Code Review：代碼品質、安全性與可維護性

### 8.0 總覽

本次 code review 涵蓋 `artifacts/scripts/` 下的所有 Python 與 PowerShell 腳本。

| 腳本 | 行數（約） | 角色 |
|---|---:|---|
| `guard_status_validator.py` | ~1850 | 核心：artifact / state / scope drift / premortem / Gate E 驗證 |
| `guard_contract_validator.py` | ~250 | root ↔ template 同步守護 |
| `run_red_team_suite.py` | ~800+ | static + live + prompt 紅隊演練 |
| `prompt_regression_validator.py` | ~180 | prompt 回歸測試引擎 |
| `build_decision_registry.py` | ~250 | decision artifact → JSON registry |
| `aggregate_red_team_scorecard.py` | ~110 | red-team report → 計分卡 |
| `discover_templates.py` | ~100 | subagent 範本發現 |
| `update_repository_profile.py` | ~90 | `.github/repository-profile.json` 管理 |
| `validate_scorecard_deltas.py` | ~90 | reviewer delta 驗證 |
| `Invoke-CodexAgent.ps1` | ~120 | Codex CLI resilient wrapper |
| `Invoke-GeminiAgent.ps1` | ~120 | Gemini CLI resilient wrapper |
| `load_env.ps1` | ~12 | `.env` 載入 |

### 8.1 代碼品質

#### 優點

<!-- 列出代碼品質優點 -->

#### 可改進項目

| # | 類別 | 位置 | 說明 | 嚴重度 |
|---|---|---|---|---|
| Q1 | <!-- 類別 --> | <!-- 位置 --> | <!-- 說明 --> | <!-- 嚴重度 --> |

### 8.2 安全性

#### 優點

<!-- 列出安全性優點 -->

#### 風險項目

| # | 類別 | 位置 | 說明 | 嚴重度 |
|---|---|---|---|---|
| S1 | <!-- 類別 --> | <!-- 位置 --> | <!-- 說明 --> | <!-- 嚴重度 --> |

### 8.3 可維護性

#### 優點

<!-- 列出可維護性優點 -->

#### 可改進項目

| # | 類別 | 位置 | 說明 | 嚴重度 |
|---|---|---|---|---|
| M1 | <!-- 類別 --> | <!-- 位置 --> | <!-- 說明 --> | <!-- 嚴重度 --> |

### 8.4 綜合評分

| 維度 | 評分 | 摘要 |
|---|---:|---|
| 代碼品質 | _/5 | <!-- 摘要 --> |
| 安全性 | _/5 | <!-- 摘要 --> |
| 可維護性 | _/5 | <!-- 摘要 --> |
| **綜合** | **_/5** | <!-- 摘要 --> |

### 8.5 建議行動優先順序

| 優先 | 行動 | 效果 |
|---:|---|---|
| 1 | <!-- 行動 --> | <!-- 效果 --> |

---

## 九、修訂紀錄

| 日期 | 版本 | 變更摘要 |
|---|---|---|
| <!-- 日期 --> | v1.0 | 初版評估 |
