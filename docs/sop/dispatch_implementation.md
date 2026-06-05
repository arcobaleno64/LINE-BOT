# 派發 Implementation SOP

本 SOP 由 `CLAUDE.md` 外移（TASK-1055）；authoritative 版本以本檔為準。CLAUDE.md 保留 quick-ref pointer 指向此檔。

### 派發 Implementation

```
1. 驗證 plan artifact 已完成 premortem（R1-R4 都有）
2. 準備 dispatch prompt，包含：
   - CODEX.md 的規則條文
   - plan artifact 的摘述
   - Scope 限制（什麼不做）
   - Routing inputs: task type、risk score、context cost
   - Codex model/effort policy
3. 執行 `artifacts/scripts/Invoke-CodexAgent.ps1`，依 task scale 指定 model policy
4. 接收 code artifact 與 verify artifact
5. 檢查 `## Files Changed` ⊆ plan 的 `## Files Likely Affected`
```

> Prompt token-cost 慣例（inline vs path-reference vs temp file vs fabrication-prone）：詳見 `docs/dispatch_prompt_discipline.md`。
