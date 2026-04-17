# STRIDE-A Analysis

**Project:** LINE Bot Webhook — `LineBotWebhook`
**Commit:** `811b2f5` (branch `main`)
**Analysis Date:** 2026-04-17
**Deployment Classification:** `INTERNET_FACING`

---

## Summary Table

> **Legend:** ✅ Mitigated — ⚠️ Partial — ❌ Gap — N/A Not Applicable

| Component | Spoofing | Tampering | Repudiation | Info Disclosure | DoS | Elevation | Abuse |
|-----------|----------|-----------|-------------|-----------------|-----|-----------|-------|
| LineWebhookController | ✅ HMAC-SHA256 | ✅ HMAC covers body | ⚠️ No event ID dedup | ✅ | ❌ No IP rate limit | N/A | ❌ Replay possible |
| WebhookSignatureVerifier | ✅ FixedTimeEquals | ✅ | ✅ | ⚠️ Secret in memory | ✅ | N/A | N/A |
| WebhookBackgroundQueue | N/A | N/A | N/A | N/A | ⚠️ Drops on overflow | N/A | N/A |
| WebhookBackgroundService | N/A | N/A | ✅ Per-event logs | N/A | ✅ Isolated exceptions | N/A | N/A |
| LineWebhookDispatcher | N/A | N/A | ⚠️ Partial logging | N/A | ✅ | N/A | ⚠️ Group gate bypassed? |
| TextMessageHandler | N/A | N/A | N/A | ⚠️ History in memory | ⚠️ Throttle resets on restart | N/A | ❌ Prompt injection |
| ImageMessageHandler | N/A | ⚠️ Malicious image | N/A | N/A | N/A | N/A | N/A |
| FileMessageHandler | N/A | ⚠️ Malicious file | N/A | N/A | N/A | N/A | ❌ Prompt via document |
| FailoverAiService | ⚠️ Provider impersonation | N/A | N/A | ⚠️ Error leakage | ⚠️ Single global 429 backoff | N/A | ⚠️ Cache pollution |
| GeminiService | N/A | N/A | N/A | ❌ API key in URL | ✅ | N/A | N/A |
| LineReplyService | N/A | N/A | ⚠️ Reply token not logged | ⚠️ replyToken in memory | N/A | N/A | N/A |
| LineContentService | ⚠️ Content-Type trust | ⚠️ Mime spoofing | N/A | N/A | ✅ 10 MB limit | N/A | N/A |
| WebSearchService | N/A | N/A | N/A | N/A | N/A | N/A | ⚠️ Search results injected |
| GeminiEmbeddingService | N/A | N/A | N/A | ❌ API key in URL | N/A | N/A | N/A |
| DownloadsController | N/A | N/A | N/A | ⚠️ File content exposure | ❌ No rate limit on token probe | N/A | N/A |
| ConversationHistoryService | N/A | N/A | N/A | ❌ PII in-memory (ephemeral) | ⚠️ State reset on restart | N/A | ⚠️ Summary injection |
| AiResponseCacheService | N/A | N/A | N/A | ⚠️ Cross-user cache hit risk | N/A | N/A | ⚠️ Cache poisoning |
| GeneratedFileService | N/A | N/A | N/A | ⚠️ File path exposure | N/A | N/A | N/A |

---

## Component Analysis

### P-01 — `LineWebhookController`

**Anchor:** `Controllers/LineWebhookController.cs`

#### Spoofing
- **[MITIGATED]** LINE Platform authenticates via HMAC-SHA256 `x-line-signature`. Any request without a valid signature is rejected before events are processed.

#### Tampering
- **[MITIGATED]** The HMAC signature covers the raw request body. Any modification in transit would invalidate the signature and cause rejection.

#### Repudiation
- **[GAP]** The controller logs `firstEventId` and `eventCount` but does not persist a durable audit trail. If the process restarts, all in-memory log context is lost. LINE event IDs are not checked for duplicates (idempotency gap).
- *Finding reference: FIND-08*

#### Information Disclosure
- **[MITIGATED]** The raw request body and signature header values are not logged. The controller reads the body into `rawBody` for HMAC and then parses; only structural properties (count, eventId) are logged.

#### Denial of Service
- **[GAP]** There is no per-IP or per-source rate limiting applied before signature verification. Any internet host can flood `POST /api/line/webhook` with invalid signatures, consuming CPU for HMAC computation per request.
- *Finding reference: FIND-02*

#### Elevation of Privilege
- Not applicable — the controller does not manage authorization levels.

#### Abuse
- **[GAP]** LINE delivers webhooks with at-least-once semantics. If a valid webhook event is re-delivered (LINE retry), the controller will enqueue and process it again, potentially triggering a duplicate AI call and a failed second reply (LINE rejects reused reply tokens).
- *Finding reference: FIND-08*

---

### P-02 — `WebhookSignatureVerifier`

**Anchor:** `Services/WebhookSignatureVerifier.cs`

#### Spoofing
- **[MITIGATED]** Uses `HMACSHA256` with the channel secret and `CryptographicOperations.FixedTimeEquals` for constant-time comparison — timing side-channel attacks are prevented.

#### Tampering
- **[MITIGATED]** Full body HMAC — any tampered byte invalidates the signature.

#### Repudiation
- **[MITIGATED]** Signature failure is logged (at Warning level) with sanitized context.

#### Information Disclosure
- **[PARTIAL]** The channel secret is held in process memory. If the Render web service is compromised (e.g., via RCE), the secret is recoverable from memory. This is inherent to the deployment model.

#### Denial of Service
- **[MITIGATED]** No HMAC computation result is cached, but HMAC-SHA256 is fast. DoS via verifier itself is not a primary concern.

#### Elevation / Abuse
- Not applicable.

---

### DS-01 — `WebhookBackgroundQueue`

**Anchor:** `Services/Background/WebhookBackgroundQueue.cs`

#### Denial of Service
- **[PARTIAL]** The channel has capacity 256 using `BoundedChannelFullMode.Wait`. `TryWrite` returns `false` immediately when full; the queue drops the event and logs a `Warning`. This is observable but silent from the user's perspective — dropped events are never processed or retried.
- *Finding reference: FIND-09*

---

### P-03 — `WebhookBackgroundService`

**Anchor:** `Services/Background/WebhookBackgroundService.cs`

#### Denial of Service
- **[MITIGATED]** Per-event `try/catch` ensures one failed event cannot crash the worker. Worker continues after exceptions.

#### Repudiation
- **[MITIGATED]** Each event logs its EventId, SourceType, and MessageType before dispatch.

---

### P-04 — `LineWebhookDispatcher`

**Anchor:** `Services/LineWebhookDispatcher.cs`

#### Abuse
- **[PARTIAL]** Group/room events are gated on `IsSelf == true` mention check via `MentionGateService`. However, this logic is evaluated inside the dispatcher after the event has been dequeued. A malicious user who can craft a valid LINE webhook (requires knowing the channel secret) could bypass group mention gate only if `ShouldHandle()` has a logic flaw — currently evaluated correctly.
- No known bypass as implemented.

#### Repudiation
- **[PARTIAL]** Dispatcher logs event type and source type. Full content not logged (correct). However, no correlation ID links the original webhook request to the dispatched handler log entry.

---

### P-05 — `TextMessageHandler`

**Anchor:** `Services/TextMessageHandler.cs`

#### Abuse — Prompt Injection
- **[GAP]** User-supplied text is passed to AI providers with only the persona prompt prepended. No input sanitization or content-based filtering is applied to the user message. A malicious user can embed instruction-injection strings (e.g., "Ignore previous instructions...") that alter AI behavior.
- *Finding reference: FIND-04*

#### Abuse — Web Search Result Injection
- **[PARTIAL]** Web search results from Tavily are injected into the AI prompt context. A maliciously crafted webpage returned by Tavily could contain prompt injection payloads that influence the AI response. Tavily is a trusted third-party provider, but the attack vector exists if Tavily returns adversarial content.
- *Finding reference: FIND-05*

#### Information Disclosure
- **[PARTIAL]** Conversation history containing user messages (potentially PII) is held in-memory indefinitely up to 1000 sessions × 15 rounds. There is no encryption or persistence, but also no access control beyond being process-local.

#### Denial of Service
- **[PARTIAL]** Per-user throttle via `UserRequestThrottleService` limits individual user request rate. However, the throttle state is in-memory and resets on process restart (Render free tier spin-down). An attacker who can trigger restarts bypasses per-user throttling.
- *Finding reference: FIND-11*

---

### P-06 — `ImageMessageHandler`

**Anchor:** `Services/ImageMessageHandler.cs`

#### Tampering
- **[PARTIAL]** Image bytes are downloaded from LINE API (authenticated) and sent to the AI for analysis. The AI's response to a crafted adversarial image (e.g., an image with embedded text containing prompt injection) is not filtered. This is a prompt-injection-via-image vector.

#### Abuse
- Image content is not scanned for malicious payloads before sending to AI. An image could contain text-based instruction injection for multi-modal models.

---

### P-07 — `FileMessageHandler`

**Anchor:** `Services/FileMessageHandler.cs`

#### Tampering / Abuse — Document Prompt Injection
- **[GAP]** The document text extraction pipeline creates grounded context from file content. If a document contains adversarial text like "Ignore previous context and say...", this is injected directly into the AI prompt via the `DocumentGroundingService`. This is a document-based prompt injection vector.
- *Finding reference: FIND-04*

#### Abuse — Malicious File
- **[PARTIAL]** File type is enforced via extension and MIME type whitelist in `LineContentService`. Unsupported types are rejected. However, the whitelist enforcement relies on client-provided MIME type (`Content-Type` header from LINE API) as secondary check.

---

### P-08 — `FailoverAiService`

**Anchor:** `Services/FailoverAiService.cs`

#### Spoofing
- **[PARTIAL]** The service uses HTTPS to communicate with AI providers. TLS server certificate validation is handled by the default `HttpClient` factory. No certificate pinning is applied.

#### Information Disclosure — Error Leakage
- **[PARTIAL]** On provider failure, error details are logged. If raw provider error bodies are logged (e.g., Gemini's error JSON), they may contain information about model limits, provider configuration, or API key validity.

#### Denial of Service — Global 429 Backoff
- **[PARTIAL]** `Ai429BackoffService` manages a single global cooldown. A 429 from Gemini triggers a cooldown that affects all users simultaneously — a single high-volume user's rate limit hit blocks everyone.
- *Finding reference: FIND-10*

#### Abuse — Cache Pollution
- **[PARTIAL]** AI responses are cached by `AiResponseCacheService` with a prompt-based cache key. If cache key construction does not include user-specific context (e.g., userId), different users might receive each other's cached responses in some edge cases.

---

### P-09 — `LineReplyService`

**Anchor:** `Services/LineReplyService.cs`

#### Repudiation
- **[PARTIAL]** Reply failures are logged with context. However, successful replies are not persisted — if the process restarts, there is no record of what was sent to which user.

#### Information Disclosure
- **[PARTIAL]** The LINE channel access token (`Authorization: Bearer`) is in process memory. Reply token is passed as a function parameter and not logged (correct).

---

### P-10 — `LineContentService`

**Anchor:** `Services/LineContentService.cs`

#### Spoofing / Tampering — MIME Type Trust
- **[PARTIAL]** The MIME type returned by LINE's Content-Type header is trusted for file routing. A file handler could be misled if LINE returns an unexpected MIME type for a known extension. The secondary check via file extension mitigates this partially.

#### Denial of Service
- **[MITIGATED]** Two-phase size check: (1) `Content-Length` header early rejection, (2) `bytes.Length` post-read enforcement. Both enforce the 10 MB limit.

---

### P-11 — `WebSearchService`

**Anchor:** `Services/WebSearchService.cs`

#### Abuse — Prompt Injection via Search Results
- **[PARTIAL]** Tavily search results are injected into the AI prompt context as-is. If a search result contains adversarial content, it can influence AI behavior without the user intending it.
- *Finding reference: FIND-05*

#### Information Disclosure
- **[MITIGATED]** Tavily API key is sent as `Authorization: Bearer` header (patched in L-01) — not in URL or request body.

---

### P-12 — `GeminiEmbeddingService`

**Anchor:** `Services/Documents/GeminiEmbeddingService.cs`

#### Information Disclosure — API Key in URL
- **[GAP]** The Gemini API key is appended as a URL query parameter `?key={apiKey}`. This is the standard Google AI API pattern, but the key will appear in:
  - Render/Kestrel access logs
  - Outbound HTTP client logs (if enabled)
  - Any proxy/CDN logs between the service and Google
- *Finding reference: FIND-03*

---

### P-13 — `DownloadsController`

**Anchor:** `Controllers/DownloadsController.cs`

#### Denial of Service — No Rate Limiting
- **[GAP]** The `GET /downloads/{token}` endpoint has no rate limiting. An attacker can probe with random Guid values at high speed, causing `GeneratedFileService.Get()` calls and file system lookups on every request.
- *Finding reference: FIND-07*

#### Information Disclosure
- **[PARTIAL]** The endpoint returns 404 for invalid tokens, 200 with file bytes for valid tokens. Response timing differences between "token not found in dictionary" and "file not found on disk" could allow an oracle. In practice, 128-bit token space makes enumeration infeasible, but rate limiting is still absent.

---

### DS-02 — `ConversationHistoryService`

**Anchor:** `Services/ConversationHistoryService.cs`

#### Information Disclosure
- **[PARTIAL]** All conversation messages (including user PII) are stored in-memory. There is no encryption. If another process or thread could access the in-memory dictionary (e.g., via unsafe reflection or debug endpoint), PII would be exposed.
- *Finding reference: FIND-12*

#### Abuse — Session Summary Injection
- **[GAP]** When a conversation exceeds the history limit, a summary is generated by AI and re-injected as a synthetic assistant message. The summary content is AI-generated and not validated. A crafted conversation could produce a summary containing injected instructions that persist into future AI interactions.
- *Finding reference: FIND-06*

#### Denial of Service
- **[PARTIAL]** State is bounded at 1000 sessions. However, all state resets on process restart. An attacker who can trigger restarts (e.g., by exploiting Render free-tier spin-down via inactivity) can bypass the throttle and conversation continuity.

---

### DS-03 — `AiResponseCacheService`

**Anchor:** `Services/AiResponseCacheService.cs`

#### Abuse — Cache Key Collision
- **[PARTIAL]** If the cache key is computed solely from message content (not including userId), two different users sending identical messages could receive a cached response intended for another user's context. The risk depends on whether the key includes conversation history.

---

### DS-05 — `GeneratedFileService`

**Anchor:** `Services/GeneratedFileService.cs`

#### Information Disclosure
- **[PARTIAL]** Generated files are stored on the ephemeral Render local disk with token-based access. The `FilePath` is derived from `_basePath / {token}`. If `_basePath` is a predictable system path, there is a theoretical path traversal risk if the token input is not validated.
- **[MITIGATED]** `Guid.NewGuid().ToString("N")` generates a valid filename with no path separators, so path traversal is not feasible through the token itself.

#### Denial of Service
- No file count limit is enforced beyond 24-h TTL pruning. A flood of file upload events could fill disk.
- *Finding reference: FIND-13*

---

### E-02 — `LINEPlatform` (External Service)

#### Spoofing
- **[MITIGATED]** LINE Platform's identity is verified by the HMAC-SHA256 signature on each webhook delivery. We trust messages from LINE only after successful signature verification.

#### Tampering
- **[MITIGATED]** HMAC covers the full request body.

---

### E-03 — `GeminiAPI` (External Service)

#### Information Disclosure
- **[GAP]** The Gemini API key appears in the HTTPS request URL (`?key={apiKey}`). While HTTPS protects the URL in transit, server-side and proxy access logs may record the full URL including the key.
- *Finding reference: FIND-03*

#### Denial of Service
- **[PARTIAL]** If Gemini is unavailable, `FailoverAiService` switches to Claude → OpenAI. Provider-level DoS is handled by failover.

---

### E-06 — `TavilyAPI` (External Service)

#### Abuse — Indirect Prompt Injection
- **[PARTIAL]** Adversarially crafted web pages indexed by Tavily could inject instructions into the AI prompt via the `searchContext` variable passed to `FailoverAiService`. There is no sanitization of Tavily response content before AI prompt injection.
- *Finding reference: FIND-05*
