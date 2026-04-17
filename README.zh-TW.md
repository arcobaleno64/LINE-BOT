<div align="center">

# LINE-BOT

<p>
  以 ASP.NET Core 打造、偏正式上線導向的 LINE AI 助理後端，整合文字對話、圖片理解、文件分析與雲端部署流程。
</p>

<p>
  <img src="https://img.shields.io/badge/.NET-10-512BD4?style=flat-square&logo=dotnet&logoColor=white" alt=".NET 10" />
  <img src="https://img.shields.io/badge/ASP.NET_Core-Web_API-5C2D91?style=flat-square&logo=dotnet&logoColor=white" alt="ASP.NET Core Web API" />
  <img src="https://img.shields.io/badge/LINE-Messaging_API-06C755?style=flat-square&logo=line&logoColor=white" alt="LINE Messaging API" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker Ready" />
  <img src="https://img.shields.io/badge/AI-多供應商整合-111111?style=flat-square" alt="AI 多供應商整合" />
</p>

<p>
  提供安全 webhook 驗證、背景處理、具韌性的 AI 路由，以及可觀測的維運基礎。
</p>

繁體中文 | **[English](README.md)**

</div>

---

## 文件導覽

- 一般使用者操作手冊：[USER_GUIDE.md](USER_GUIDE.md)
- 非工程師決策與審稿手冊：[USER_GUIDE_NON_ENGINEER.zh-TW.md](USER_GUIDE_NON_ENGINEER.zh-TW.md)

---

## 產品定位

LINE-BOT 是一個以 LINE Messaging API 為入口的 AI 助理後端服務，目標如下：

- 在 LINE 中進行自然語言互動
- 分析使用者上傳的圖片內容
- 整理與摘要上傳檔案
- 透過 grounded 文件流程降低 AI 憑空補述的風險
- 以雲端可部署流程與健康驗證支援上線

它不只是 webhook 接收器，而是包含簽章驗證、佇列化背景分派、多供應商 AI 備援、下載輸出與穩定性保護機制的完整後端骨架。

---

## 為什麼是這個專案

大多數 LINE Bot 範例只做到「收到訊息，回一段話」。

這個專案往前多做了幾步：

- 不只回覆文字，也處理圖片與檔案
- 不只呼叫 AI，也納入節流、快取、冷卻與短時間請求合併
- 不只做摘要，也輸出可下載整理結果
- 不只在本機可跑，也有測試關卡與部署後驗證流程

換句話說，這份儲存庫更接近「可延伸的產品基礎」，不是展示用的最小範例。

---

## 核心能力

<table>
  <tr>
    <td width="33%" valign="top">
      <h3>文字互動</h3>
      <p>處理文字訊息時包含群組提及規則、AI 回覆、可選網頁搜尋與 quick reply 建議。</p>
    </td>
    <td width="33%" valign="top">
      <h3>圖片理解</h3>
      <p>下載圖片內容後交由 AI 分析，並套用節流與冷卻保護機制。</p>
    </td>
    <td width="33%" valign="top">
      <h3>文件摘要</h3>
      <p>先做文字抽取與 grounding 片段選取，再生成摘要與暫時性下載連結。</p>
    </td>
  </tr>
</table>

---

## 產品特色

### 1. 現代化 webhook 架構
- 採用 ASP.NET Core Web API
- 在進入主要流程前先驗證 LINE 請求簽章
- 事件先進入有界背景佇列
- 由 hosted worker 消化佇列後，再依訊息/事件類型分派處理

### 2. 面向正式上線的穩定性設計
- 使用者節流控制
- AI 429 冷卻機制
- AI 配額耗盡保護
- 回覆快取
- 短時間重複請求合併
- 提供含佇列資訊的 readiness 端點

### 3. 更可信的文件處理流程
- 先抽取文件文字內容
- 再進行片段整理與 grounding
- 最後交由 AI 生成摘要
- 輸出可下載 markdown 檔（token 化短效連結）

### 4. 可部署、可延伸、可維護
- 已提供 Dockerfile
- CI 流程含 restore、test gate、映像建置、部署觸發與部署後驗證
- 結構清楚，方便擴充更多 handler、供應商與文件能力

---

## 適用情境

這個專案特別適合以下使用方式：

| 情境 | 說明 |
|---|---|
| 個人 AI 助理 | 在 LINE 中直接提問並取得精簡回覆 |
| 團隊知識整理 | 上傳檔案後快速整理重點、結論與待辦事項 |
| 圖片內容解讀 | 傳圖後取得結構化重點分析 |
| 自建 AI Bot 後端 | 作為安全且可延伸的後端基礎 |
| 部署驗證示範 | 示範測試關卡與部署後健康驗證 |

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
| `.docx` | 支援 |
| `.xlsx` | 支援 |
| `.pptx` | 支援 |

### 目前限制
- 尚不支援掃描型 PDF
- 尚不支援純圖片型 PDF
- 尚不支援二進位檔案摘要
- process-local 執行狀態不會跨實例共享

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
    +-- 放入有界背景佇列
            |
            v
      WebhookBackgroundService (hosted worker)
            |
            v
      Dispatcher
        |       |       |        \
        |       |       |         +-- Postback 處理
        |       |       +------------ FileMessageHandler
        |       +-------------------- ImageMessageHandler
        +---------------------------- TextMessageHandler（group/room 需 mention）
                                        |
                                        +-- AI Failover Service
                                        +-- Web Search Service（可選）
                                        +-- Cache / Throttle / Backoff / Merge

其他端點：
- GET /
- GET /health
- GET /ready
- GET /downloads/{token}
```
