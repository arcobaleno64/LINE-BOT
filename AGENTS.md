# AGENTS.md

## Purpose

Project-specific review rules for this LINE Bot Webhook repository.

Use these rules together with the baseline review policy:

- prioritize security, correctness, data integrity, regression risk, and operability
- prefer fewer, stronger findings over broad advice
- report only concrete issues supported by evidence in the diff

This file adds repository-specific expectations so reviews stay consistent and high-signal.

## System Overview

This project is a LINE Messaging API webhook built on ASP.NET Core.

Key behaviors:

- inbound webhook endpoint: `POST /api/line/webhook`
- root probe: `GET /`
- liveness: `GET /health`
- readiness: `GET /ready`
- file download endpoint: `GET /downloads/{token}`
- LINE replies depend on short-lived `replyToken`
- text, image, and file flows are routed separately
- AI responses may use Gemini, OpenAI, or Claude with fallback behavior
- background processing uses an in-process queue and hosted worker
- some runtime state is intentionally process-local

## Critical Review Areas For This Repository

### 1. Webhook Security And Authenticity

Treat all webhook requests as untrusted until the LINE signature is verified.

Flag any change that:

- weakens or bypasses `x-line-signature` verification
- moves processing ahead of signature verification
- trusts client-provided identity or source fields without server-side checks
- logs raw signature headers, request bodies, access tokens, reply tokens, or API keys

Smallest safe expectation:

- verify signature before any meaningful processing
- reject invalid signatures with safe logging only

### 2. Reply Token Workflow Correctness

`replyToken` is short-lived and single-use in practice.

Flag any change that:

- risks delayed processing without clear handling of token expiry
- retries replies unsafely after unknown delivery state
- converts immediate reply paths into patterns likely to miss the token validity window
- swallows reply failures without actionable logs

Smallest safe expectation:

- keep reply flow observable
- preserve failure context without leaking sensitive data

### 3. Source-Type And Mention Gating

Current repository behavior intentionally differs by source and message type.

Flag any change that breaks these expectations:

- text in `group` / `room` should only be handled when the bot is mentioned
- image and file handling should not silently expand to unsupported source types without explicit approval
- unsupported message behavior must stay intentional and predictable

Treat changes here as high regression risk because they affect production-facing workflow rules.

### 4. AI Fallback, Backoff, And Capacity Safety

This codebase has explicit handling for:

- provider failover
- Gemini dual-key routing
- `429` / quota cooldown behavior
- response cache
- in-flight merge

Flag any change that:

- alters failover order without clear intent
- triggers global backoff earlier or later than before
- causes duplicate expensive AI calls by bypassing cache or merge behavior
- retries non-retryable provider failures blindly
- logs raw provider secrets or full sensitive error bodies

Smallest safe expectation:

- preserve runtime semantics unless the change explicitly intends to alter them
- make provider transitions observable with sanitized metadata only

### 5. Background Queue And Worker Safety

Webhook processing now relies on an in-process queue and background worker.

Flag any change that:

- reintroduces ad-hoc `Task.Run` request-thread fire-and-forget dispatch
- changes queue-full behavior without explicit product approval
- risks dropping events silently
- removes worker lifecycle logs or queue pressure visibility
- breaks orderly shutdown or per-item exception isolation

Review shutdown and stop behavior carefully. One failed item must not terminate the worker.

### 6. File Handling And Extraction Safety

Uploaded files are untrusted input.

Flag any change that:

- broadens supported file types without safe parsing logic
- treats binary files as trusted text
- weakens handling for scanned/image-only PDFs
- risks memory blowups by loading unusually large content without limits
- exposes generated download tokens or internal file contents in logs

Smallest safe expectation:

- maintain whitelist-based file support
- keep unsupported-file behavior safe and explicit

### 7. Document QA / Summarization Integrity

File-based AI answers must be grounded in extracted document content.

Flag any change that:

- bypasses chunk selection / grounding and goes back to naive whole-document prompting
- increases hallucination risk by removing “insufficient evidence” constraints
- loses compatibility with existing download-summary flow
- weakens handling of long documents by relying only on hard truncation

### 8. Process-Local State And Deployment Constraints

Some state is intentionally process-local:

- generated file tokens
- request throttling
- AI cooldown / backoff
- response cache
- in-flight merge
- background queue state

Flag any change that assumes these states are shared across instances when they are not.

Also flag changes that ignore current deployment constraints:

- Render web service deployment
- free-tier spin-down / cold-start behavior
- health and readiness endpoints used by uptime monitoring

## Sensitive Data Definitions For This Repository

Treat the following as sensitive and unsuitable for normal logs, errors, or URLs:

- LINE channel access token
- LINE channel secret
- LINE reply token
- LINE signature header value
- AI provider API keys, including Gemini secondary key
- full request body from webhook payloads
- raw user text when not necessary for safe diagnostics
- stable user identifiers when raw values are not needed
- generated file tokens

Prefer:

- fingerprints
- masked identifiers
- sanitized status/context fields

Do not require complete secrecy for every identifier in all cases, but report unnecessary raw exposure.

## Repository-Specific Correctness Rules

### Webhook Contract

Treat these as compatibility-sensitive:

- `POST /api/line/webhook`
- immediate `200 OK` response behavior
- existing `GET /`, `GET /health`, `GET /ready`, and `GET /downloads/{token}` routes

Any change that modifies route shape or timing semantics should be treated as high risk unless explicitly requested.

### Shared Utility Blast Radius

Raise review priority for changes in:

- `Program.cs`
- `Controllers/LineWebhookController.cs`
- `Services/FailoverAiService.cs`
- `Services/GeminiService.cs`
- `Services/LineReplyService.cs`
- `Services/LineWebhookDispatcher.cs`
- background queue / worker types
- readiness / observability services
- cache / merge / backoff / throttle services

These files affect many entry points and can create broad regressions.

### Error Handling Expectations

Flag catch blocks that:

- hide provider failures and continue unsafely
- suppress queue / worker failures without logs
- downgrade important failures to no-op behavior
- leak raw provider payloads or secrets

Expected logging context for risky failures:

- operation
- event or correlation identifier when available
- provider / handler / message type
- sanitized failure reason

### Operability Expectations

For risky changes, check whether the diff preserves or improves:

- invalid signature diagnostics without secret leakage
- reply failure visibility
- queue pressure visibility
- readiness accuracy
- provider failover visibility
- safe background worker stop behavior

Missing observability is worth reporting only when it materially weakens incident response.

## Testing Expectations For Risky Changes

When a diff changes any of the following, look for targeted validation:

- webhook signature verification
- background queue behavior
- readiness decisions
- provider failover order
- Gemini primary/secondary key routing
- `429` / quota handling
- file extraction and unsupported-file behavior
- document QA / summary pipeline
- reply failure handling

Prefer concrete scenario coverage, for example:

- invalid signature rejected
- empty events ignored safely
- queue full path
- worker survives dispatcher exception
- Gemini primary key exhausted, secondary key succeeds
- Gemini exhausted, provider failover succeeds
- scanned PDF still rejected
- document question with insufficient evidence stays conservative

## Forbidden Shortcuts

Flag these strongly when seen in diffs:

- trusting source type, mention state, or identity only because the client sent it
- moving state-changing or security-sensitive behavior to `GET`
- logging secrets or raw tokens for debugging convenience
- replacing queue behavior with ad-hoc background tasks
- bypassing throttle/backoff/cache/merge protections in hot paths
- turning unsupported file or PDF cases into best-effort parsing without guards
- silently changing user-facing workflow semantics without explicit request

## Review Output Preference For This Repository

When you report a finding on this repository, prefer:

- concrete production failure mode
- exact file / function / flow affected
- smallest safe correction
- focused validation scenario tied to LINE webhook, queue, AI fallback, or file workflow

Do not spend review budget on stylistic cleanup unless it masks a real production risk.
