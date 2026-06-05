# Artifact Gallery

> Examples extracted from `docs/artifact_schema.md` §5; each example references its origin section.

## Example: task artifact (from §5.1)
```md
# Task: TASK-001

## Metadata
- Task ID:
- Artifact Type: task
- Owner:
- Status:
- Last Updated:

## Objective

## Background

## Inputs

## Constraints

## Acceptance Criteria

## Dependencies

## Out of Scope

## Assurance Level

## Project Adapter

## Current Status Summary
```

## Example: verify checklist scaffold (from §5.6)
```md
# Verification: TASK-001

## Metadata
- Task ID:
- Artifact Type: verify
- Owner:
- Status:
- Last Updated:

## Verification Summary

## Acceptance Criteria Checklist

## Overall Maturity

## Deferred Items

## Evidence

## Evidence Refs

## Decision Refs

## Build Guarantee

## TAO Trace

## Pass Fail Result

## Remaining Gaps

## Recommendation
```

## Example: status.json artifact (from §5.8)
```json
{
  "task_id": "TASK-001",
  "state": "planned",
  "current_owner": "Claude",
  "next_agent": "Codex",
  "required_artifacts": ["task", "research", "plan"],
  "available_artifacts": ["task", "research", "plan"],
  "missing_artifacts": [],
  "assurance_level": "mvp",
  "project_adapter": "generic",
  "open_verification_debts": [],
  "blocked_reason": "",
  "last_updated": "2026-04-09T14:30:00+08:00"
}
```
