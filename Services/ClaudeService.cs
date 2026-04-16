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
    private readonly PersonaContext _persona;

    public ClaudeService(HttpClient http, IConfiguration config, ConversationHistoryService history, PersonaContext persona)
    {
        _http     = http;
        _apiKey   = config["Ai:Claude:ApiKey"] ?? throw new InvalidOperationException("Missing Ai:Claude:ApiKey");
        _model    = config["Ai:Claude:Model"] ?? "claude-sonnet-4-20250514";
        _endpoint = config["Ai:Claude:Endpoint"] ?? "https://api.anthropic.com/v1/messages";
        _maxOutputTokens = int.TryParse(config["Ai:MaxOutputTokens"], out var parsed) ? parsed : 4096;
        _history  = history;
        _persona  = persona;
    }

    public async Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default, bool enableQuickReplies = false)
    {
        var historyMsgs = _history.GetHistory(userKey)
            .Select(m => new { role = m.Role, content = m.Content })
            .Append(new { role = "user", content = userMessage })
            .ToArray();

        var payload = new
        {
            model      = _model,
            max_tokens = _maxOutputTokens,
            system     = BuildSystemPrompt(enableQuickReplies),
            messages   = historyMsgs
        };
        var text = await SendGenerateAsync(payload, ct);
        var parsed = QuickReplySuggestionParser.Parse(text);
        _history.Append(userKey, userMessage, parsed.MainText);
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

    private string BuildSystemPrompt(bool enableQuickReplies)
    {
        return LineReplyTextFormatter.BuildSystemPrompt(_persona.SystemPrompt, enableQuickReplies);
    }

    public async Task<string> GenerateStatelessReplyAsync(string prompt, CancellationToken ct = default)
    {
        var payload = new
        {
            model      = _model,
            max_tokens = _maxOutputTokens,
            system     = _persona.SystemPrompt,
            messages   = new[] { new { role = "user", content = prompt } }
        };

        return await SendGenerateAsync(payload, ct);
    }

    private async Task<string> SendGenerateAsync(object payload, CancellationToken ct)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, _endpoint)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Add("x-api-key", _apiKey);
        request.Headers.Add("anthropic-version", "2023-06-01");

        using var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();

        using var doc = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(ct), cancellationToken: ct);
        return doc.RootElement
            .GetProperty("content")[0]
            .GetProperty("text")
            .GetString() ?? "(AI 無回應)";
    }
}
