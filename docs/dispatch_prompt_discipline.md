# Dispatch Prompt Discipline

本文件為 sub-agent dispatch 之 caller-side prompt 慣例之 authoritative governance；codified from `memory/feedback_dispatch_prompt_discipline.md`。Routing rule、threshold 與 case study 之 anchor 字面以本文件為準。

## 1. 適用範圍

本規範適用於以下三 wrapper 之 caller：

- `artifacts/scripts/Invoke-CodexAgent.ps1`（`-Prompt` 為 free-text string；caller 全權決定 prompt 內容）
- `artifacts/scripts/Invoke-GeminiAgent.ps1`（`-Prompt` 為 free-text string；同上）
- `artifacts/scripts/Invoke-CodexReview.ps1`（**不收自由 prompt**；prompt 由 `-DiffSource` 自動推導；故本規範對 review wrapper 不適用——保留為「為何不在此規範範圍內」之反證）

「Caller」一般指 Claude 主 agent，亦含人工命令列觸發之 dispatch。

## 2. Token 成本機制

Claude Code 之 Agent tool 中，tool call `prompt` field 為主 agent 之 generation output。主 agent 必先吞下整段 prompt 文本，才能將其交給 sub-agent。此即：

- **主 agent 端 token 成本** = system prompt + 對話 context + tool call composition（含整段 `prompt` field）
- **sub-agent 端 token 成本** = wrapper 將 prompt 傳入新 fresh session 之 input tokens

Fresh sub-agent（Gemini wrapper / Codex wrapper / 多數 named subagent_type）為 fresh session 全載，無 prompt cache 攤銷。故將長文本 inline 嵌入 dispatch prompt 等同雙重計費：主 agent 與 sub-agent 同時付費。

## 3. Routing Rule

依 prompt 內擬嵌入之內容類型，採以下四分支：

| 分支 | 條件 | 處理 | 範例 |
|---|---|---|---|
| **inline** | 長度 ≤ 500 chars 且為 instruction / scope constraint / anti-fabrication rule | 直接內嵌於 `-Prompt` | `"審視 artifacts/research/TASK-XXX.research.md §Sources 段，並驗證所有 URL 可達。"` |
| **path-reference** | 長度 > 500 chars 之 artifact / spec / 規則章程 | 僅傳檔案路徑，令 sub-agent 自行 Read | `"Read GEMINI.md and artifacts/tasks/TASK-XXX.task.md，然後依其 §Acceptance Criteria 撰寫 research。"` |
| **temp file** | 主 agent 推斷後產之 dynamic context（非既有檔） | 寫入 `%TEMP%/dispatch-<task-id>-<role>.md` 後傳 path | `"Read $env:TEMP/dispatch-TASK-1064-research.md 之 working context。"` |
| **fabrication-prone** | SHA / 版本號 / 行號 / commit hash 等 sub-agent 易捏造之引用 | 永遠 inline 並標 `UNVERIFIED:` 或要求 sub-agent 直驗（gh api / grep） | `"Verify SHA 60a0d83039c74a4aee543509d22c19323799cdea via gh api repos/actions/github-script/git/refs/tags/v7.0.1 before pinning."` |

### 3.1 Threshold 之選擇

`500` chars 為當前 anchor 字面。500 chars 約對應 80-100 中文字 + 英文技術詞，足以涵蓋一條 instruction + 一條 scope constraint + 一條 anti-fabrication rule；超出此量級之內容語意密度通常已下降，path-reference 之 read overhead 划算。

threshold 之未來調校（上下調或引入分段 threshold）屬另立 task 之決策範圍；任何調整須同步本文件 + `memory/feedback_dispatch_prompt_discipline.md` + PR-031 anchor。

### 3.2 fabrication-prone 例外之 rationale

Sub-agent（特別是 Gemini CLI）對引用 SHA / 版本號 / commit hash 之 fabrication 為已知行為（per `memory/feedback_wrapper_known_bugs.md` Bug-B1）。若採 path-reference 令 sub-agent 自行 Read，sub-agent 仍可能在生成 output 時產出 fabricated 字面。故 fabrication-prone 引用永遠 inline + `UNVERIFIED:` 標記，並要求 sub-agent 走 `gh api` / `grep` 直驗回報，不接受 sub-agent 之 verbal claim。

## 4. Case Studies

### 4.1 TASK-1063 — 5722-char Gemini dispatch（2026-05-08）

**事件**：Council-review revert task 之 Research 階段，Claude 將 TASK-1058 backlog 段落 + GEMINI.md 規則 + 預期輸出格式全段 inline 嵌入 dispatch prompt，總長度 5722 chars。

**後果**：
- 主 agent context 已吞下整段 5722 chars 作為 tool call output composition
- Gemini sub-agent 收到 prompt 後，於 Sources 段生成 fabricated GitHub URL（namespace `arcobaleno64` / hash `60a0d8...46f366` 末 24 chars corrupted）
- 主 agent review 階段須移除捏造項、renumber，等同主 agent 親手做完工作
- 總 token 成本未省反翻倍

**正確處置**：dispatch prompt 應為「Read GEMINI.md and artifacts/tasks/TASK-1063.task.md，依 §Acceptance Criteria 撰寫 research artifact at artifacts/research/TASK-1063.research.md。Sources 段每條引用須以 gh api 或本地 grep 直驗，禁止猜測 commit hash 或版本字串。」此版本約 200 chars，主 agent context 省 5500 chars。

### 4.2 TASK-1061 — 5001-char Codex multiline dispatch（2026-05-08）

**事件**：CITATION_PATTERN 放寬 task 之 Coding 階段，Claude dispatch Codex 跑 plan §CP-1..CP-6，prompt 為 multiline 5001 chars，起手 `[ROLE]`。

**後果**：
- Wrapper bug-W4（Windows `cmd.exe` 對 multiline arg 在第一個 LF/CR 處截斷）觸發；Codex CLI 收到 prompt 第一行 8 chars `[ROLE]`
- 9 retry × 3 tier 全 deterministic 失敗
- 主 agent context 已吞下完整 5001 chars，token 成本翻倍
- 主 agent 最終以 fork sub-agent fallback 自行執完 plan

**後續修復**：Bug-W4 已由 TASK-1062 commit `b5b7e32` 修（stdin pipe threshold 由 7000 降至 0；Codex side per artifacts/scripts/Invoke-CodexAgent.ps1）；TASK-1063 reopen pass 補 Gemini 同 fix（per artifacts/scripts/Invoke-GeminiAgent.ps1）。**但 wrapper fix 僅解 CLI arg 鏈路問題，未解 caller-side token 翻倍問題**——後者為本規範存在之核心理由。

**正確處置**：Coding 階段 dispatch 應為「Read artifacts/plans/TASK-1061.plan.md §CP-1..CP-6 並執行；按 plan §Files Likely Affected 修改，commit 一次。Wrapper 為被測物，dispatch 自身不應修 wrapper script.」約 180 chars。

## 5. Audit Procedure

未來新增 dispatch event 前，caller 應自審 prompt 字符長度。簡易方法：

```powershell
# PowerShell：將擬 dispatch 之 prompt 暫存於變數
$prompt = @'
<your dispatch prompt here>
'@
$prompt.Length  # 顯示字元數；> 500 即須改 path-reference
```

歷史 dispatch event 之 audit 可 grep 既有 task 之 `code.md` / `decision.md` / `verify.md` 中之 dispatch log 段：

```bash
grep -rE "prompt_size=[0-9]+|prompt[^a-z]*= ?[0-9]+ chars" artifacts/
```

自動化 enforcement（CI-side 強制 reject > 500 char dispatch）未列入本規範範圍；屬未來 task。當前 enforcement 為 caller 之自律 + PR-031 之 doc 字面 anchor 偵測。

Wrapper-side enforcement（自 TASK-1067）：三 wrapper（`Invoke-CodexAgent` / `Invoke-GeminiAgent` / `Invoke-CodexReview`）於 prompt size 超過閾值時自動 warn 或 reject（dispatch wrapper warn @ 500 / reject @ 5000 chars，exit 4；review wrapper warn @ 100000 / reject @ 200000 chars，diff-driven 故較寬鬆）；caller 可傳 `-SuppressSizeWarn` 暫時繞過。PR-032 anchor 守 wrapper 字面之 bounds 設定。

## 6. Cross-references

- `memory/feedback_dispatch_prompt_discipline.md`：本規範之 origin memory；4 條 how-to-apply 細則之原文出處。
- `memory/feedback_wrapper_known_bugs.md`：Bug-W4（cmd.exe truncation）+ Bug-B1（Gemini Sources fabrication）之事件記錄。
- `artifacts/scripts/Invoke-CodexAgent.ps1`：Codex wrapper；caller-side `-Prompt` 接收點。
- `artifacts/scripts/Invoke-GeminiAgent.ps1`：Gemini wrapper；同上。
- `artifacts/scripts/Invoke-CodexReview.ps1`：review wrapper；本規範不適用之反證。
- `artifacts/scripts/drills/prompt_regression_cases.json` PR-031：本文件之 keyword pin anchor。
- 三 agent 入口檔之 cross-reference：`CLAUDE.md` 派發段、`GEMINI.md` Write Scope Discipline 段、`CODEX.md` Write Scope Discipline 段。
