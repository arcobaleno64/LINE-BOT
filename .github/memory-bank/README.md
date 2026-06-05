# Memory Bank — 知識庫檔案索引

本目錄存儲本 repository 的穩定知識和經驗法則。

## 檔案清單

| 檔案 | 用途 | 更新頻率 |
|---|---|---|
| `artifact-rules.md` | Artifact schema 的已知規則和例外 | 月度 |
| `workflow-gates.md` | Guard validator 的觸發條件與回避方式 | 雙周 |
| `prompt-patterns.md` | 本 repo 的 prompt 寫作範式 | 月度 |
| `project-facts.md` | 專案特有的技術棧、集成點、部署約定 | 改變時 |
| `coverage-sprint.md` | 測試覆蓋率衝刺策略、技巧與踩坑紀錄 | 衝刺完成時 |

## 經驗沉澱流程

新增或更新 memory-bank 檔案時，使用 `remember-capture.prompt.md` 流程。
該流程提供分類、查重、膨脹檢查與安全檢查，避免重複寫入或檔案膨脹。
Gemini CLI 可用 Memory Bank Curator 模式產生 draft，但不得直接寫入本目錄；實際修改由 Claude/Codex 在明確 scope 下執行，並由 Claude 最終驗收。
若 Gemini 研究 draft 含 Tavily-assisted research，`## Tavily Cache` / `## Source Cache` 只是 draft evidence；不得直接轉寫成本目錄內容。
詳見 `.github/prompts/remember-capture.prompt.md`。

## 寫法規範

- 簡潔第一：1-2 句事實，避免囉唆
- 版本化：若涉及特定腳本版本或 artifact 版本，註明
- 引用：指向原始檔案或 commit
- 私密性：絕不存儲憑證或敏感資訊
- 品質：只保存長期、可追蹤、非顯而易見、非短期排障且未過時的知識

## 維護

- 每個 session 完成後複查
- 發現新規則立即記錄
- 季度深度複查（刪除過時、更正錯誤）
