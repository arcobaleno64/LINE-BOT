# Artifact Spec: test

> 本檔由 `docs/artifact_schema.md` §5.5 拆分而來；schema literal、欄位定義、字串契約皆與原檔逐字對齊。

## 5.5 Test Artifact Schema

> PDCA Stage: C (Check，測試輸出)

檔名：`artifacts/test/TASK-001.test.md`

用途：承接測試與驗證輸出，不把原始 log 丟進主 thread。

必填區段：

```md
# Test Report: TASK-001

## Metadata
- Task ID:
- Artifact Type: test
- Owner:
- Status:
- Last Updated:

## Test Scope

## Commands Executed

## Result Summary

## Failures

## Evidence Files

## Recommendation
```

欄位規則：

- `Commands Executed`: 至少列出實際命令或測試類型。
- `Result Summary`: 必須有總結，不可只貼 log。
- `Failures`: 沒有時寫 `None`。
- `Evidence Files`: 若完整 log 落地到其他檔案，需在此列出。

最低驗收標準：

- 不可只貼 raw output。
- 必須明確指出是 pass、fail 或 blocked。

---
