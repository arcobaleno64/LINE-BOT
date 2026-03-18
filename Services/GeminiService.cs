using System.Text;
using System.Text.Json;

namespace LineBotWebhook.Services;

public class GeminiService : IAiService
{
    private readonly HttpClient _http;
    private readonly string _apiKey;
    private readonly string _model;
    private readonly string _endpoint;

    public GeminiService(HttpClient http, IConfiguration config)
    {
        _http     = http;
        _apiKey   = config["Ai:Gemini:ApiKey"] ?? throw new InvalidOperationException("Missing Ai:Gemini:ApiKey");
        _model    = config["Ai:Gemini:Model"] ?? "gemini-3.0-flash";
        _endpoint = config["Ai:Gemini:Endpoint"] ?? "https://generativelanguage.googleapis.com/v1beta/models";
    }

    public async Task<string> GetReplyAsync(string userMessage, CancellationToken ct = default)
    {
        // POST {endpoint}/{model}:generateContent?key={apiKey}
        var url = $"{_endpoint.TrimEnd('/')}/{_model}:generateContent?key={_apiKey}";

        var payload = new
        {
            contents = new[]
            {
                new
                {
                    role  = "user",
                    parts = new[] { new { text = userMessage } }
                }
            },
            systemInstruction = new
            {
                parts = new[] { new { text = "你是一個樂於助人的 LINE 聊天機器人助手。請用繁體中文回答。" } }
            },
            generationConfig = new { maxOutputTokens = 1024 }
        };

        var request = new HttpRequestMessage(HttpMethod.Post, url)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };

        var response = await _http.SendAsync(request, ct);
        response.EnsureSuccessStatusCode();

        using var doc = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(ct), cancellationToken: ct);
        var text = doc.RootElement
            .GetProperty("candidates")[0]
            .GetProperty("content")
            .GetProperty("parts")[0]
            .GetProperty("text")
            .GetString();

        return text ?? "(AI 無回應)";
    }
}
