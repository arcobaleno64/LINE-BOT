# LINE Messaging API 最大限度整合方案

> 基於 LINE Messaging API 官方文件完整分析，對照本 Bot 現有架構，建構可行的最大限度整合藍圖。

---

## 一、功能全景：已實現 vs 未實現

### ✅ 已實現（12 項）

| # | 功能 | 實作位置 | 備註 |
|---|------|---------|------|
| 1 | 文字訊息接收 | `TextMessageHandler.cs` | 含 @mention 群組篩選 |
| 2 | 圖片訊息接收 | `ImageMessageHandler.cs` | 限 1-to-1 |
| 3 | 檔案訊息接收 | `FileMessageHandler.cs` | 限 1-to-1，支援 txt/md/csv/json/xml/log/pdf |
| 4 | 純文字回覆 | `LineReplyService.cs` | 自動分割（5000 字上限，最多 5 則） |
| 5 | Quick Reply | `QuickReplySuggestionParser.cs` | AI 生成，最多 3 個，每個 ≤20 字 |
| 6 | AI 多提供商 Failover | `FailoverAiService.cs` | Gemini → OpenAI → Claude |
| 7 | 對話記憶 | `ConversationHistoryService.cs` | 15 輪，480 分鐘自動摘要 |
| 8 | Web 搜尋 | `WebSearchService.cs` | Tavily API |
| 9 | Webhook 簽名驗證 | `WebhookSignatureVerifier.cs` | HMAC-SHA256 |
| 10 | 背景佇列處理 | `WebhookBackgroundService.cs` | 非同步事件處理 |
| 11 | 429 回退 / 快取 / 合併 | 多個 Service | 完整保護層 |
| 12 | 健康檢查端點 | `Program.cs` | `/health`, `/ready`, `/` |

### ❌ 未實現（按整合價值排序）

| # | 功能 | 1-to-1 | 群組 | 整合優先度 | 說明 |
|---|------|--------|------|-----------|------|
| 1 | **Flex Message（回覆）** | ✅ | ✅ | 🔴 極高 | 結構化卡片，取代純文字牆 |
| 2 | **Loading Indicator（讀取動畫）** | ✅ | ✅ | 🔴 極高 | AI 回覆延遲時顯示「思考中」 |
| 3 | **Postback 事件處理** | ✅ | ✅ | 🔴 極高 | 按鈕回傳，Flex/Template 必備 |
| 4 | **Sticker 回覆** | ✅ | ✅ | 🟡 高 | 增加人格情感表達 |
| 5 | **Rich Menu（固定選單）** | ✅ | ✅* | 🟡 高 | 常用功能入口（*群組顯示預設選單） |
| 6 | **Follow / Join 事件** | 分別支援 | 分別支援 | 🟡 高 | 歡迎訊息 |
| 7 | **Template Message（回覆）** | ✅ | ✅ | 🟢 中 | Confirm/Buttons/Carousel |
| 8 | **Quote（引用回覆）** | ✅ | ✅ | 🟢 中 | 群組中明確「回覆哪則」 |
| 9 | **Sticker 接收識別** | ✅ | ✅ | 🟢 中 | 讀取用戶貼圖情緒 |
| 10 | **Location 接收** | ✅ | ✅ | 🟢 中 | 位置相關推薦 |
| 11 | **Sender 自訂名稱/圖示** | ✅ | ✅ | 🟢 中 | 回覆時自訂顯示名 |
| 12 | **Text v2 + Mention** | ✅ | ✅ | 🟢 中 | 群組中 @提及用戶 |
| 13 | **Image 回覆** | ✅ | ✅ | ⚪ 低 | 需自行 host 圖片 |
| 14 | **Push API** | ✅ | ✅ | ⚪ 低 | 主動推送（需更多用例） |
| 15 | **Unsend 事件** | ✅ | ✅ | ⚪ 低 | 尊重撤回意圖 |
| 16 | **Video / Audio 接收** | ✅ | ✅ | ⚪ 低 | 需額外轉碼/處理能力 |
| 17 | **Emoji（LINE 專屬）** | ✅ | ✅ | ⚪ 低 | 傳送 LINE 原生表情 |
| 18 | **Imagemap** | ✅ | ✅ | ⚪ 低 | 低需求，Flex 可替代 |
| 19 | **Narrowcast / Broadcast** | ✅ | ❌ | ⚪ 低 | 大量推播（非教學情境核心） |
| 20 | **Coupon** | ✅ | ✅ | ⚪ 低 | 非本 Bot 情境 |
| 21 | **Beacon** | ✅ | — | ⚪ 低 | 需硬體裝置 |
| 22 | **Account Link** | ✅ | — | ⚪ 低 | 帳號綁定 |
| 23 | **Membership** | ✅ | — | ⚪ 低 | 付費會員制 |

---

## 二、群組聊天室相容性警告

### 🚫 群組/多人聊天室 **不支援** 的功能（絕對不能架構）

| 功能 | 原因 |
|------|------|
| Follow / Unfollow 事件 | 群組不產生此事件（僅 1-to-1） |
| Video `trackingId`（影片觀看完成事件） | 群組不產生 `videoPlayComplete` 事件 |
| Per-user Rich Menu | 群組中無法針對特定用戶切換 Rich Menu |
| Narrowcast | 無法以 groupId/roomId 為目標 |
| Multicast | 不能傳送至群組/多人聊天 |

### ⚠️ 群組中 **行為不同** 的功能

| 功能 | 1-to-1 行為 | 群組行為 | 注意事項 |
|------|------------|---------|---------|
| Message 事件 | 所有訊息觸發 | 所有訊息觸發（需自行 mention gate） | 已實作 ✅ |
| Rich Menu | 按用戶顯示 | 僅顯示 default rich menu | 設計時需考量 |
| Push Message | 以 userId 為目標 | 以 groupId 為目標，全員可見 | 隱私考量 |
| Loading Indicator | 對單一用戶顯示 | 對整個聊天室顯示 | 可接受 |
| Sender 自訂 | 顯示自訂名/圖示 | 同上 | 可用 ✅ |
| Join / Leave 事件 | ❌ | Bot 加入/離開群組 | 可做歡迎訊息 |
| Member join/leave | ❌ | 成員加退 | 可做通知 |
| Quote（引用） | 可用 | 可用 | 群組中更有價值 |

### ✅ 群組中完全相容的功能

所有 **訊息類型**（Text、Flex、Template、Sticker、Image、Video、Audio、Location、Imagemap）在群組均可使用。Quick Reply 在群組也完全支援。

---

## 三、整合藍圖（分階段）

### Phase 1：體驗升級（影響最大、風險最低）

#### 1.1 Loading Indicator（讀取動畫）
```
POST /v2/bot/chat/loading/start
Body: { "chatId": "{userId or groupId}", "loadingSeconds": 20 }
```
- **觸發時機**：收到訊息、開始 AI 處理前
- **效果**：用戶看到「...」動畫，知道 Bot 正在思考
- **實作位置**：`TextMessageHandler.cs`、`ImageMessageHandler.cs`、`FileMessageHandler.cs`
- **群組相容**：✅ 完全相容
- **估計改動**：新增 `LoadingIndicatorService.cs` + 各 Handler 加一行呼叫

#### 1.2 Flex Message（結構化回覆）
- **用途**：文件摘要卡片、選項比較表、搜尋結果呈現
- **取代**：長篇純文字牆 → 帶標題/分隔線/按鈕的卡片
- **群組相容**：✅ 完全相容
- **注意**：需設定 `altText`（舊版 LINE 或通知列顯示用）
- **建議起步**：
  - 文件摘要 → Bubble（header + body + footer with download button）
  - 方案比較 → Carousel（多 Bubble 橫滑）
  - Web 搜尋結果 → Bubble with 來源連結按鈕

#### 1.3 Postback 事件處理
- **必要性**：Flex/Template 的按鈕回傳依賴此事件
- **webhook event type**：`postback`
- **實作**：在 `LineWebhookDispatcher` 新增 `postback` 事件路由
- **data 格式建議**：`action=xxx&param=yyy`（URL query string 風格）
- **群組相容**：✅ 完全相容

#### 1.4 Quick Reply 擴充 Action 類型
目前僅使用 `message` action，可擴充為：
| Action | 用途 | 群組相容 |
|--------|------|---------|
| `postback` | 隱藏指令（用戶不可見） | ✅ |
| `uri` | 開啟連結 | ✅ |
| `datetimepicker` | 選擇日期時間 | ✅ |
| `camera` | 開啟相機 | ✅ |
| `cameraRoll` | 開啟相簿 | ✅ |
| `location` | 傳送位置 | ✅ |
| `clipboard` | 複製文字 | ✅ |

**Quick Reply 上限**：最多 13 個按鈕（目前僅用 3 個）

---

### Phase 2：人格深化（情感 + 互動）

#### 2.1 Sticker 回覆
- **用途**：施學琦人格的情感表達
  - 回答完畢 → 微笑貼圖
  - 鼓勵學生 → 加油貼圖
  - 幽默場景 → 趣味貼圖
- **實作**：`LineReplyService` 新增 `ReplyWithStickerAsync`
- **群組相容**：✅
- **注意**：需查 [Sticker List](https://developers.line.biz/en/docs/messaging-api/sticker-list/) 選用可傳送的貼圖

#### 2.2 Follow / Join 歡迎訊息
- **Follow 事件**（1-to-1）: 用戶加好友 → 發送自我介紹 Flex Message
- **Join 事件**（群組）: Bot 加入群組 → 簡短自我介紹 + 使用說明
- **實作**：`LineWebhookDispatcher` 新增事件路由
- **群組相容**：Follow ❌（僅 1-to-1）/ Join ❌（僅群組）→ 各自對應場景，無衝突

#### 2.3 Sender 自訂名稱與圖示
```json
{
  "type": "text",
  "text": "Hello!",
  "sender": {
    "name": "施學琦",
    "iconUrl": "https://example.com/avatar.png"
  }
}
```
- **效果**：回覆時顯示施學琦名字 + 自訂頭像，而非 LINE Official Account 原始名稱
- **群組相容**：✅
- **限制**：name ≤ 20 字，不能含 "LINE" 等保留字

#### 2.4 Sticker 接收識別
- **用途**：用戶傳貼圖時，Bot 能讀取 emoji keywords 判斷情緒/意圖
- **webhook**：`message.type = "sticker"`，含 `packageId`、`stickerId`、`keywords[]`
- **回應策略**：根據 keywords 給出符合施學琦人格的回覆
- **群組相容**：✅（但需遵守 mention gate 規則？或視為主動互動？）

---

### Phase 3：群組功能強化

#### 3.1 Quote 引用回覆
```json
{
  "type": "text",
  "text": "針對你這個問題...",
  "quoteToken": "q3Plxr4AgKd..."
}
```
- **用途**：群組中明確標示回覆對象，避免對話混亂
- **實作**：webhook 中取得 `quoteToken`，reply 時帶入
- **群組相容**：✅（群組中價值更高）
- **限制**：僅 Reply / Push 端點可用，僅 text / sticker 訊息可引用

#### 3.2 Text v2 + @Mention
```json
{
  "type": "textV2",
  "text": "{user} 你問的問題很好...",
  "substitution": {
    "user": {
      "type": "mention",
      "mentionee": { "type": "user", "userId": "U..." }
    }
  }
}
```
- **用途**：群組中 @提及提問者，讓回覆更清楚
- **限制**：僅 group/room 可用（1-to-1 中不需要）
- **群組相容**：✅（專為群組設計）

#### 3.3 群組圖片/檔案處理擴展
- **現狀**：群組中圖片/檔案被跳過（`return true`）
- **方案**：群組中若 Bot 被 @mention + 附帶圖片/檔案 → 處理
- **風險**：需確認觸發條件，避免處理非目標內容
- **群組相容**：需設計 mention gate 與圖片/檔案的聯動邏輯

---

### Phase 4：進階互動

#### 4.1 Rich Menu（固定選單）
- **用途**：常駐功能入口
  - 區域 A：「問問題」→ 提示用戶輸入
  - 區域 B：「搜尋網路」→ 觸發 web search
  - 區域 C：「使用說明」→ 顯示指引 Flex
- **實作**：透過 API 建立 Rich Menu + 上傳圖片 + 設為 default
- **群組相容**：只顯示 default rich menu（無法 per-user）
- **注意**：Rich Menu 可搭配 Rich Menu Alias 實現分頁切換

#### 4.2 Template Message（結構化選項）
- **Confirm Template**：是/否確認
- **Buttons Template**：圖片 + 標題 + 多按鈕
- **Carousel Template**：多欄橫滑
- **群組相容**：✅
- **注意**：Flex Message 功能更強，Template 可作為簡單場景替代

#### 4.3 Location 接收處理
- **用途**：用戶傳位置 → 結合場景推薦
- **webhook**：`message.type = "location"`，含 `latitude`、`longitude`、`address`
- **群組相容**：✅

---

### Phase 5：營運觀測（低優先）

#### 5.1 Unsend 事件
- 用戶撤回訊息 → 清除對應快取/記憶
- **群組相容**：✅

#### 5.2 Push API
- 主動推送提醒（排程通知、作業截止等）
- 需額外觸發機制（不是 webhook 驅動）
- **群組相容**：✅（以 groupId 推送，全員可見）

#### 5.3 Insights API
- 統計數據：傳送量、好友數、人口統計
- 純觀測，不影響用戶互動

---

## 四、架構安全護欄

### 絕對禁止

| 規則 | 原因 |
|------|------|
| 不得在群組使用 Video trackingId | 群組不產生 `videoPlayComplete` 事件 |
| 不得對群組使用 Narrowcast/Multicast | API 不支援 |
| 不得假設 Per-user Rich Menu 在群組生效 | 群組只看到 default |
| 不得在 Follow handler 假設有 groupId | Follow 事件無 group context |
| 不得在 Join handler 假設有 userId | Join 事件可能無 userId |

### 設計原則

| 原則 | 說明 |
|------|------|
| **Reply-first** | 優先使用 Reply API（免費），Push API 作補充 |
| **altText 必填** | 所有 Flex/Template 必須提供有意義的 altText |
| **群組 mention gate 不可繞過** | 所有群組互動入口都必須經過 mention 驗證 |
| **Postback data 結構化** | 使用 `action=xxx&key=value` 格式，方便路由 |
| **單一聊天室同時只有一個 Loading** | 避免重複呼叫 loading/start |
| **Sticker 選用 sendable 清單** | 只使用官方可傳送的貼圖 ID |
| **Flex JSON ≤ 30KB** | 單一 Bubble 上限；Carousel ≤ 50KB |

---

## 五、技術實作要點

### 新增 Service 清單（預估）

| Service | 用途 |
|---------|------|
| `LoadingIndicatorService` | 呼叫 `POST /v2/bot/chat/loading/start` |
| `FlexMessageBuilder` | 建構 Flex Message JSON |
| `PostbackHandler` | 路由 postback event data |
| `StickerService` | 貼圖傳送 + 接收識別 |
| `RichMenuService` | Rich Menu CRUD（可首次手動設定） |
| `WelcomeMessageService` | Follow/Join 歡迎訊息 |

### 現有 Service 需修改

| Service | 修改內容 |
|---------|---------|
| `LineWebhookDispatcher` | 新增 postback / follow / join / sticker / location 事件路由 |
| `LineReplyService` | 新增 Flex / Sticker / Image reply 方法 |
| `Models/LineWebhookEvent` | 新增 postback / follow / join 事件模型 |
| `TextMessageHandler` | 加入 Loading Indicator 呼叫；支援 quoteToken 回覆 |
| `ImageMessageHandler` | 加入 Loading Indicator；考量群組 mention + 圖片聯動 |
| `FileMessageHandler` | 同上 |
| `QuickReplySuggestionParser` | 擴充 action type 解析（postback / uri / datetime） |

---

## 六、Quick Reply 最大化方案

| 目前 | 最大化 |
|------|--------|
| 僅 `message` action | 支援 7 種 action type |
| 最多 3 個 | 可擴至 13 個 |
| 僅 label + text | 可加圖示 `imageUrl` |
| AI 生成文字選項 | AI 生成 + 預設功能按鈕（📷 拍照、📍 位置、📋 複製） |

---

## 七、整合優先順序總結

```
🔴 Phase 1（體驗升級）     → Loading Indicator + Flex Message + Postback
🟡 Phase 2（人格深化）     → Sticker + Welcome + Sender 自訂
🟢 Phase 3（群組強化）     → Quote + @Mention + 群組圖片擴展
⚪ Phase 4（進階互動）     → Rich Menu + Template + Location
⚪ Phase 5（營運觀測）     → Unsend + Push + Insights
```

每個 Phase 的功能都與群組聊天室完全相容（或已排除不相容項目）。
