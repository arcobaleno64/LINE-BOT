---
name: srs
description: Software Requirements Specification template (full scale; lightweight 改用 task §Objective + §Acceptance Criteria)
version: 1.0.0
applicable_agents:
  - Claude Code
  - Codex CLI
applicable_stages:
  - intake
  - planning
applicable_scale: full
prerequisites:
  - artifacts/tasks/{{TASK_ID}}.task.md
---

# SRS: {{TASK_ID}}

> 與既有 artifact spec 之關係：本範本適用於 **full scale**（多模組功能、跨 sprint、需正式 spec 留底）。
> - lightweight scale 改用 `artifacts/tasks/{{TASK_ID}}.task.md` 之 §Objective + §Acceptance Criteria 即可。
> - SRS §Functional Requirements 與 task §Acceptance Criteria 內容應一致（建議 SRS 之 FR-N 編號 ↔ task 之 AC-N 編號）；SRS 為「正式 spec 文檔」，task 為「執行視圖」。

## Metadata

- Task ID: {{TASK_ID}}
- Version: 1.0.0
- Last Updated: {{ISO8601}}+08:00
- Status: {{draft|approved|deprecated}}

## Purpose

<!-- 此 spec 描述之系統 / module / feature 之目的；目標讀者；對應 task §Objective 之延伸 -->

## Scope

<!-- 包含 / 不包含；對應 plan §Scope；明列邊界以避 scope drift -->

## Definitions, Acronyms, Abbreviations

<!-- 領域詞彙；本 spec 使用之縮寫 -->

## Functional Requirements

<!-- FR-N 條列；建議與 task §Acceptance Criteria 之 AC-N 編號對齊 -->

- FR-1: {{describe what the system SHALL do}}
  - Priority: {{must | should | could}}
  - Verification: {{test | review | inspection | analysis}}
  - Linked AC: AC-1

## Non-Functional Requirements

<!-- NFR-N：performance / security / usability / scalability / maintainability / portability -->

- NFR-1: {{e.g., 95th percentile latency < 200ms}}
  - Category: performance
  - Verification: load test

## Constraints

<!-- 技術 / 法規 / 環境 / 時程約束；對應 task §Constraints -->

## Assumptions and Dependencies

<!-- 本 spec 成立之前提假設；外部相依 -->

## Acceptance Criteria

<!-- 對應 task §Acceptance Criteria；可直接複用 AC-N 編號 -->

- AC-1: {{verifiable criterion}}

## Open Issues

<!-- 待澄清項；對應 research §Uncertain Items -->
