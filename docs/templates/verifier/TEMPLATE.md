---
name: verifier
description: Subagent prompt template for the Verifier role
version: 1.0.0
applicable_agents:
  - Codex CLI
  - Claude Code
applicable_stages:
  - verifying
prerequisites:
  - task artifact
  - code artifact
  - test artifact
---

## Role

Verifier

## Inputs

- artifacts/tasks/TASK-XXX.task.md
- artifacts/code/TASK-XXX.code.md
- artifacts/test/TASK-XXX.test.md

## Task

- Validate against acceptance criteria

## Rules

- Do NOT assume test pass = requirement satisfied
- Must check each acceptance criterion

## Output

- artifacts/verify/TASK-XXX.verify.md

## Required Sections In Output

- Acceptance Criteria Checklist
- Evidence
- Pass/Fail
- TAO Trace (required when task risk ≥ 3; otherwise write `None`)

## TAO Trace Schema (per docs/agentic_execution_layer.md §2)

When required, append to verify artifact:

```md
## TAO Trace

### Step 1
- Thought Log: <reading verify obligations, identifying which AC to check>
- Action Step: <command run or artifact read>
- Observation: <verifier evidence: test output, grep result, file diff>
- Next-Step Decision: continue | halt | escalate
```

If `Observation` reveals an AC fails or evidence is insufficient, set `Next-Step Decision: halt` with `mismatch_reason:` and stop. Do NOT mark `Pass/Fail: pass` to bypass the issue — return to orchestrator with halt.
