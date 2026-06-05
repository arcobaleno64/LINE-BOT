---
name: bootstrap-prompt-builder
description: "5-stage interactive flow that produces a tailored BOOTSTRAP_PROMPT for council-forge artifact-first multi-agent workflow. Use this skill when a user wants to start a new project, onboard an external chat (ChatGPT / Claude Chat) to council-forge, or generate a bootstrap message scaled to project size and work type. Triggers: 'bootstrap', 'new project', '開新專案', '外部 chat 接入'."
license: Same terms as the council-forge repository (root LICENSE)
metadata:
  version: 1.0.0
  source_repo: arcobaleno64/council-forge
---

# Bootstrap Prompt Builder

**When this skill starts, display this banner before doing anything else:**

```
Bootstrap Prompt Builder v1.0.0 — council-forge artifact-first workflow
```

Help the user produce a tailored BOOTSTRAP_PROMPT for `council-forge` artifact-first workflow without copying boilerplate they don't need. The user describes their project once; this skill walks five short stages and outputs a ready-to-paste prompt sized to their actual scope.

## When to Use

- User says: "bootstrap", "new project", "開新專案", "外部 chat 接入", "啟動 council-forge", "我要開新案子"
- User shares a project goal but is unsure which template / agent / variant to start with
- User pastes a short description and asks "what's the right BOOTSTRAP_PROMPT for this?"

This skill works in any chat surface that can read user messages and emit markdown. It does **not** require Python, file system access, or CLI execution. Anything that mentions a CLI command in this document is **Optional** — a fallback table is always provided for chat-only environments.

## What This Skill Produces

A single markdown code block containing the user's BOOTSTRAP_PROMPT, sized as one of three variants:

| Variant | Approx. lines | Suitable for |
|---|---|---|
| minimal | 8-15 | solo / POC / single-file feature; risk ≤ 2 + context cost = S |
| standard | 30-60 | feature with plan + research; cross 2-3 files |
| full | 80-130 | cross-module / migration / security; needs SRS / RTM / Tavily |

The single source of truth for prompt content is the repository's `BOOTSTRAP_PROMPT.md`. This skill **never** copies its text verbatim — it points the user at the source file and instructs them which sections to keep, fill, or remove based on the five stages below.

---

## Phase 1: Identify Project Scale

Ask the user these five questions in order. Skip questions whose answer is already in their initial message.

1. **Codebase size**: How many source lines, roughly? (estimate: <500 / 500-5000 / 5000-50000 / >50000)
2. **Module count**: How many top-level modules / packages / services?
3. **Team**: solo / 2-5 / 6+ ?
4. **External dependencies**: any API keys, third-party services, or upstream forks involved?
5. **Scope clarity**: is the first task fully defined (tight AC) or exploratory (need research first)?

### Compute risk score and context cost

Apply the council-forge routing rubric (from `CLAUDE.md` §Agent Routing Policy).

**Risk Score (0-10)** — sum the points, cap at 10:

| Signal | Points if present |
|---|---|
| External API / network dependency | +1 |
| Security / secrets / credential handling | +2 |
| Schema or migration touched | +2 |
| Cross-module / cross-repo writes | +2 |
| Verification difficulty (no automated check) | +1 |
| Scope ambiguity (research needed first) | +2 |

**Context Cost**:
- `S`: ≤ 3 files in scope
- `M`: 4-10 files or multi-stage docs
- `L`: > 10 files, cross-module, or long artifacts

### Map to scale variant

| Risk + Context | Scale variant | Default agents |
|---|---|---|
| risk ≤ 2 AND context = S | minimal | Claude direct |
| 3 ≤ risk ≤ 5, context = M | standard | Claude orchestrate, Codex implement |
| risk ≥ 6 OR context = L | full | Claude orchestrate, Codex implement, Gemini research, Tavily allowed |

Tell the user: "Based on your answers, your scale is **<minimal | standard | full>**."

---

## Phase 2: Identify Work Type

Ask: "Which best describes the first task?"

- **Bug fix**: reproduce-then-fix; uses Bug Report + Debug runbook (full only)
- **Feature**: new functionality; uses Feature Request + PR description; SRS / ADR at standard+
- **Refactor**: structure change without behavior change; ADR at standard+
- **Migration**: schema / dependency / framework change; ADR + RTM at full
- **Experiment / spike**: time-boxed exploration; minimal artifacts only

### Map to required templates

Use this matrix (mirrors `docs/lightweight_mode_rules.md` §3.5):

| Work type | minimal | standard adds | full adds |
|---|---|---|---|
| Bug fix | task + code + verify + Bug report | + Debug runbook | + RTM if ≥3 modules touched |
| Feature | task + plan + code + verify + Feature request + PR description | + SRS (User Story) + ADR if architectural | + SRS (full IEEE 29148) + RTM |
| PR (external contribution) | task + code + verify + PR description | + decision (if architectural) | + ADR |
| Refactor | task + plan + code + verify | + ADR if architectural | + RTM (recompute coverage) |
| Migration | task + plan + code + verify + ADR | + RTM | + SRS (full) + RTM (full coverage) |
| Experiment | task + code (lightweight gate) | n/a | n/a |

Record which templates the user needs.

---

## Phase 3: Identify Agent Configuration

Ask three yes/no questions:

1. "Will you use **Codex CLI** for implementation?" (yes for risk ≥ 3 or context cost ≥ M)
2. "Will you use **Gemini CLI** for research / spec comparison?" (yes if external standards / multi-source research needed)
3. "Will you allow **Tavily-assisted research** through Gemini?" (yes only if Tavily CLI available locally; council-forge requires explicit dispatch authorization)

The user's answers determine which subsections of `BOOTSTRAP_PROMPT.md` §4 (Agent 配置) survive the rendering step.

| Variant | Codex | Gemini | Tavily |
|---|---|---|---|
| minimal | optional (Claude direct OK) | usually no | no |
| standard | yes | optional | optional |
| full | yes | yes | yes if available |

If any answer is "no", note it — Phase 5 will instruct the user to delete the corresponding subsection from `BOOTSTRAP_PROMPT.md` §4.

---

## Phase 4: Identify Output Templates

Show the user the 13 available templates in council-forge. Mark which ones their work type + scale needs (from Phase 2 matrix).

**council-forge template catalog** (mirrors `docs/templates/<role>/TEMPLATE.md` plus three GitHub UI surfaces):

| Template | Path | Scale | Purpose |
|---|---|---|---|
| Implementer | `docs/templates/implementer/TEMPLATE.md` | all | Codex coding subagent prompt |
| Tester | `docs/templates/tester/TEMPLATE.md` | all | Test-writing subagent prompt |
| Verifier | `docs/templates/verifier/TEMPLATE.md` | all | Verification subagent prompt |
| Reviewer | `docs/templates/reviewer/TEMPLATE.md` | all | Code review subagent prompt |
| Parallel | `docs/templates/parallel/TEMPLATE.md` | all | Parallel subagent orchestration |
| Blocking | `docs/templates/blocking/TEMPLATE.md` | all | Blocked-task declaration |
| Memory Curator | `docs/templates/memory-curator/TEMPLATE.md` | all | Gemini memory-bank draft |
| Architecture Synthesizer | `docs/templates/architecture-synthesizer/TEMPLATE.md` | all | Gemini SECI architecture guidance |
| RACI Auditor | `docs/templates/raci-auditor/TEMPLATE.md` | all | Gemini RACI audit |
| SRS | `docs/templates/srs/TEMPLATE.md` | full | Software Requirements Specification |
| RTM | `docs/templates/rtm/TEMPLATE.md` | full | Requirements Traceability Matrix |
| Debug runbook | `docs/templates/debug/TEMPLATE.md` | both | In-incident debug log |
| ADR | `docs/templates/adr/TEMPLATE.md` | standard+ | Architecture Decision Record |

Plus three GitHub UI surfaces (used at PR / Issue creation time):

| Surface | Path |
|---|---|
| PR description | `.github/PULL_REQUEST_TEMPLATE.md` |
| Bug report | `.github/ISSUE_TEMPLATE/bug_report.yml` |
| Feature request | `.github/ISSUE_TEMPLATE/feature_request.yml` |

**Optional (CLI users only)**: if the user already has council-forge cloned, they can run `python artifacts/scripts/discover_templates.py --scale <lightweight|standard|full|all>` to filter the list dynamically. External Chat users use the table above.

---

## Phase 5: Render the Prompt

Output the prompt as a single markdown code block. Tell the user:

> "Open the file `BOOTSTRAP_PROMPT.md` in your council-forge repository (or the published copy at `https://github.com/arcobaleno64/council-forge/blob/master/BOOTSTRAP_PROMPT.md`). It is the canonical 6-section template. Apply the edits below based on your **<scale variant>** result and paste the final block as the first message in your new chat."

Provide an **outline** of which sections to keep / fill / remove for each variant. Do NOT copy section text from `BOOTSTRAP_PROMPT.md` — only describe the edits.

### Variant: minimal

Use the "最小版" example in `BOOTSTRAP_PROMPT.md` (the second code block in `## 使用說明`). Replace the four placeholders:
- `【名稱】`, `【路徑】`, `【語言/框架】`, `【描述】`

Tell the user this variant skips: research artifact, premortem (lightweight gate), Tavily, Memory Bank Curator, multi-round review.

### Variant: standard

Use the main 6-section block in `BOOTSTRAP_PROMPT.md`. Edit:

| Section | Action |
|---|---|
| §1 專案資訊 | Fill all 5 placeholders |
| §2 上游 Fork 模式 | **Delete entirely** (assumes no fork; if fork exists, fill the 3 placeholders instead) |
| §3 範本來源 | Fill the path to your council-forge clone or template source |
| §4 Agent 配置 | Keep Claude + Codex subsections. Delete Gemini and Tavily subsections if Phase 3 said "no" to those |
| §5 工作規範 | Keep as-is |
| §6 第一個任務 | Fill TASK-001 placeholders (objective, background, acceptance) |

### Variant: full

Use the main 6-section block. Edit:

| Section | Action |
|---|---|
| §1 專案資訊 | Fill all 5 placeholders |
| §2 上游 Fork 模式 | Fill if fork project; delete otherwise |
| §3 範本來源 | Fill the path |
| §4 Agent 配置 | Keep all subsections (Claude, Codex, Gemini, Tavily) |
| §5 工作規範 | Keep as-is |
| §6 第一個任務 | Fill placeholders. Add a one-line note: "This task may need SRS / RTM / ADR per `docs/lightweight_mode_rules.md` §3.5" |

After rendering, also remind the user of the three template categories from Phase 4 that their work type / scale combination requires.

---

## Closing Step

After producing the rendered prompt, give the user one paragraph telling them:

1. **Paste the block as the first message** in their new Claude Code session
2. **Verify the workflow gate** by running `python artifacts/scripts/guard_status_validator.py --task-id TASK-001 --auto-classify` (Optional — only if the user has the repo cloned; otherwise Claude Code itself will run this in the new session)
3. **Templates referenced are in `docs/templates/<role>/TEMPLATE.md`** — Claude Code will fetch them on demand; the user does not need to copy template text into the BOOTSTRAP message

Do not invent CLI steps the user did not ask for. The skill ends when the rendered block is delivered.

---

## Rules This Skill Must Follow

- **Single source of truth**: `BOOTSTRAP_PROMPT.md` is canonical. This skill points at it; never quotes it.
- **No verbatim copying**: any line of `BOOTSTRAP_PROMPT.md` reproduced inside this SKILL.md beyond a one-line section title is a violation. Stage 5 outputs **edits-to-apply**, not the prompt text.
- **No required CLI**: every Python / pip / npm command in this document is in an Optional context with a markdown table fallback that works for external chat users.
- **No new frontmatter keys**: keys in the YAML header above are limited to those used by existing council-forge skills (`name`, `description`, `license`, `metadata.*`). Do not invent new keys (e.g., the `applicable_scale` key used by `docs/templates/<role>/TEMPLATE.md` belongs to a different layer and is not used here).
- **Scale name alignment**: minimal / standard / full in this skill correspond to lightweight / standard / full in `docs/lightweight_mode_rules.md` §3.5. The skill's "minimal" maps to the rules file's "lightweight"; treat them as synonyms across the two documents.

## When NOT to Use

- User already has a populated council-forge repo and a clear next task — they don't need bootstrap; they need to start the next task directly.
- User wants the workflow rules edited (use `CLAUDE.md` / `AGENTS.md` directly).
- User wants a specific artifact template (use `docs/templates/<role>/TEMPLATE.md` directly).
- User has a finished BOOTSTRAP message and wants debugging help — that's a separate task, not this skill.
