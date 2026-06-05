---
applyTo: "**"
---

# Memory Bank — 知識庫管理規範

## 知識庫結構

### `.github/memory-bank/`（Repository 級知識）

用途：本 repo 的穩定知識、guard 規則、常見失誤、技術棧資訊
生命周期：版本化（與 git 歷史對齊）
更新頻率：發現新規則或過時時更新

檔案：
- `artifact-rules.md` — Artifact schema 的已知規則和例外
- `workflow-gates.md` — Guard validator 的觸發條件與回避方式
- `prompt-patterns.md` — Agent dispatch 範式與 artifact 輸出範本
- `project-facts.md` — 技術棧、集成點、環境變數、構建約定

## 權限與責任

| 階段 | 負責角色 | 權限 |
|---|---|---|
| Detect | Claude Code / Codex CLI / Tester | 指出可能值得沉澱的 lesson |
| Curate | Gemini CLI | read-only curator；分類、查重、驗證來源、產生 `Remember Capture` draft |
| Write | Claude Code 或 Codex CLI | 在明確 scope 下修改 `.github/memory-bank/` |
| Approve | Claude Code | 最終驗收是否寫入、source、line count 與安全檢查 |

Gemini 不擁有 `.github/memory-bank/` 寫入權；它只能輸出 draft。任何追加、更新或整併都必須由 Claude/Codex 以窄範圍修改執行，並由 Claude 最終驗收。

若 Gemini 在研究或 curator draft 中被允許使用 Tavily CLI，Tavily 結果只能作為 research artifact draft 的 `## Tavily Cache` / `## Source Cache`。Gemini 不得把 Tavily cache 直接轉寫進 `.github/memory-bank/`；Tavily CLI 不可用時，必須標示 blocked 或 `UNVERIFIED`。

### 經驗沉澱流程

新增或更新 memory-bank 檔案時，使用 `.github/prompts/remember-capture.prompt.md` 流程。
該流程提供分類（artifact-rule / workflow-gate / prompt-pattern / project-fact）、查重、膨脹檢查與安全檢查。
若由 Gemini 執行，輸出僅能是 `Remember Capture` draft，不得直接修改 repo-tracked memory-bank files。

## 寫法規範

- 簡潔：單行事實或短列表，避免長段落
- 引用：每條事實附註來源（檔案名:行號 或 commit hash）
- 版本化：若涉及某個 artifact 或 script，註明版本
- 隱私：絕不寫密碼、token、個人資訊
- 品質：只保存長期、可追蹤、非顯而易見、非短期排障且未過時的知識；可由文件或常識輕易推敲出的內容不要寫入

## 何時更新

- 不要在 session 進行中頻繁更新（會干擾當前工作）
- Session 完成後，提煉重點寫入
- 發現新的 pattern 或 gotcha 時立即記錄
- 月度複查：刪除過時、合併重複、更正錯誤

## 查詢方式

直接讀取 `.github/memory-bank/` 下的對應檔案：
- 查 artifact 規則：讀 `.github/memory-bank/artifact-rules.md`
- 查 gate 條件：讀 `.github/memory-bank/workflow-gates.md`
- 查 prompt 範式：讀 `.github/memory-bank/prompt-patterns.md`
- 查技術棧：讀 `.github/memory-bank/project-facts.md`
