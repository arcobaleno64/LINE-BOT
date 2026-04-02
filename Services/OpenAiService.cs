using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace LineBotWebhook.Services;

public class OpenAiService : IAiService
{
    private readonly HttpClient _http;
    private readonly string _apiKey;
    private readonly string _model;
    private readonly string _endpoint;
    private readonly int _maxOutputTokens;
    private readonly ConversationHistoryService _history;
    private readonly PersonaContext _persona;

    public OpenAiService(HttpClient http, IConfiguration config, ConversationHistoryService history, PersonaContext persona)
    {
        _http     = http;
        _apiKey   = config["Ai:OpenAI:ApiKey"] ?? throw new InvalidOperationException("Missing Ai:OpenAI:ApiKey");
        _model    = config["Ai:OpenAI:Model"] ?? "gpt-4o";
        _endpoint = config["Ai:OpenAI:Endpoint"] ?? "https://api.openai.com/v1/chat/completions";
        _maxOutputTokens = int.TryParse(config["Ai:MaxOutputTokens"], out var parsed) ? parsed : 4096;
        _history  = history;
        _persona  = persona;
    }

    public async Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default, bool enableQuickReplies = false)
    {
        var systemMsg = new { role = "system", content = BuildSystemPrompt(enableQuickReplies) };
        var historyMsgs = _history.GetHistory(userKey)
            .Select(m => new { role = m.Role, content = m.Content });
        var messages = new[] { systemMsg }
            .Concat(historyMsgs)
            .Append(new { role = "user", content = userMessage })
            .ToArray();

        var payload = new { model = _model, messages, max_tokens = _maxOutputTokens };
        var content = await SendGenerateAsync(payload, ct);
        var parsed = QuickReplySuggestionParser.Parse(content);
        _history.Append(userKey, userMessage, parsed.MainText);
        return content;
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
        var basePrompt = _persona.SystemPrompt;
        if (!enableQuickReplies)
            return basePrompt;

        return basePrompt + "\n回答結束後，若適合，可在回覆最後附上唯一格式：\\n\\n<quick-replies>[\"選項1\",\"選項2\"]</quick-replies>。最多 3 個選項，需短、自然、可直接點擊送出；若不適合提供，就不要附加任何 quick reply 區塊。";
    }

    public async Task<string> GenerateStatelessReplyAsync(string prompt, CancellationToken ct = default)
    {
        var messages = new[]
        {
            new { role = "system", content = _persona.SystemPrompt },
            new { role = "user", content = prompt }
        };

        var payload = new { model = _model, messages, max_tokens = _maxOutputTokens };
        return await SendGenerateAsync(payload, ct);
    }

    private async Task<string> SendGenerateAsync(object payload, CancellationToken ct)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, _endpoint)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);

        var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();

        using var doc = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(ct), cancellationToken: ct);
        return doc.RootElement
            .GetProperty("choices")[0]
            .GetProperty("message")
            .GetProperty("content")
            .GetString() ?? "(AI 無回應)";
    }
}
