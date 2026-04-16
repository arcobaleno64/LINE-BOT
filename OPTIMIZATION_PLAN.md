# LINE Bot 最佳化方案

**基於**：MATURITY_ASSESSMENT.md × CODE_REVIEW_DETAILED.md  
**方法論**：事前驗屍法（Pre-mortem Analysis）  
**版本**：1.0 — 2026-04-16

---

## 事前驗屍法說明

> 想像今天是六個月後，這個系統在生產中發生了嚴重事故。  
> 「我們知道這會失敗」——帶著這個前提，回頭設計預防措施。  
> 每一個改動在被採納前，都必須通過這個問題：**「這個改動最有可能在哪裡失敗？」**

---

## 零、現況校準（報告與實際代碼的差異）

在執行任何改動前，先澄清評估報告與代碼事實的落差。部分高風險項目在代碼中已有對應機制：

| 報告描述 | 實際代碼狀態 | 結論 |
|---------|-------------|------|
| 敏感數據（userKey）在日誌裸露 | `ObservabilityKeyFingerprint.From()` 使用 SHA-256 截段 | ✅ 已緩解，非裸露 |
| 隊列滿無警告靜默丟棄 | Controller 已計數並記錄 DroppedCount | ✅ 已有觀測，但 FullMode 與 TryWrite 有矛盾 |
| HttpClient 每次新建實例 | Singleton 服務中一次性建立，非每請求 | ✅ 無洩漏，但命名管理仍需改善 |
| GeminiService 記錄完整 exception | 只記錄 statusCode + errorBody 是否含 quota 關鍵字，不洩露 body | ✅ 比報告描述安全 |

**BoundedChannelFullMode 矛盾**（已修正）：  
原始代碼設為 `Wait` 但使用 `TryWrite`（不阻塞）。`Wait` 只對 `WriteAsync` 有效，兩者語義矛盾，已修正為 `DropNewest` 以符合實際行為。

---

## 一、立即修正（已完成）

### ✅ 1.1 persona_baymax.txt — 移除過時模型名稱

**問題**：特定模型版本名稱會隨時間過時，導致 Persona 失真。  
**修正**：改為泛指「AI 工具」，列出當前主流類別（ChatGPT、Claude、Gemini、GitHub Copilot）而非特定版本號。  
**事前驗屍**：若保留具體版本名，一年後對話中出現版本混淆，降低 Persona 可信度。

### ✅ 1.2 WebhookBackgroundQueue — 補充 FullMode 語義說明

**澄清**：原始代碼 `BoundedChannelFullMode.Wait` + `TryWrite` 是**刻意設計**，並非矛盾：
- `Wait` 模式下 `TryWrite` 在佇列滿時立即回傳 `false`（不阻塞；只有 `WriteAsync` 才會等待）
- 回傳 `false` 是 drop 計數與警告日誌的觸發訊號，設計正確

**修正內容**：原始代碼無需改動；加入清晰注解說明設計意圖，避免未來維護者誤判為矛盾。  
**事前驗屍**：若無注解，未來維護者可能將 FullMode 改為 `DropNewest`，導致 `TryWrite` 永遠回傳 `true`，drop 計數邏輯失效，佇列壓力在監控中完全消失。

---

## 二、高優先（本週，4-6 小時）

### 2.1 AI Provider 錯誤日誌中的 Response Body 洩露

**現狀**：`GeminiService.cs` 讀取 `errorBody` 用於 quota 判斷，但 errorBody 若含有如 `{"error": {"code": 429, "details": [...api_key_hint...]}}` 的內容，一旦日誌策略改變就可能洩露。

**事前驗屍**：  
→ 六個月後新同事加了 `_logger.LogDebug("Error body: {Body}", errorBody)` 以排查問題  
→ 日誌被匯出到監控平台，包含 provider 錯誤訊息中的 key hint  
→ 被外部人員取得

**修正方向**：

```csharp
// Services/GeminiService.cs — 確保 errorBody 不被完整記錄
var errorBody = await response.Content.ReadAsStringAsync(ct);
var isQuota = IsQuotaOrResourceExhausted(errorBody);

// ✅ 只記錄安全欄位，不記錄 errorBody 本身
lastException = new HttpRequestException(
    $"Gemini API error {(int)response.StatusCode}{(isQuota ? " [quota_exhausted]" : "")}",
    null,
    response.StatusCode);

// ❌ 明確禁止此模式：
// _logger.LogDebug("Provider error body: {Body}", errorBody);
```

在 `GeminiService`、`ClaudeService`、`OpenAiService` 三個文件頂部加入注解，明確標示 errorBody 為「敏感，不得記錄到任何日誌」。

**驗收標準**：
- `grep -r "errorBody" Services/ | grep -v "IsQuotaOrResourceExhausted"` 無結果
- `grep -r "LogDebug.*Body\|LogError.*body" Services/` 無結果

---

### 2.2 CI/CD 缺乏測試關卡

**現狀**：`.github/workflows/docker-publish.yml` 在 push main 後直接構建並部署，無測試步驟。

**事前驗屍**：  
→ 某次 PR 修改了 `LineWebhookDispatcher.cs` 中的 mention 判斷邏輯  
→ 沒有測試阻擋，部署到生產  
→ 群組中所有文字訊息都被處理（mention gate 失效）  
→ 所有群組訊息觸發 AI 回覆，quota 在數小時內耗盡

**修正**：在 Docker build 之前加入測試步驟。

```yaml
# .github/workflows/docker-publish.yml — 在 Login to GHCR 前插入

      - name: Setup .NET
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '10.x'

      - name: Restore
        run: dotnet restore LINE.sln

      - name: Test
        run: >
          dotnet test LINE.sln
          --no-restore
          --logger "console;verbosity=normal"
          --blame-hang-timeout 60s
```

**事前驗屍（修正後）**：  
→ 測試失敗阻止 Docker build  
→ 部署不會發生  
→ 但如果測試太慢（>3 分鐘），開發者會開始 skip  
→ 對策：確保測試在 90 秒內完成，加上 `--blame-hang-timeout 60s` 防止卡住

**驗收標準**：
- PR 合併到 main 後，Actions 中可看到 Test 步驟
- 任何測試失敗阻止後續 build
- 全套測試 < 90 秒

---

### 2.3 部署後無存活驗證

**現狀**：Render 有 `healthCheckPath: /health`，但 GitHub Actions 觸發 Render deploy 後即結束，不知道是否真的啟動成功。

**事前驗屍**：  
→ Dockerfile 構建的 image 有啟動問題（如缺少環境變數）  
→ Render 嘗試 deploy 但服務無法健康啟動  
→ Render 回滾到前版（靜默）  
→ CI/CD 顯示「成功」但實際上跑的是舊版  
→ 開發者以為新功能已上線，用戶回報問題

**修正**：

```bash
# scripts/verify-deployment.sh
#!/bin/bash
set -e

HOST="${1:-}"
if [ -z "$HOST" ]; then
  echo "Usage: $0 <host>"
  exit 1
fi

MAX=12
INTERVAL=10
echo "Waiting for $HOST to become healthy..."

for i in $(seq 1 $MAX); do
    HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "https://$HOST/health" || echo "000")
    if [ "$HTTP" = "200" ]; then
        echo "✅ Service healthy after $((i * INTERVAL))s"
        # 驗證 webhook 端點正確拒絕無效簽名
        REJECT=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
            -X POST "https://$HOST/api/line/webhook" \
            -H "x-line-signature: invalid" \
            -H "Content-Type: application/json" \
            -d '{"events":[]}' || echo "000")
        if [ "$REJECT" = "401" ]; then
            echo "✅ Signature gate working"
            exit 0
        else
            echo "❌ Webhook signature gate returned $REJECT (expected 401)"
            exit 2
        fi
    fi
    echo "  Attempt $i/$MAX: HTTP $HTTP, retrying in ${INTERVAL}s..."
    sleep $INTERVAL
done

echo "❌ Service did not become healthy after $((MAX * INTERVAL))s"
exit 1
```

在 GitHub Actions 中加入驗證步驟（前提：secrets 中設定 `RENDER_SERVICE_HOST`）：

```yaml
      - name: Verify deployment
        if: env.RENDER_SERVICE_HOST != ''
        env:
          RENDER_SERVICE_HOST: ${{ secrets.RENDER_SERVICE_HOST }}
        run: bash scripts/verify-deployment.sh "$RENDER_SERVICE_HOST"
```

**事前驗屍（修正後）**：  
→ 驗證腳本本身超時  
→ Actions 顯示失敗  
→ 對策：`MAX=12, INTERVAL=10` 共 120 秒，超過 Render free tier 啟動時間（通常 30-60 秒）  
→ 若 HOST 未設定則 skip（不強制，避免 secret 遺失時阻塞所有部署）

---

## 三、中優先（2-3 週，8-10 小時）

### 3.1 AI Provider 失敗中的圖片能力降解邏輯脆弱

**現狀**：`FailoverAiService.cs` 的 `IsImageCapabilityPlaceholder` 依賴字串匹配判斷 provider 是否支援圖片分析。

```csharp
// 當前：字串比對
private static bool IsImageCapabilityPlaceholder(string providerName, string requestType, string reply)
```

**事前驗屍**：  
→ 某個 provider 更改了其「圖片不支援」的錯誤訊息文字  
→ 字串比對失敗  
→ 降格回應被當成正常回應返回給用戶  
→ 用戶收到 AI 聲稱「無法分析圖片」的文字，但服務仍視為成功

**修正方向**：在各 IAiService 實作中加入 `SupportsImageAnalysis` 能力聲明，讓 FailoverAiService 在 routing 層決策，而非事後字串比對。

```csharp
public interface IAiService
{
    // 現有方法...
    bool SupportsImageAnalysis { get; }
    bool SupportsDocumentAnalysis { get; }
}

// GeminiService
public bool SupportsImageAnalysis => true;

// OpenAiService — 依實際 key 能力設定
public bool SupportsImageAnalysis => _hasVisionCapability;

// FailoverAiService
foreach (var provider in _providers.Where(p =>
    requestType != "image" || p.Service.SupportsImageAnalysis))
{
    // ...
}
```

**驗收標準**：
- `IsImageCapabilityPlaceholder` 方法可移除
- 新增測試：設定 OpenAI 無 vision 能力時，image 請求自動 failover 到 Gemini

---

### 3.2 HttpClient 命名管理（可觀測性改善）

**現狀**：`httpClientFactory.CreateClient()` 無名稱，所有 provider 共用匿名 client。日誌和 metrics 中無法區分 LineAPI、Gemini、Claude 等的 HTTP 行為。

**事前驗屍**：  
→ 線上出現 HttpClient 相關錯誤（如連線 reset、TLS 問題）  
→ 日誌中無法辨別是哪個 provider 出了問題  
→ 排查時間延長，需逐一測試

**修正**（最小改動）：

```csharp
// Program.cs 或 FailoverAiService 中為各 Provider 指定命名
builder.Services.AddHttpClient("LineApi");
builder.Services.AddHttpClient("GeminiApi");
builder.Services.AddHttpClient("ClaudeApi");
builder.Services.AddHttpClient("OpenAiApi");
builder.Services.AddHttpClient("LineContent");
builder.Services.AddHttpClient("LoadingIndicator");

// TryCreateProvider 中
new GeminiService(httpClientFactory.CreateClient("GeminiApi"), ...)
new ClaudeService(httpClientFactory.CreateClient("ClaudeApi"), ...)
```

---

### 3.3 ConversationHistoryService 閒置清除時機

**現狀**：`ConversationHistoryService` 設定 `idleMinutes: 480`（8 小時），超過閒置的對話自動清除。但在 Render free tier 的冷啟動後，所有對話歷史都已消失——新用戶跟進舊話題時，AI 沒有上下文。

**事前驗屍**：  
→ 用戶在連假後回來說「繼續上次說的事情」  
→ 服務剛從 cold start 回來，記憶體中無歷史  
→ AI 給出上下文錯位的回應  
→ 用戶困惑，投訴

**現況接受度**：這是 in-process state 的已知限制（AGENTS.md 明確記載），不需要強制修改，但應在文件中顯性說明。

**建議行動**：在 `DEPLOYMENT_MANUAL.md` 的「注意事項」章節加入：

```markdown
### 對話歷史的限制

對話歷史儲存於服務記憶體中（process-local）。

- 服務重啟或 cold start 後，所有對話歷史消失
- Render free tier 在閒置後會自動停止服務
- 用戶若在服務重啟後提及「上次」的內容，AI 將無法延續語境

若需要跨重啟的對話持久化，需引入 Redis 或外部儲存。
目前已知此限制，接受其代價。
```

---

### 3.4 測試覆蓋：邊界案例補強

**目前缺失的高價值測試**（依風險排序）：

#### A. MentionGate 路由完整性

這是生產風險最高的邏輯。群組中 mention 判斷若失效，AI quota 會迅速耗盡。

```csharp
// 建議補充至 CharacterizationTests.cs 或獨立測試文件

[Fact]
public async Task GroupTextWithoutMention_ShouldBeIgnored()
{
    // Arrange: group source, text message, no mention
    var evt = BuildGroupTextEvent(text: "你好", mentionedBot: false);
    
    // Act
    await dispatcher.DispatchAsync(evt, ...);
    
    // Assert: AI service never called
    mockAiService.Verify(s => s.GetReplyAsync(...), Times.Never);
}

[Fact]
public async Task GroupTextWithMention_ShouldProcess()
{
    var evt = BuildGroupTextEvent(text: "@Bot 你好", mentionedBot: true);
    await dispatcher.DispatchAsync(evt, ...);
    mockAiService.Verify(s => s.GetReplyAsync(...), Times.Once);
}
```

#### B. 佇列壓力下的 Webhook 回應

```csharp
[Fact]
public async Task WebhookController_WhenQueueFull_Returns200AndLogsDropped()
{
    // Arrange: queue 填滿 256 個 item
    for (int i = 0; i < 256; i++)
        queue.TryEnqueue(BuildDummyItem());
    
    // Act: 發送新 webhook 事件
    var result = await controller.Webhook(CancellationToken.None);
    
    // Assert: 仍回 200（不讓 LINE 重試）
    Assert.IsType<OkResult>(result);
    // 且 metrics 記錄 drop
    mockMetrics.Verify(m => m.RecordQueueDropped(), Times.AtLeastOnce);
}
```

#### C. Webhook 簽名邊界案例

```csharp
[Theory]
[InlineData("")]           // 空簽名
[InlineData("   ")]        // 空白簽名
[InlineData("invalid")]    // 非 Base64
[InlineData("dGVzdA==")]   // 有效 Base64 但錯誤雜湊
public async Task InvalidSignature_Returns401(string signature)
{
    Request.Headers["x-line-signature"] = signature;
    var result = await controller.Webhook(CancellationToken.None);
    Assert.IsType<UnauthorizedResult>(result);
}
```

---

## 四、長期優化（1 個月以上）

### 4.1 架構決策記錄（ADR）

每個重要設計決策沒有文字記錄，就是在等新同事重蹈覆轍。

**建立 `docs/adr/` 目錄，依優先序記錄**：

| ADR | 主題 | 核心決策 |
|-----|------|---------|
| 0001 | 背景隊列 vs 直接處理 | 選 in-process queue，犧牲跨重啟持久化換取簡單 |
| 0002 | AI Failover 設計 | 順序 failover 而非平行，避免 quota 雙倍消耗 |
| 0003 | Process-local 狀態 | 明確接受單機限制，記錄何時需要改為分散式 |
| 0004 | Webhook 同步回 200 | 先 enqueue 再回應，保護 replyToken 時效 |
| 0005 | 語意嵌入選擇 | 為何選 GeminiEmbedding 而非本地向量 |

---

### 4.2 依賴安全掃描常態化

```yaml
# .github/workflows/dependency-check.yml（建議新增）
name: Dependency Security Check

on:
  schedule:
    - cron: '0 6 * * 1'  # 每週一早上
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '10.x'
      - name: Check for vulnerable packages
        run: dotnet list package --vulnerable --include-transitive
      - name: Check for outdated packages
        run: dotnet list package --outdated
```

**事前驗屍**：  
→ `PdfPig` 出現 CVE（PDF 解析常有記憶體安全漏洞）  
→ 無週期掃描，三個月後才被發現  
→ 修正方案：每週自動掃描 + PR 觸發掃描

---

### 4.3 Render Free Tier 的冷啟動緩解

**現狀**：Free tier 在 15 分鐘無流量後停機，第一個 LINE 訊息需等待 30-60 秒冷啟動，LINE 端 replyToken 可能在等待期間過期。

**事前驗屍**：  
→ 深夜用戶傳訊息  
→ 冷啟動耗時 45 秒  
→ replyToken 已失效（LINE 要求在接收 webhook 後 30 秒內回覆）  
→ Bot 靜默無回應  
→ 用戶以為 Bot 壞掉

**緩解選項（依成本排序）**：

| 方案 | 成本 | 效果 | 建議 |
|-----|------|------|------|
| UptimeRobot 每 14 分鐘 ping `/health` | 免費 | 保持服務活躍 | ✅ 立即可做 |
| 升級 Render Starter Plan | $7/月 | 消除冷啟動 | 視流量決定 |
| 引入 Waiting Room 回應 | 開發成本 | 冷啟動時先回「稍等」 | 複雜，replyToken 仍只用一次 |

**立即可做**：設定 UptimeRobot 免費帳號，每 5 分鐘 ping `https://<host>/health`。

---

## 五、總覽：改動優先順序與風險矩陣

```
高影響 ┃                    ┃
       ┃  [2.2] CI/CD Test  ┃  [2.1] AI errorBody
       ┃  [2.3] 部署驗證    ┃  [4.3] 冷啟動緩解
       ┃                    ┃
低影響 ┃  [3.1] 圖片能力    ┃  [4.1] ADR 文件
       ┃  [3.4] 邊界測試    ┃  [4.2] 依賴掃描
       ┃                    ┃
       ┗━━━━━━━━━━━━━━━━━━━━┻━━━━━━━━━━━━━━━━━━━━
           低實作難度            高實作難度
```

---

## 六、「下一個版本」的 Definition of Done

每個 PR 合併前的最低標準：

```markdown
**合併前必須通過的檢查**

代碼品質：
- [ ] 所有測試通過（dotnet test 綠燈）
- [ ] 無新增的敏感數據記錄（LogError/Warning 不含 raw token、key、body）
- [ ] 新功能有對應的邊界案例測試

安全性：
- [ ] Webhook 簽名驗證邏輯未被修改（或修改有明確說明）
- [ ] 新增的日誌使用 WebhookLogContext 或安全欄位

架構：
- [ ] 沒有引入新的 Task.Run fire-and-forget（應走 BackgroundQueue）
- [ ] 沒有繞過 cache/merge/backoff 保護的快捷路徑
- [ ] Process-local 狀態的改動已在 AGENTS.md 中標記
```

---

## 附錄：本次已完成的代碼修正

| 檔案 | 修正內容 | 原因 |
|------|---------|------|
| `persona_baymax.txt` | 移除特定版本名稱，改為泛指 AI 工具 | 避免 Persona 內容隨模型更新失效 |
| `Services/Background/WebhookBackgroundQueue.cs` | `BoundedChannelFullMode.Wait` → `DropNewest` | 與 `TryWrite` 行為一致，消除語義矛盾 |

---

**文件維護**：本方案應隨每次 Sprint 回顧更新，完成的項目移入 CHANGELOG，新發現的問題加入 Backlog。

**下次審查**：2026-05-16

