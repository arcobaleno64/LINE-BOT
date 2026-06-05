---
name: debug-runbook
description: Debug runbook for active incidents (transient; convert to improvement artifact post-incident)
version: 1.0.0
applicable_agents:
  - Claude Code
  - Codex CLI
applicable_stages:
  - any
applicable_scale: both
prerequisites: []
---

# Debug Runbook: {{INCIDENT_ID}}

> 與既有 artifact spec 之關係：Debug runbook 為「事件發生中」之 transient 紀錄，行動導向、短時效；事件結束後須轉為 `artifacts/improvement/{{TASK_ID}}.improvement.md` 作 post-mortem 留底。
> Debug runbook **不入 lifecycle**，**不被 `guard_status_validator.py` 檢查**；屬 ad-hoc 工作筆記。

## Metadata

- Incident ID: {{INCIDENT_ID}}
- Started: {{ISO8601}}+08:00
- Severity: {{P0 | P1 | P2 | P3}}
- Owner: {{name}}

## Symptom

<!-- 觀察到之失敗症狀；錯誤訊息、stack trace、用戶報告原文 -->

## Reproduction

<!-- 最小重現路徑；命令、輸入、環境 -->

## Hypothesis

<!-- 候選根因；逐條附 evidence-needed -->

- H1: {{hypothesis}}
  - Evidence needed: {{logs | metrics | trace | code review | git bisect}}
  - Verified: {{yes | no | partial}}

## Evidence

<!-- 已收集之 logs / metrics / outputs；對 hypothesis 之檢驗結果 -->

## Fix

<!-- 採用之修復動作；commit hash、PR、配置變更 -->

- Action: {{description}}
- Commit: {{hash}}
- PR: {{url}}
- Verified by: {{test | smoke | manual | monitor}}

## Regression Test

<!-- 防止再發之 test 或 monitor；對應未來 improvement §5.Preventive Action -->

## Conversion Note

<!-- 事件結束後填寫；填好後將內容轉入 improvement artifact 並刪除本檔（或歸檔至 incident log） -->

- Converted to improvement artifact: {{path | not yet}}
- Lessons captured: {{summary}}
