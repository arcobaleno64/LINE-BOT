# SUBAGENT_TASK_TEMPLATES — Index

本文件為 subagent task template 的索引。各 template 已拆分至獨立目錄 `docs/templates/<role>/TEMPLATE.md`。

---

## Template 清單

| Template | 路徑 | 適用 Agent | 適用階段 |
|----------|------|-----------|---------|
| Implementer | `docs/templates/implementer/TEMPLATE.md` | Codex CLI | coding |
| Tester | `docs/templates/tester/TEMPLATE.md` | Codex CLI | testing |
| Verifier | `docs/templates/verifier/TEMPLATE.md` | Codex CLI / Claude Code | verifying |
| Reviewer | `docs/templates/reviewer/TEMPLATE.md` | Codex CLI | verifying |
| Parallel Execution | `docs/templates/parallel/TEMPLATE.md` | Codex CLI | coding → verifying |
| Memory Curator | `docs/templates/memory-curator/TEMPLATE.md` | Gemini CLI | closure |
| Blocking | `docs/templates/blocking/TEMPLATE.md` | Any | any |

---

## 設計原則

- 每個模板都是最小可用
- 強制輸入與輸出
- 不允許模糊描述

如果一個 subagent 可以自由發揮，那這整套系統就會開始失控
