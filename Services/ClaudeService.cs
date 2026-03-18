using System.Text;
using System.Text.Json;

namespace LineBotWebhook.Services;

public class ClaudeService : IAiService
{
    private readonly HttpClient _http;
    private readonly string _apiKey;
    private readonly string _model;
    private readonly string _endpoint;

    public ClaudeService(HttpClient http, IConfiguration config)
    {
        _http     = http;
        _apiKey   = config["Ai:Claude:ApiKey"] ?? throw new InvalidOperationException("Missing Ai:Claude:ApiKey");
        _model    = config["Ai:Claude:Model"] ?? "claude-sonnet-4-20250514";
        _endpoint = config["Ai:Claude:Endpoint"] ?? "https://api.anthropic.com/v1/messages";
    }

    public async Task<string> GetReplyAsync(string userMessage, CancellationToken ct = default)
    {
        var payload = new
        {
            model      = _model,
            max_tokens = 1024,
            system     = "你是一個樂於助人的 LINE 聊天機器人助手。請用繁體中文回答。",
            messages   = new[]
            {
                new { role = "user", content = userMessage }
            }
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
            .GetString();

        return text ?? "(AI 無回應)";
    }
}
