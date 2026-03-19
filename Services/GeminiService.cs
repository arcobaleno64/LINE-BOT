using System.Net;
using System.Text;
using System.Text.Json;

namespace LineBotWebhook.Services;

public class GeminiService : IAiService
{
    private const string ButlerPrompt = "你是一位親切的管家，語氣溫暖有禮、回答精簡實用，必要時可條列重點。請全程使用繁體中文，並避免自稱是 AI。";

    private readonly HttpClient _http;
    private readonly string _apiKey;
    private readonly string _model;
    private readonly string _fallbackModel;
    private readonly string _endpoint;
    private readonly int _maxOutputTokens;
    private readonly ConversationHistoryService _history;

    public GeminiService(HttpClient http, IConfiguration config, ConversationHistoryService history)
    {
        _http = http;
        _apiKey = config["Ai:Gemini:ApiKey"] ?? throw new InvalidOperationException("Missing Ai:Gemini:ApiKey");
        _model = config["Ai:Gemini:Model"] ?? "gemini-2.5-flash";
        _fallbackModel = config["Ai:Gemini:FallbackModel"] ?? "gemini-2.0-flash-lite";
        _endpoint = config["Ai:Gemini:Endpoint"] ?? "https://generativelanguage.googleapis.com/v1beta/models";
        _maxOutputTokens = int.TryParse(config["Ai:MaxOutputTokens"], out var parsed) ? parsed : 4096;
        _history = history;
    }

    public async Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default)
    {
        var history = _history.GetHistory(userKey);
        var contents = history
            .Select(m => new
            {
                role = m.Role == "assistant" ? "model" : "user",
                parts = new[] { new { text = m.Content } }
            })
            .Append(new
            {
                role = "user",
                parts = new[] { new { text = userMessage } }
            })
            .ToArray();

        var payload = BuildPayload(contents);
        var text = await SendWithRetryAsync(payload, ct);
        _history.Append(userKey, userMessage, text);
        return text;
    }

    public async Task<string> GetReplyFromImageAsync(byte[] imageBytes, string mimeType, string userPrompt, string userKey, CancellationToken ct = default)
    {
        var history = _history.GetHistory(userKey)
            .Select(m => new
            {
                role = m.Role == "assistant" ? "model" : "user",
                parts = new[] { new { text = m.Content } }
            })
            .Cast<object>();

        var prompt = string.IsNullOrWhiteSpace(userPrompt)
            ? "請協助分析這張圖片重點。"
            : userPrompt;

        var imagePart = new
        {
            role = "user",
            parts = new object[]
            {
                new { text = prompt },
                new
                {
                    inline_data = new
                    {
                        mime_type = mimeType,
                        data = Convert.ToBase64String(imageBytes)
                    }
                }
            }
        };

        var contents = history.Append(imagePart).ToArray();
        var payload = BuildPayload(contents);

        var text = await SendWithRetryAsync(payload, ct);
        var userInput = string.IsNullOrWhiteSpace(userPrompt)
            ? "[使用者上傳一張圖片，請分析]"
            : $"[使用者上傳一張圖片] {userPrompt}";

        _history.Append(userKey, userInput, text);
        return text;
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

    private object BuildPayload(object contents) => new
    {
        contents,
        systemInstruction = new
        {
            parts = new[] { new { text = ButlerPrompt } }
        },
        generationConfig = new { maxOutputTokens = _maxOutputTokens }
    };

    private async Task<string> SendWithRetryAsync(object payload, CancellationToken ct)
    {
        var response = await SendGenerateAsync(_model, payload, ct);

        if (response.StatusCode == HttpStatusCode.TooManyRequests &&
            !string.Equals(_model, _fallbackModel, StringComparison.OrdinalIgnoreCase))
        {
            response.Dispose();
            response = await SendGenerateAsync(_fallbackModel, payload, ct);
        }

        // 429 立刻拋出，由 controller 層的 Ai429BackoffService 統一處理冷卻與友善回覆
        // 不在此層重試，避免多 webhook 同時 retry 放大 429 風暴
        using (response)
        {
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

            if (candidate.TryGetProperty("finishReason", out var reason) &&
                reason.GetString() == "MAX_TOKENS")
            {
                text += "\n\n⚠️ 回答已達字數上限，如需後續請繼續提問。";
            }

            return text;
        }
    }

    private Task<HttpResponseMessage> SendGenerateAsync(string model, object payload, CancellationToken ct)
    {
        var url = $"{_endpoint.TrimEnd('/')}/{model}:generateContent?key={_apiKey}";
        var body = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
        var request = new HttpRequestMessage(HttpMethod.Post, url) { Content = body };
        return _http.SendAsync(request, ct);
    }
}

