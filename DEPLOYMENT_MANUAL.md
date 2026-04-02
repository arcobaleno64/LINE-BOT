# LINE Bot 上線手冊

## 1. 目的

本文提供部署與維運人員使用，說明本版 LINE Bot 的必要設定、上線步驟、驗證方式與常見故障排查。

## 2. 本版實際能力

- Webhook 接收：`POST /api/line/webhook`
- 1 對 1：文字 / 圖片 / 檔案
- 群組 / room：只處理被 mention 的文字
- 基本健康檢查：`GET /health`
- 檔案下載：`GET /downloads/{token}`

## 3. 必要設定

### LINE
必填：
- `Line:ChannelSecret`
- `Line:ChannelAccessToken`

### AI Provider
至少提供一組可用 API Key：
- `Ai:OpenAI:ApiKey`
- `Ai:Gemini:ApiKey`
- `Ai:Claude:ApiKey`

可選：
- `Ai:Provider`
- `Ai:FallbackProvider`

注意：
- 若沒有任何可用的 AI Provider API Key，應用啟動會失敗。

### App
可選：
- `App:PublicBaseUrl`
- `App:TimeZoneId`
- `App:UserThrottleSecondsText`
- `App:UserThrottleSecondsImage`
- `App:UserThrottleSecondsFile`
- `App:Ai429CooldownSeconds`
- `App:AiQuotaCooldownSeconds`
- `App:AiResponseCacheSeconds`
- `App:AiMergeWindowSeconds`

### Web Search
若要開啟最新資訊查詢：
- `WebSearch:Enabled=true`
- `WebSearch:TavilyApiKey=<key>`

注意：
- 搜尋功能未設定時，系統仍可啟動，只是搜尋型問題會回提示訊息。

## 4. Webhook 設定

LINE Developers Console 中請設定：
- Webhook URL：
  - `https://<public-domain>/api/line/webhook`
- 啟用 Webhook

注意：
- Bot 若在群組中使用，目前只處理 mention text
- route 不要改動，否則 LINE 端會失效

## 5. 公開網址與下載功能

若有檔案整理與下載需求，建議設定：
- `App:PublicBaseUrl=https://<public-domain>`

若未設定，系統會依 request host 與 forwarded proto 推算。

下載端點：
- `GET /downloads/{token}`

限制：
- 檔案約保留 24 小時
- 重新部署後下載連結可能失效
- 檔案索引是單機記憶體狀態

## 6. 上線後驗證

### 基本檢查
1. `GET /`
   - 預期：`LINE Bot Webhook is running`
2. `GET /health`
   - 預期：`{ "status": "ok" }`

### Webhook 驗證
1. 在 LINE Developers Console 驗證 webhook
2. 送 1 對 1 文字測試
3. 測試：
   - `現在幾點`
   - 一般文字問題
   - 一張圖片
   - 一個支援格式的文字檔
4. 若有開啟搜尋，再測：
   - `幫我查最新 AI 新聞`

### 群組驗證
1. 將 Bot 加入群組
2. 測試未 mention 不回覆
3. 測試 mention 後文字有回覆

## 7. 常見故障排查

### LINE webhook 驗證失敗
檢查：
- `Line:ChannelSecret` 是否正確
- LINE Webhook URL 是否正確
- 反向代理是否有正確轉發請求
- 是否真的打到 `/api/line/webhook`

### Bot 收到訊息但不回應
檢查：
- `Line:ChannelAccessToken`
- 外部網路是否可呼叫 LINE reply API
- AI provider 是否有有效 API Key
- 群組是否有 mention Bot

### 圖片 / 檔案失敗
檢查：
- 是否為 1 對 1 聊天
- Token 是否有效
- 檔案格式是否支援
- PDF 是否為可擷取文字的 PDF

### 最新資訊查詢失敗
檢查：
- `WebSearch:Enabled`
- `WebSearch:TavilyApiKey`
- 搜尋服務外網可達性

### 大量出現稍後再試
可能原因：
- 使用者節流觸發
- AI 429
- AI quota exhausted

請檢查：
- AI provider 配額
- 上游服務狀態
- 是否有異常流量

## 8. 已知營運限制

- 背景處理仍是 fire-and-forget
- 無正式 background queue
- 無 distributed cache / throttle / merge / backoff
- 多實例部署下，各 instance 的記憶體狀態彼此不共享
- `/health` 目前只有基本 liveness，不是完整 readiness
- 檔案下載索引為單機記憶體狀態
- 重新部署後下載連結可能失效

## 9. 本版邊界

本版是第一階段重構完成版：
- 重點是整理結構
- 不改既有外部行為

不包含：
- `Task.Run` 改 queue / `BackgroundService`
- Redis 或其他共享狀態儲存
- 更完整的 readiness / observability 架構
