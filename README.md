<div align="center">

# LINE-BOT

<p>
  A production-oriented LINE AI assistant backend built with ASP.NET Core, integrating text conversation, image understanding, document analysis, and cloud deployment workflows.
</p>

<p>
  <img src="https://img.shields.io/badge/.NET-10-512BD4?style=flat-square&logo=dotnet&logoColor=white" alt=".NET 10" />
  <img src="https://img.shields.io/badge/ASP.NET_Core-Web_API-5C2D91?style=flat-square&logo=dotnet&logoColor=white" alt="ASP.NET Core Web API" />
  <img src="https://img.shields.io/badge/LINE-Messaging_API-06C755?style=flat-square&logo=line&logoColor=white" alt="LINE Messaging API" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker Ready" />
  <img src="https://img.shields.io/badge/AI-Multi--Provider_Integration-111111?style=flat-square" alt="AI Multi-Provider Integration" />
</p>

<p>
  A practical backend foundation with secure webhook handling, background processing, resilient AI routing, and observable operations.
</p>

**[繁體中文](README.zh-TW.md)** | English

</div>

---

## Documentation Guide

- General user guide: [USER_GUIDE.md](USER_GUIDE.md)
- Non-engineer decision and document-review guide (Traditional Chinese): [USER_GUIDE_NON_ENGINEER.zh-TW.md](USER_GUIDE_NON_ENGINEER.zh-TW.md)

---

## Product Overview

LINE-BOT is an AI assistant backend service that uses the LINE Messaging API as its entry point, designed for these goals:

- Natural language interaction within LINE
- Analyzing images uploaded by users
- Organizing and summarizing uploaded files
- Reducing hallucination risk through a grounded document pipeline
- Running a cloud-ready deployment flow with health verification

It is more than a basic webhook receiver. It includes signature verification, queue-based background dispatch, provider failover support, downloadable outputs, and runtime safeguards for stability.

---

## Why This Project

Most LINE Bot examples only do "receive a message, send a reply."

This project goes several steps further:

- Handles text, image, file, and postback events through dedicated flows
- Adds throttling, short-window merge, response cache, and cooldown protection
- Uses queue + hosted worker to avoid request-thread fire-and-forget patterns
- Adds CI test gate and post-deploy verification before considering release complete

In other words, this repository is closer to an "extensible product foundation" rather than a minimal demo.

---

## Core Capabilities

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>Text Interaction</h3>
      <p>Processes user text with mention-gate rules, AI replies, optional web search, and quick-reply suggestions.</p>
    </td>
    <td width="33%" valign="top">
      <h3>Image Understanding</h3>
      <p>Downloads image content and routes it to AI analysis with throttling and cooldown safeguards.</p>
    </td>
    <td width="33%" valign="top">
      <h3>Document Summarization</h3>
      <p>Extracts document text, selects grounded chunks, generates summary output, and provides a downloadable result link.</p>
    </td>
  </tr>
</table>

---

## Product Highlights

### 1. Modern Webhook Architecture
- Built on ASP.NET Core Web API
- Verifies LINE request signatures before any meaningful processing
- Enqueues events into a bounded background queue
- Processes queue items in a hosted worker and dispatches by message/event type

### 2. Production-Oriented Stability Design
- Per-user throttling
- AI 429 cooldown mechanism
- AI quota exhaustion protection
- Reply caching
- Deduplication of repeated requests within short time windows
- Readiness endpoint with queue-aware operational snapshot

### 3. A More Trustworthy Document Processing Pipeline
- Extracts document text content first
- Performs chunk organization and grounding
- Generates AI summary at the end
- Produces downloadable markdown output with temporary tokenized access

### 4. Deployable, Extensible, and Maintainable
- Dockerfile included
- CI workflow includes restore, test gate, image build, deploy trigger, and deployment verification
- Clear structure for extending handlers, providers, and document capabilities

---

## Use Cases

This project is particularly well-suited for the following scenarios:

| Scenario | Description |
|---|---|
| Personal AI Assistant | Ask questions and get concise responses directly in LINE |
| Team Knowledge Organization | Upload files and quickly extract highlights, conclusions, and action items |
| Image Content Interpretation | Send an image and receive structured key-point analysis |
| Custom AI Bot Backend | Reuse as a secure, extensible backend foundation |
| Deployment Validation Demo | Demonstrate test-gated CI and post-deploy health verification |

---

## Supported Content

### Supported Message Types
| Type | Description |
|---|---|
| Text message | Conversational AI reply |
| Image message | Image content analysis |
| File message | Document extraction, summarization, and downloadable output |

### Supported File Formats
| Format | Support Status |
|---|---|
| `.txt` | Supported |
| `.md` | Supported |
| `.csv` | Supported |
| `.json` | Supported |
| `.xml` | Supported |
| `.log` | Supported |
| `.pdf` | Supported for text-extractable PDFs |
| `.docx` | Supported |
| `.xlsx` | Supported |
| `.pptx` | Supported |

### Current Limitations
- Scanned PDFs are not yet supported
- Image-only PDFs are not yet supported
- Binary file summarization is not yet supported
- Process-local runtime state is not shared across instances

---

## System Architecture

```text
LINE Platform
    |
    v
POST /api/line/webhook
    |
    +-- Verify x-line-signature
    +-- Parse webhook events
    +-- Enqueue to bounded background queue
            |
            v
      WebhookBackgroundService (hosted worker)
            |
            v
      Dispatcher
        |       |       |        \
        |       |       |         +-- Postback handling
        |       |       +------------ FileMessageHandler
        |       +-------------------- ImageMessageHandler
        +---------------------------- TextMessageHandler (mention gate in group/room)
                                        |
                                        +-- AI Failover Service
                                        +-- Web Search Service (optional)
                                        +-- Cache / Throttle / Backoff / Merge

Other HTTP endpoints:
- GET /
- GET /health
- GET /ready
- GET /downloads/{token}
```
