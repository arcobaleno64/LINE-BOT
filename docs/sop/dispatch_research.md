# 派發 Research SOP

本 SOP 由 `CLAUDE.md` 外移（TASK-1055）；authoritative 版本以本檔為準。CLAUDE.md 保留 quick-ref pointer 指向此檔。

### 派發 Research

```
1. 準備 dispatch prompt，包含：
   - 問題敘述
   - GEMINI.md 的規則條文
   - 預期輸出格式（見 docs/schemas/artifact-spec-research.md §5.2）
2. 執行 `gemini -m gemini-3.1-flash-lite-preview --approval-mode=yolo -p "..."` 或 `artifacts/scripts/Invoke-GeminiAgent.ps1`
3. 接收 research artifact，驗證 `## Sources` 有 >=2 條 + URL
```

> Prompt token-cost 慣例（inline vs path-reference vs temp file vs fabrication-prone）：詳見 `docs/dispatch_prompt_discipline.md`。
