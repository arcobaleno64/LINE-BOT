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
        var apiKey = config["Ai:OpenAI:ApiKey"];
        if (string.IsNullOrWhiteSpace(apiKey))
            throw new InvalidOperationException("Missing Ai:OpenAI:ApiKey");
        _apiKey   = apiKey;
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
        // 本提供者未啟用真實圖片解析；直接拋例外讓 FailoverAiService 接手下一個提供者，
        // 避免將 placeholder 訊息寫入 ConversationHistoryService 而污染後續上下文。
        throw new NotSupportedException("OpenAI image analysis is not enabled in this configuration.");
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

        using var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();

        using var doc = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(ct), cancellationToken: ct);
        return doc.RootElement
            .GetProperty("choices")[0]
            .GetProperty("message")
            .GetProperty("content")
            .GetString() ?? "(AI 無回應)";
    }
}
