---
name: rtm
description: Requirements Traceability Matrix template (full scale; manual or via build_rtm.py follow-up)
version: 1.0.0
applicable_agents:
  - Claude Code
applicable_stages:
  - planning
  - verification
applicable_scale: full
prerequisites:
  - artifacts/tasks/{{TASK_ID}}.task.md
---

# RTM: {{TASK_ID}}

> 與既有 artifact spec 之關係：RTM 是聚合視圖，以 task §AC-N 編號為主鍵，跨 plan / code / verify artifact 拉出 trace。
> 本範本提供格式；自動聚合工具 `build_rtm.py` 為 follow-up（屬另一 task），手動填寫即可滿足 full scale 要求。

## Metadata

- Task ID: {{TASK_ID}}
- Last Updated: {{ISO8601}}+08:00
- Coverage: {{number_of_verified_AC}}/{{total_AC}}

## Matrix

| Requirement ID | Description | Source | Linked Task | Linked Plan | Linked Code | Linked Verify | Status |
|---|---|---|---|---|---|---|---|
| AC-1 | {{requirement description}} | task §Acceptance Criteria | TASK-XXXX §AC-1 | plan §Proposed Changes Step N | code §Files Changed: path/to/file | verify §AC-1 | verified |
| AC-2 | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{...}} | {{verified \| deferred \| blocked}} |

## Coverage Summary

- verified: {{N}} / {{total}}
- deferred: {{N}}（每條須附 reason_code，見 verify §Deferred Items）
- blocked: {{N}}（每條須附 decision artifact 連結）

## Notes

<!-- 跨 task 追溯之說明；upstream 需求變更時之影響範圍 -->
