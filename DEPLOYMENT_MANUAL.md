# LINE Bot 上線手冊

## 1. 目的

本文提供部署與維運人員使用，說明本版 LINE Bot 的必要設定、上線步驟、驗證方式與常見故障排查。

## 2. 本版實際能力

- Webhook 接收：`POST /api/line/webhook`
- 1 對 1：文字 / 圖片 / 檔案
- 群組 / room：文字需 mention；圖片預設忽略；檔案可由設定控制
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
- `App:AllowGroupFileHandling`
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
- Bot 若在群組中使用：文字需 mention，圖片預設忽略，檔案可由設定控制
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
- 圖片是否在 1 對 1 聊天（群組圖片預設忽略）
- 檔案若在群組，是否已啟用 `App:AllowGroupFileHandling`
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

- 對話歷史儲存於服務記憶體（process-local），服務重啟或 cold start 後消失
- 無 distributed cache / throttle / merge / backoff（多實例部署下各自獨立）
- 多實例部署下，各 instance 的記憶體狀態彼此不共享
- `/health` 目前只有基本 liveness，不是完整 readiness
- 檔案下載索引為單機記憶體狀態，重新部署後下載連結可能失效
- Render free tier 在閒置 15 分鐘後停機，建議設定 UptimeRobot 每 5 分鐘 ping `/health`

## 9. GitHub Actions Secrets 設定

本倉庫的 CI/CD 流程（`.github/workflows/docker-publish.yml`）使用以下 secrets，需在 GitHub → Settings → Secrets and variables → Actions 中設定：

| Secret 名稱 | 是否必填 | 說明 |
|------------|---------|------|
| `RENDER_DEPLOY_HOOK` | 必填 | Render Deploy Hook URL，觸發部署用 |
| `RENDER_SERVICE_HOST` | 選填 | 部署後驗證用，填入如 `my-bot.onrender.com`（不含 https://） |

若未設定 `RENDER_SERVICE_HOST`，部署驗證步驟會自動跳過。

**取得 Render Deploy Hook**：Render Dashboard → 服務 → Settings → Deploy Hook → Copy URL

### 手動執行部署驗證

```bash
bash scripts/verify-deployment.sh my-bot.onrender.com
```

驗證內容：
1. `/health` 回 `200`（服務存活）
2. `POST /api/line/webhook` 帶無效簽名回 `401`（簽名閘道完好）

## 10. 本版邊界

- 背景處理已改為 in-process queue（`System.Threading.Channels`，容量 256）
- 對話記憶體、節流、快取、backoff 等狀態為 process-local
- 不包含 Redis 或其他共享狀態儲存
- 更完整的 readiness / observability 架構列於 OPTIMIZATION_PLAN.md
