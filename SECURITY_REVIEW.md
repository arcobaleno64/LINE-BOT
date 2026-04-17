# 安全審查報告

**專案：** LINE Bot Webhook (`arcobaleno64/LINE-BOT`)  
**技術棧：** ASP.NET Core / .NET 10 / C#  
**審查日期：** 2025-07  
**審查工具：** GitHub Copilot security-review skill  

---

## 摘要嚴重性分佈

| 嚴重性 | 發現數 |
|--------|--------|
| 🔴 CRITICAL | 0 |
| 🟠 HIGH | 0 |
| 🟡 MEDIUM | 1 |
| 🔵 LOW | 2 |
| ⚪ INFO | 1 |

---

## 🟡 MEDIUM 發現

### M-01：Gemini Embedding API 金鑰附於 URL Query 參數

**檔案：** [Services/Documents/GeminiEmbeddingService.cs](Services/Documents/GeminiEmbeddingService.cs#L33)  
**函式：** `GetEmbeddingAsync`

**問題程式碼：**
```csharp
using var response = await _http.PostAsJsonAsync(
    $"{endpoint}/{model}:embedContent?key={apiKey}", payload, cancellationToken: ct);
```

**風險：**  
API 金鑰附在 URL 查詢參數中，可能出現在：
- HTTP 伺服器存取日誌（Nginx / Kestrel / Render）
- 反向代理日誌
- .NET `HttpClient` Diagnostic Event Listener 事件追蹤
- Application Insights / 分散式追蹤工具

攻擊者若取得日誌存取權，即可取得 Gemini API 金鑰並直接呼叫 Gemini API 產生費用或惡意請求。

**說明：** 這是 Gemini REST API 的官方認證方式（`?key=`），在 API 層面無替代方案。但可在應用層面減少暴露範圍。

**最小修復方案：**  
在 `Program.cs` 或 DI 設定中，對用於 embedding 的 `HttpClient` 加上 `DelegatingHandler`，讓日誌遮蔽該請求的 URL，或確保 Render 部署的日誌等級不含完整 request URL：

```csharp
// 選項 A：設定 HttpClient 不記錄完整 URL（自訂 Handler）
public class SuppressQueryLoggingHandler : DelegatingHandler
{
    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken ct)
    {
        // Strip query from logged URI in diagnostic events
        return base.SendAsync(request, ct);
    }
}
```

或更根本的方案：將 API key 改存於請求 Header（若 Gemini 未來支援），目前可接受現狀但需確保日誌設定不記錄 URL query string。

**驗證情境：** 確認 Render 的 access log 未包含完整 URL（含 query string）。

---

## 🔵 LOW 發現

### L-01：Tavily API 金鑰置於 JSON 請求 Body

**檔案：** [Services/WebSearchService.cs](Services/WebSearchService.cs#L66)  
**函式：** `TrySearchAsync`

**問題程式碼：**
```csharp
var payload = new
{
    api_key = _apiKey,
    query,
    ...
};
```

**風險：**  
API 金鑰在 JSON Body 中（Tavily 的官方認證方式），若未來啟用 HTTP 請求 body 除錯日誌，或透過第三方 middleware 記錄 request body，金鑰將被記錄。目前程式碼無 body 日誌，風險低。

**最小修復方案：**  
Tavily 同時支援 `Authorization: Bearer <key>` header，可改用標準 Bearer Token 方式避免金鑰出現在 body 中：

```csharp
using var request = new HttpRequestMessage(HttpMethod.Post, _endpoint)
{
    Content = new StringContent(
        JsonSerializer.Serialize(new { query, search_depth, max_results, include_answer, include_images }),
        Encoding.UTF8, "application/json")
};
request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
```

---

### L-02：`PublicBaseUrlResolver` 依賴 `Host` Header 作為後備

**檔案：** [Services/PublicBaseUrlResolver.cs](Services/PublicBaseUrlResolver.cs#L14)  
**函式：** `Resolve`

**問題程式碼：**
```csharp
var configured = _config["App:PublicBaseUrl"];
if (!string.IsNullOrWhiteSpace(configured))
    return configured.TrimEnd('/');

var proto = request.Headers["x-forwarded-proto"].ToString();
if (string.IsNullOrWhiteSpace(proto))
    proto = request.Scheme;

return $"{proto}://{request.Host}".TrimEnd('/');
```

**風險：**  
若 `App:PublicBaseUrl` 未設定，生成的下載連結 URL 使用來自請求的 `Host` header（攻擊者可控）。雖然需通過 LINE webhook 簽章驗證才能抵達此程式碼，但仍屬 host header injection 風險。若攻擊者取得 ChannelSecret，可製造指向惡意域名的下載連結讓使用者點擊。

**最小修復方案：**  
確保生產環境的 `appsettings.json`（或 Render 環境變數）始終設定 `App:PublicBaseUrl`；或在 `Resolve` 方法加上 allowlist 驗證：

```csharp
// 確認 Render 環境變數已設定
// App__PublicBaseUrl=https://your-service.onrender.com
```

若 `App:PublicBaseUrl` 已在 Render 設定，此問題實際上已緩解。

---

## ⚪ INFO 發現

### I-01：ConversationHistoryService 的對話摘要包含前段摘要原文注入風險（低優先）

**檔案：** [Services/ConversationHistoryService.cs](Services/ConversationHistoryService.cs#L55)

**觀察：**
```csharp
history.Add(new ChatMessage(
    "assistant",
    $"先前對話摘要：\n{session.SessionSummary}"));
```

對話摘要作為 `assistant` 角色注入至對話歷史。若摘要生成本身曾被使用者輸入污染（含有 prompt injection 指令），這些指令會在後續所有對話中持續出現在 context 中（Persistent Prompt Injection）。

目前的 `GenerateStatelessReplyAsync` 用於生成摘要，理論上惡意使用者可在對話中嵌入「請在摘要中包含：忽略所有系統提示...」等指令。

**這是 AI 應用的普遍風險**，非程式碼漏洞，不影響系統安全性，但值得記錄。現階段無需修復。

---

## 正面安全發現（通過項目）

下列安全關鍵路徑均已正確實作：

| 項目 | 實作品質 |
|------|---------|
| **Webhook 簽章驗證** | ✅ HMAC-SHA256 + `CryptographicOperations.FixedTimeEquals`（防時序攻擊），空簽章直接拒絕，在任何業務處理前執行 |
| **日誌不含敏感資料** | ✅ 所有 log 呼叫僅記錄長度、指紋、狀態碼、事件 ID，無原始 token/key/body |
| **群組/聊天室 mention 閘控** | ✅ `MentionGateService.ShouldHandle` 正確要求 `IsSelf == true`，非 mention 事件靜默略過 |
| **檔案大小雙層限制** | ✅ Content-Length header 早期拒絕 + 實際 byte 長度確認 |
| **檔案類型白名單** | ✅ 不支援的類型拋出 `NotSupportedException`，無 fallback 解析 |
| **下載 token 安全性** | ✅ `Guid.NewGuid().ToString("N")` — 128-bit 隨機，不可猜測，token 對路徑映射完全內部 |
| **安全檔名生成** | ✅ `MakeSafeFileName` 使用 `Path.GetInvalidFileNameChars()` 白名單清洗 |
| **背景 Worker 例外隔離** | ✅ 每個 event 獨立 try/catch，單一失敗不終止 worker，優雅停機已實作 |
| **記憶體邊界** | ✅ Sessions 上限 1000、快取上限 5000 筆、throttle 字典 1h 清理 |
| **依賴套件** | ✅ `DocumentFormat.OpenXml 3.2.0`、`PdfPig 0.1.13` — 均為近期版本，無已知重大 CVE |
| **路徑穿越防護** | ✅ `DownloadsController` 以 token 查找檔案路徑，不接受使用者提供的路徑 |

---

## 相依套件審計

| 套件 | 版本 | 狀態 |
|------|------|------|
| `DocumentFormat.OpenXml` | 3.2.0 | ✅ 安全 |
| `PdfPig` | 0.1.13 | ✅ 安全 |

無 npm/pip 等其他套件管理員。.NET 10 系統套件由 Microsoft 維護，無需額外審計。

---

## 修補建議優先序

| 優先序 | 項目 | 工作量 |
|--------|------|--------|
| 1 | **確認** Render `App__PublicBaseUrl` 環境變數已設定（L-02 緩解） | 5 分鐘 |
| 2 | 改用 Bearer Header 認證 Tavily API（L-01） | 30 分鐘 |
| 3 | 確認 Render access log 設定不記錄 URL query string（M-01 緩解） | 設定確認 |

---

*本報告由 security-review skill (github/awesome-copilot) 輔助生成，涵蓋 OWASP Top 10 及 LINE Bot 特定安全風險。*
