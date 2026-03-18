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
        _model    = config["Ai:Gemini:Model"] ?? "gemini-2.5-flash";
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
                parts = new[] { new { text = "你是一位親切的管家，語氣溫暖有禮、回答精簡實用，必要時可條列重點。請全程使用繁體中文，並避免自稱是 AI。" } }
            },
            generationConfig = new { maxOutputTokens = 2048 }
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
            var candidate = doc.RootElement.GetProperty("candidates")[0];

            var parts = candidate.GetProperty("content").GetProperty("parts");
            var sb = new StringBuilder();
            foreach (var part in parts.EnumerateArray())
            {
                if (part.TryGetProperty("text", out var textPart))
                    sb.Append(textPart.GetString());
            }

            var text = sb.ToString().Trim();
            if (string.IsNullOrWhiteSpace(text))
                return "(AI 無回應)";

            // 若因 token 上限截斷，補上提示
            if (candidate.TryGetProperty("finishReason", out var reason) &&
                reason.GetString() == "MAX_TOKENS")
                text += "\n\n⚠️ 回答已達字數上限，如需後續請繼續提問。";

            return text;
        }
    }
}
