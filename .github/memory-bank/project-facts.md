# Project Facts — 技術棧、集成點、部署約定

**Reference**: docs/orchestration.md, .github/workflows/  
**Last Updated**: 2026-04-25 +08:00

## 技術棧

Language: Python 3.11
Framework: N/A (CLI utility)
Testing: pytest + pytest-cov
Linting: pylint + black
Version Control: Git + GitHub
CI/CD: GitHub Actions (see .github/workflows/)
Context Tooling: code2prompt (optional, 用於 pack-context CLI mode, `cargo install code2prompt`)
Research Tooling: Tavily CLI (optional, 用於 Gemini Tavily-assisted research)
  - 套件: `tavily-cli` (PyPI)，安裝指令：`pip install tavily-cli`
  - **CLI 命令名為 `tvly`**（非 `tavily`，常見混淆點，必須以 `tvly` 呼叫）
  - 認證：`tvly login --api-key tvly-XXX` 或設 `TAVILY_API_KEY` 環境變數
  - 認證設定檔：`~/.tavily/config.json`（含 API key，**不得提交、不得進 memory-bank**）
  - 驗證可用：`tvly --status`、`tvly auth`
  - 速測：`tvly --json search "query" --max-results 2`

## 主要組件

| 組件 | 檔案 | 說明 |
|---|---|---|
| Guard Status Validator | artifacts/scripts/guard_status_validator.py | Artifact 流程檢查 |
| Guard Contract Validator | artifacts/scripts/guard_contract_validator.py | Prompt 和 README 同步檢查 |
| Context Stack Validator | artifacts/scripts/validate_context_stack.py | 上下文系統完整性驗證 |
| Red Team Suite | artifacts/scripts/run_red_team_suite.py | 自動化紅隊演練 |
| Regression Validator | artifacts/scripts/prompt_regression_validator.py | Prompt 變更檢測 |

## 已知集成點

本專案與以下外部系統有集成關係。

### GitHub API
用途：讀取 PR 和 issue metadata, 推送 artifact 到 release notes
認證：Personal access token（環境變數 GITHUB_TOKEN，勿寫進 memory-bank）
端點：api.github.com/repos/arcobaleno64/line-bot/...

### External Integrations / Upstream Repo（若有 fork）
Location: external/line-bot-upstream-pr/
同步方式：每次 PR 執行 git fetch upstream + git reset --hard upstream/main
Protected: 禁止本地特性分支進入此目錄

## 環境變數

| 變數 | 用途 | 示例 | 必需 |
|---|---|---|---|
| GITHUB_TOKEN | 驗證 GitHub API | ghp_xxx... | 否（fallback 為唯讀） |
| PYTHONPATH | Import artifacts/scripts | C:\...\CLI | 用於 guard scripts |

## 執行環境

Python 3.11 venv（`.venv/`）：在執行 guard scripts 前必須啟動。

## 構建和部署

本地開發安裝：
python -m pip install -r requirements-dev.txt

`requirements-dev.txt`：root / template 必須完全同步的本地開發與測試依賴契約。

初始化外部整合：
git submodule update --init --recursive

本地測試：
python -m pytest artifacts/scripts/test_guard_units.py artifacts/scripts/test_security_scans.py -q

執行 guard：
python artifacts/scripts/guard_status_validator.py --task-id TASK-900

執行紅隊演練：
python artifacts/scripts/run_red_team_suite.py --phase all
python artifacts/scripts/run_red_team_suite.py --phase static --keep-temp

## 常見故障排查

| 問題 | 原因 | 解決 |
|---|---|---|
| Guard 找不到 task artifact | Filename 不符 TASK-XXX 格式 | 確認 artifacts/tasks/TASK-XXX.task.md |
| Prompt regression 失敗 | CLAUDE.md 或 GEMINI.md 變更了 | 執行 guard_contract_validator 檢查 diff |
| CI timeout on red-team | Phase all 太重 | 改用 --phase inference 或 --phase static |
| 需要保留 red-team fixture | 預設執行後會自動清理 `.codex-red-team/` | 改用 `python artifacts/scripts/run_red_team_suite.py --phase static --keep-temp` |
| `which tavily` 找不到 / 誤判 Tavily 不可用 | Tavily CLI 套件 (`tavily-cli`) 安裝後實際命令名為 `tvly`，非 `tavily`；以 `which tavily` 查必失敗 | 改用 `which tvly` 與 `tvly --status` 驗證；參見上述「Research Tooling」 |

## 版本歷史

v1.0 (2026-04-16): 初版，基於 workflow v3
