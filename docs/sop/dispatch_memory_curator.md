# 派發 Memory Bank Curator SOP

本 SOP 由 `CLAUDE.md` 外移（TASK-1055）；authoritative 版本以本檔為準。CLAUDE.md 保留 quick-ref pointer 指向此檔。

### 派發 Memory Bank Curator

```
1. Closure 或 memory capture 階段若有長期可重用 lesson，Claude 可派 Gemini 以 Memory Bank Curator 模式產生 `Remember Capture` draft。
2. Dispatch prompt 只提供最小必要 context：任務摘要、可追蹤 source、目標 `.github/memory-bank/*.md` 讀取範圍、`.github/prompts/remember-capture.prompt.md`。
3. Gemini 不得改檔；只能分類、查重、驗證來源與輸出 draft。
4. 若 draft 的 `Action` 需要追加/更新/先整併，交由 Claude 或 Codex 在明確 write scope 下修改 `.github/memory-bank/`。
5. Claude 最終驗收安全檢查、source、line count、是否排除 secrets / credential / 短期排障紀錄。
```
