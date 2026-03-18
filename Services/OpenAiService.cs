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
    private readonly ConversationHistoryService _history;

    public OpenAiService(HttpClient http, IConfiguration config, ConversationHistoryService history)
    {
        _http     = http;
        _apiKey   = config["Ai:OpenAI:ApiKey"] ?? throw new InvalidOperationException("Missing Ai:OpenAI:ApiKey");
        _model    = config["Ai:OpenAI:Model"] ?? "gpt-4o";
        _endpoint = config["Ai:OpenAI:Endpoint"] ?? "https://api.openai.com/v1/chat/completions";
        _history  = history;
    }

    public async Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default)
    {
        var systemMsg = new { role = "system", content = "你是一位親切的管家，語氣溫暖有禮、回答精簡實用，必要時可條列重點。請全程使用繁體中文，並避免自稱是 AI。" };
        var historyMsgs = _history.GetHistory(userKey)
            .Select(m => new { role = m.Role, content = m.Content });
        var messages = new[] { systemMsg }
            .Concat(historyMsgs)
            .Append(new { role = "user", content = userMessage })
            .ToArray();

        var payload = new { model = _model, messages, max_tokens = 2048 };

        var request = new HttpRequestMessage(HttpMethod.Post, _endpoint)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);

        var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();

        using var doc = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(ct), cancellationToken: ct);
        var content = doc.RootElement
            .GetProperty("choices")[0]
            .GetProperty("message")
            .GetProperty("content")
            .GetString() ?? "(AI 無回應)";

        _history.Append(userKey, userMessage, content);
        return content;
    }
}
