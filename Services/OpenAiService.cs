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

    public OpenAiService(HttpClient http, IConfiguration config)
    {
        _http     = http;
        _apiKey   = config["Ai:OpenAI:ApiKey"] ?? throw new InvalidOperationException("Missing Ai:OpenAI:ApiKey");
        _model    = config["Ai:OpenAI:Model"] ?? "gpt-4o";
        _endpoint = config["Ai:OpenAI:Endpoint"] ?? "https://api.openai.com/v1/chat/completions";
    }

    public async Task<string> GetReplyAsync(string userMessage, CancellationToken ct = default)
    {
        var payload = new
        {
            model    = _model,
            messages = new[]
            {
                new { role = "system", content = "你是一個樂於助人的 LINE 聊天機器人助手。請用繁體中文回答。" },
                new { role = "user",   content = userMessage }
            },
            max_tokens = 1024
        };

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
            .GetString();

        return content ?? "(AI 無回應)";
    }
}
