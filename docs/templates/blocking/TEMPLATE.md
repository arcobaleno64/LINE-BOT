---
name: blocking
description: Template for declaring a blocked task state
version: 1.0.0
applicable_agents:
  - Codex CLI
  - Claude Code
  - Gemini CLI
applicable_stages:
  - any
prerequisites: []
---

## Role

Any agent encountering a blocking condition

## Inputs

- Current task context

## Task

Status: BLOCKED

Reason:
- Missing artifact OR conflicting inputs

Required action:
- Specify missing artifact
- Specify responsible agent

## Rules

- Do NOT continue execution

## Output

- Blocked status recorded in status artifact
