<div align="center">

# LINE-BOT

<p>
  以 ASP.NET Core 打造的現代化 LINE AI 助理後端，整合文字對話、圖片理解、文件整理摘要與雲端部署能力。
</p>

<p>
  <img src="https://img.shields.io/badge/.NET-10-512BD4?style=flat-square&logo=dotnet&logoColor=white" alt=".NET 10" />
  <img src="https://img.shields.io/badge/ASP.NET_Core-Web_API-5C2D91?style=flat-square&logo=dotnet&logoColor=white" alt="ASP.NET Core Web API" />
  <img src="https://img.shields.io/badge/LINE-Messaging_API-06C755?style=flat-square&logo=line&logoColor=white" alt="LINE Messaging API" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker Ready" />
  <img src="https://img.shields.io/badge/AI-多供應商整合-111111?style=flat-square" alt="AI 多供應商整合" />
</p>

<p>
  更自然的互動體驗，更可靠的文件摘要流程，更貼近正式上線需求的後端架構。
</p>

繁體中文 | **[English](README.md)**

</div>

---

## 產品定位

LINE-BOT 是一個以 LINE Messaging API 為入口的 AI 助理後端服務，專為以下需求而設計：

- 在 LINE 中進行自然語言互動
- 分析使用者上傳的圖片內容
- 整理與摘要文件檔案
- 透過 grounded 文件流程降低 AI 憑空補述的風險
- 以 Docker 為基礎部署到雲端平台

它不只是單純的 webhook 接收器，而是一個具備事件驗章、背景處理、AI 回覆、文件整理、下載輸出與穩定性保護機制的完整後端骨架。

---

## 為什麼是這個專案

大多數 LINE Bot 範例只做到「收到訊息，回一段話」。

這個專案往前多做了幾步：

- 不只回覆文字，也處理圖片與檔案
- 不只呼叫 AI，也考慮節流、快取、冷卻與備援
- 不只做摘要，也把文件整理成可下載成果
- 不只可在本機執行，也考慮雲端部署與健康檢查

換句話說，這份儲存庫更接近「可延伸的產品基礎」，不是展示用的最小範例。

---

## 核心能力

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>文字互動</h3>
      <p>接收使用者文字訊息，結合 AI 回覆流程，必要時搭配網頁搜尋補充背景資訊，提供更完整的回答。</p>
    </td>
    <td width="33%" valign="top">
      <h3>圖片理解</h3>
      <p>支援接收圖片訊息，下載內容後交由 AI 分析，快速整理圖片重點與可讀結果。</p>
    </td>
    <td width="33%" valign="top">
      <h3>文件摘要</h3>
      <p>支援文字型檔案與可直接擷取文字的 PDF，完成內容抽取、片段整理、摘要生成與下載檔輸出。</p>
    </td>
  </tr>
</table>

---

## 產品特色

### 1. 現代化 webhook 架構
- 採用 ASP.NET Core Web API
- 驗證 LINE 請求簽章
- 將事件放入背景佇列處理，降低同步處理壓力
- 依訊息類型分派到專屬 handler

### 2. 面向正式上線的穩定性設計
- 使用者節流控制
- AI 429 冷卻機制
- AI 配額耗盡保護
- 回覆快取
- 短時間重複請求合併
- readiness 健康檢查端點

### 3. 更可信的文件處理流程
- 先抽取文件文字內容
- 再進行片段整理與 grounding
- 最後交由 AI 生成摘要
- 降低模型脫離原文自行補完的風險

### 4. 可部署、可延伸、可維護
- 已提供 Dockerfile
- 適合部署到 Render、Railway、Azure Web App for Containers 等平台
- 結構清楚，方便擴充更多 handler、更多 AI 供應商與更多文件流程

---

## 適用情境

這個專案特別適合以下使用方式：

| 情境 | 說明 |
|---|---|
| 個人 AI 助理 | 在 LINE 中直接提問、取得摘要與回覆 |
| 團隊知識整理 | 上傳文件後快速整理重點、結論與待辦事項 |
| 圖片內容解讀 | 透過 LINE 傳圖後快速取得分析結果 |
| 自建 AI Bot 後端 | 作為自己的 LINE AI 服務骨架 |
| 雲端部署展示專案 | 作為可上線、可展示的後端作品集 |

---

## 支援內容

### 支援的訊息類型
| 類型 | 說明 |
|---|---|
| 文字訊息 | 對話式 AI 回覆 |
| 圖片訊息 | 圖片內容分析 |
| 檔案訊息 | 文件抽取、摘要與下載檔輸出 |

### 支援的檔案格式
| 格式 | 支援狀態 |
|---|---|
| `.txt` | 支援 |
| `.md` | 支援 |
| `.csv` | 支援 |
| `.json` | 支援 |
| `.xml` | 支援 |
| `.log` | 支援 |
| `.pdf` | 支援可直接擷取文字的 PDF |

### 目前限制
- 尚不支援掃描型 PDF
- 尚不支援純圖片型 PDF
- 尚不支援 `.docx`、`.xlsx`、`.pptx`
- 尚不支援二進位檔案摘要

---

## 系統架構

```text
LINE Platform
    |
    v
POST /api/line/webhook
    |
    +-- 驗證 x-line-signature
    +-- 解析 webhook events
    +-- 放入背景佇列
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
