<div align="center">

# LINE-BOT

<p>
  A modern LINE AI assistant backend built with ASP.NET Core, integrating text conversation, image understanding, document summarization, and cloud deployment capabilities.
</p>

<p>
  <img src="https://img.shields.io/badge/.NET-10-512BD4?style=flat-square&logo=dotnet&logoColor=white" alt=".NET 10" />
  <img src="https://img.shields.io/badge/ASP.NET_Core-Web_API-5C2D91?style=flat-square&logo=dotnet&logoColor=white" alt="ASP.NET Core Web API" />
  <img src="https://img.shields.io/badge/LINE-Messaging_API-06C755?style=flat-square&logo=line&logoColor=white" alt="LINE Messaging API" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker Ready" />
  <img src="https://img.shields.io/badge/AI-Multi--Provider_Integration-111111?style=flat-square" alt="AI Multi-Provider Integration" />
</p>

<p>
  A more natural interaction experience, a more reliable document summarization pipeline, and a backend architecture closer to production-ready requirements.
</p>

</div>

---

## Product Overview

LINE-BOT is an AI assistant backend service that uses the LINE Messaging API as its entry point, designed for the following needs:

- Natural language interaction within LINE
- Analyzing images uploaded by users
- Organizing and summarizing document files
- Reducing the risk of AI hallucination through a grounded document pipeline
- Docker-based deployment to cloud platforms

It is not just a simple webhook receiver — it is a complete backend skeleton with event signature verification, background processing, AI replies, document organization, downloadable output, and stability protection mechanisms.

---

## Why This Project

Most LINE Bot examples only do "receive a message, send a reply."

This project goes several steps further:

- Handles not only text but also images and files
- Considers not only AI calls but also throttling, caching, cooldown, and fallback
- Goes beyond summarization to produce organized, downloadable document results
- Works not only locally but also considers cloud deployment and health checks

In other words, this repository is closer to an "extensible product foundation" rather than a minimal demo.

---

## Core Capabilities

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>Text Interaction</h3>
      <p>Receives user text messages and generates AI responses, optionally supplemented by web search for more complete answers.</p>
    </td>
    <td width="33%" valign="top">
      <h3>Image Understanding</h3>
      <p>Supports receiving image messages, downloading the content, and passing it to AI for analysis to quickly extract key points and readable results.</p>
    </td>
    <td width="33%" valign="top">
      <h3>Document Summarization</h3>
      <p>Supports text-based files and text-extractable PDFs — performing content extraction, chunk organization, summary generation, and downloadable output.</p>
    </td>
  </tr>
</table>

---

## Product Highlights

### 1. Modern Webhook Architecture
- Built on ASP.NET Core Web API
- Verifies LINE request signatures
- Places events into a background queue to reduce synchronous processing pressure
- Dispatches to dedicated handlers based on message type

### 2. Production-Oriented Stability Design
- Per-user throttling
- AI 429 cooldown mechanism
- AI quota exhaustion protection
- Reply caching
- Deduplication of repeated requests within short time windows
- Readiness health check endpoint

### 3. A More Trustworthy Document Processing Pipeline
- Extracts document text content first
- Performs chunk organization and grounding
- Generates AI summary at the end
- Reduces the risk of the model diverging from the source material

### 4. Deployable, Extensible, and Maintainable
- Dockerfile included
- Suitable for deployment on Render, Railway, Azure Web App for Containers, and similar platforms
- Clear structure, easy to extend with more handlers, AI providers, and document pipelines

---

## Use Cases

This project is particularly well-suited for the following scenarios:

| Scenario | Description |
|---|---|
| Personal AI Assistant | Ask questions, get summaries and replies directly in LINE |
| Team Knowledge Organization | Upload documents for quick extraction of key points, conclusions, and action items |
| Image Content Interpretation | Send an image via LINE and quickly get analysis results |
| Custom AI Bot Backend | Use as a skeleton for your own LINE AI service |
| Cloud Deployment Showcase | Use as a production-ready, demo-ready backend portfolio project |

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

### Current Limitations
- Scanned PDFs are not yet supported
- Image-only PDFs are not yet supported
- `.docx`, `.xlsx`, `.pptx` are not yet supported
- Binary file summarization is not yet supported

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
    +-- Enqueue to background queue
            |
            v
      Dispatcher
        |       |       |
        |       |       +-- FileMessageHandler
        |       +---------- ImageMessageHandler
        +------------------ TextMessageHandler
                                |
                                +-- AI Service
                                +-- Web Search Service
                                +-- Cache / Throttle / Backoff / Merge
```
