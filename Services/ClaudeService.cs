using System.Text;
using System.Text.Json;

namespace LineBotWebhook.Services;

public class ClaudeService : IAiService
{
    private readonly HttpClient _http;
    private readonly string _apiKey;
    private readonly string _model;
    private readonly string _endpoint;
    private readonly int _maxOutputTokens;
    private readonly ConversationHistoryService _history;

    public ClaudeService(HttpClient http, IConfiguration config, ConversationHistoryService history)
    {
        _http     = http;
        _apiKey   = config["Ai:Claude:ApiKey"] ?? throw new InvalidOperationException("Missing Ai:Claude:ApiKey");
        _model    = config["Ai:Claude:Model"] ?? "claude-sonnet-4-20250514";
        _endpoint = config["Ai:Claude:Endpoint"] ?? "https://api.anthropic.com/v1/messages";
        _maxOutputTokens = int.TryParse(config["Ai:MaxOutputTokens"], out var parsed) ? parsed : 4096;
        _history  = history;
    }

    public async Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default)
    {
        var historyMsgs = _history.GetHistory(userKey)
            .Select(m => new { role = m.Role, content = m.Content })
            .Append(new { role = "user", content = userMessage })
            .ToArray();

        var payload = new
        {
            model      = _model,
            max_tokens = _maxOutputTokens,
            system     = "你是一位親切的管家，語氣溫暖有禮、回答精簡實用，必要時可條列重點。請全程使用繁體中文，並避免自稱是 AI。",
            messages   = historyMsgs
        };

        var request = new HttpRequestMessage(HttpMethod.Post, _endpoint)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Add("x-api-key", _apiKey);
        request.Headers.Add("anthropic-version", "2023-06-01");

        var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();

        using var doc = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(ct), cancellationToken: ct);
        var text = doc.RootElement
            .GetProperty("content")[0]
            .GetProperty("text")
            .GetString() ?? "(AI 無回應)";

        _history.Append(userKey, userMessage, text);
        return text;
    }

    public Task<string> GetReplyFromImageAsync(byte[] imageBytes, string mimeType, string userPrompt, string userKey, CancellationToken ct = default)
    {
        var prompt = string.IsNullOrWhiteSpace(userPrompt)
            ? "使用者上傳了一張圖片，但目前提供者未啟用圖片解析。請禮貌說明可改用 Gemini，或請使用者補充文字描述後我再協助。"
            : $"使用者上傳了一張圖片，補充需求：{userPrompt}。目前提供者未啟用圖片解析。請禮貌說明可改用 Gemini，或請使用者補充文字描述後我再協助。";
        return GetReplyAsync(prompt, userKey, ct);
    }

    public Task<string> GetReplyFromDocumentAsync(string fileName, string mimeType, string extractedText, string userPrompt, string userKey, CancellationToken ct = default)
    {
        const int maxChars = 12000;
        var clipped = extractedText.Length > maxChars
            ? extractedText[..maxChars] + "\n\n[已截斷，僅分析前段內容]"
            : extractedText;

        var prompt = $"""
你收到一個檔案，請協助整理重點。
檔名：{fileName}
MIME：{mimeType}
使用者需求：{(string.IsNullOrWhiteSpace(userPrompt) ? "請整理摘要與重點" : userPrompt)}

以下是檔案文字內容：
{clipped}
""";

        return GetReplyAsync(prompt, userKey, ct);
    }
}
