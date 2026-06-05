---
name: adr
description: Architecture Decision Record template (long-form architectural decisions; standard+ scale)
version: 1.0.0
applicable_agents:
  - Claude Code
  - Codex CLI
applicable_stages:
  - planning
applicable_scale: standard
prerequisites: []
---

# ADR-{{NNNN}}: {{TITLE}}

> 與既有 artifact spec 之關係：
> - **短期 task-local 決策**請改用 `artifacts/decisions/{{TASK_ID}}.decision.md`（gate-blocking、單 task 生命週期）。
> - 本範本適用「**跨多 task / 跨季度 / 跨年**」之長期架構決策（如「採用 microservices」、「儲存層改 Postgres」、「身份認證改 OIDC」）。
> - ADR 之 Status 流為 `proposed → accepted → deprecated → superseded`；deprecated / superseded 之 ADR 須保留檔案不刪。
> - 編號 NNNN 全 repo 連續遞增，與 TASK-XXXX 編號獨立。

## Metadata

- ADR Number: {{NNNN}}
- Title: {{TITLE}}
- Date: {{ISO8601}}+08:00
- Author: {{name}}
- Supersedes: {{ADR-XXXX | none}}
- Superseded by: {{ADR-XXXX | none}}

## Status

{{proposed | accepted | deprecated | superseded by ADR-XXXX}}

## Context

<!-- 為何此決策必要；驅動因子（business / tech / regulatory / cost）；當下已知條件與限制 -->

## Decision

<!-- 採用之方案；具體可執行陳述；避免抽象用詞 -->

## Consequences

<!-- trade-offs 顯性化 -->

### Positive
- {{benefit 1}}

### Negative
- {{cost 1}}

### Neutral
- {{side-effect 1}}

## Alternatives

<!-- 其他選項與被否決之理由；每項列 Pros / Cons -->

- Alt-1: {{option}}
  - Pros: {{...}}
  - Cons: {{...}}
  - Rejected because: {{reason}}

- Alt-2: {{option}}
  - Pros: {{...}}
  - Cons: {{...}}
  - Rejected because: {{reason}}

## Implementation Notes

<!-- 對應之 task / migration plan / rollout strategy；連結至首次落地之 task artifact -->

## Review Cadence

<!-- 多久檢視此決策一次（quarterly / yearly）；觸發重審之條件 -->
