---
name: parallel-execution
description: Orchestration template for parallel subagent execution
version: 1.0.0
applicable_agents:
  - Codex CLI
applicable_stages:
  - coding
  - testing
  - verifying
prerequisites:
  - task artifact
  - plan artifact
---

## Role

Orchestrator (Parallel Execution)

## Inputs

- Completed Implementer output

## Task

Use subagents.

1. Implementer completes code
2. Then spawn in parallel:
   - Tester
   - Verifier
   - Reviewer

## Rules

- No parallel code modification
- All outputs must be written to artifacts
- Final answer must reference artifacts only

## Output

- All parallel subagent artifacts completed
