using System.Net;
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
        _model    = config["Ai:Gemini:Model"] ?? "gemini-2.5-flash-lite";
        _endpoint = config["Ai:Gemini:Endpoint"] ?? "https://generativelanguage.googleapis.com/v1beta/models";
    }

    public async Task<string> GetReplyAsync(string userMessage, CancellationToken ct = default)
    {
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

        var body = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");

        // 遇到 429 最多重試 3 次，每次等待間隔加倍
        int[] retryDelaysMs = [2000, 5000, 10000];
        for (int attempt = 0; ; attempt++)
        {
            var request = new HttpRequestMessage(HttpMethod.Post, url) { Content = body };
            var response = await _http.SendAsync(request, ct);

            if (response.StatusCode == HttpStatusCode.TooManyRequests && attempt < retryDelaysMs.Length)
            {
                await Task.Delay(retryDelaysMs[attempt], ct);
                body = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
                continue;
            }

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
}
