using System.Net;
using System.Text;
using System.Text.Json;

namespace LineBotWebhook.Services;

public class GeminiService : IAiService
{
    private const string ButlerPrompt = "你是一位親切的管家，語氣溫暖有禮、回答精簡實用，必要時可條列重點。請全程使用繁體中文，並避免自稱是 AI。";
    private const string ProviderName = "Gemini";

    private readonly HttpClient _http;
    private readonly IReadOnlyList<string> _apiKeys;
    private readonly string _model;
    private readonly string _fallbackModel;
    private readonly string _endpoint;
    private readonly int _maxOutputTokens;
    private readonly ConversationHistoryService _history;
    private readonly ILogger<GeminiService> _logger;

    public GeminiService(HttpClient http, IConfiguration config, ConversationHistoryService history, ILogger<GeminiService> logger)
    {
        _http = http;
        _apiKeys = AiConfigurationHelpers.GetConfiguredValues(config, "Ai:Gemini:ApiKey", "Ai:Gemini:SecondaryApiKey");
        if (_apiKeys.Count == 0)
            throw new InvalidOperationException("Missing Ai:Gemini:ApiKey");

        _model = config["Ai:Gemini:Model"] ?? "gemini-2.5-flash";
        _fallbackModel = config["Ai:Gemini:FallbackModel"] ?? "gemini-2.0-flash-lite";
        _endpoint = config["Ai:Gemini:Endpoint"] ?? "https://generativelanguage.googleapis.com/v1beta/models";
        _maxOutputTokens = int.TryParse(config["Ai:MaxOutputTokens"], out var parsed) ? parsed : 4096;
        _history = history;
        _logger = logger;
    }

    public async Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default, bool enableQuickReplies = false)
    {
        return await GetReplyFromTextPromptAsync(userMessage, userKey, "text", ct, enableQuickReplies);
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
        var payload = BuildPayload(contents, enableQuickReplies: false);

        var text = await SendWithRetryAsync(payload, "image", ct);
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

        return GetReplyFromTextPromptAsync(prompt, userKey, "document", ct, enableQuickReplies: false);
    }

    private object BuildPayload(object contents, bool enableQuickReplies) => new
    {
        contents,
        systemInstruction = new
        {
            parts = new[] { new { text = BuildSystemPrompt(enableQuickReplies) } }
        },
        generationConfig = new { maxOutputTokens = _maxOutputTokens }
    };

    private async Task<string> SendWithRetryAsync(object payload, string requestType, CancellationToken ct)
    {
        HttpRequestException? lastException = null;
        var blockedKeySlots = new HashSet<string>(StringComparer.Ordinal);

        foreach (var attempt in BuildAttempts())
        {
            if (blockedKeySlots.Contains(attempt.KeySlot))
                continue;

            using var response = await SendGenerateAsync(attempt.Model, attempt.ApiKey, payload, ct);

            if (response.IsSuccessStatusCode)
            {
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

                _logger.LogInformation(
                    "Gemini request served. Provider={Provider} RequestType={RequestType} KeySlot={KeySlot} ModelSlot={ModelSlot}",
                    ProviderName,
                    requestType,
                    attempt.KeySlot,
                    attempt.ModelSlot);

                return text;
            }

            var errorBody = await response.Content.ReadAsStringAsync(ct);
            lastException = new HttpRequestException(
                $"Gemini API error {(int)response.StatusCode}: {errorBody}",
                null,
                response.StatusCode);

            switch (ClassifyFailure(response.StatusCode, errorBody))
            {
                case GeminiFailureDisposition.TryOtherGeminiRoutes:
                    _logger.LogWarning(
                        "Gemini attempt failed; trying next Gemini route. Provider={Provider} RequestType={RequestType} KeySlot={KeySlot} ModelSlot={ModelSlot} StatusCode={StatusCode} IsQuotaExhausted={IsQuotaExhausted}",
                        ProviderName,
                        requestType,
                        attempt.KeySlot,
                        attempt.ModelSlot,
                        (int)response.StatusCode,
                        IsQuotaOrResourceExhausted(errorBody));
                    continue;
                case GeminiFailureDisposition.TryOtherKeysOnly:
                    blockedKeySlots.Add(attempt.KeySlot);
                    _logger.LogWarning(
                        "Gemini key failed authentication/authorization; trying another Gemini key. Provider={Provider} RequestType={RequestType} KeySlot={KeySlot} ModelSlot={ModelSlot} StatusCode={StatusCode}",
                        ProviderName,
                        requestType,
                        attempt.KeySlot,
                        attempt.ModelSlot,
                        (int)response.StatusCode);
                    continue;
                default:
                    throw lastException;
            }
        }

        if (lastException is not null)
            throw lastException;

        throw new InvalidOperationException("Gemini API call failed without a captured exception.");
    }

    private async Task<string> GetReplyFromTextPromptAsync(string prompt, string userKey, string requestType, CancellationToken ct, bool enableQuickReplies)
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
                parts = new[] { new { text = prompt } }
            })
            .ToArray();

        var payload = BuildPayload(contents, enableQuickReplies);
        var text = await SendWithRetryAsync(payload, requestType, ct);
        var parsed = QuickReplySuggestionParser.Parse(text);
        _history.Append(userKey, prompt, parsed.MainText);
        return text;
    }

    private static string BuildSystemPrompt(bool enableQuickReplies)
    {
        if (!enableQuickReplies)
            return ButlerPrompt;

        return ButlerPrompt + "\n回答結束後，若適合，可在回覆最後附上唯一格式：\\n\\n<quick-replies>[\"選項1\",\"選項2\"]</quick-replies>。最多 3 個選項，需短、自然、可直接點擊送出；若不適合提供，就不要附加任何 quick reply 區塊。";
    }

    private IEnumerable<GeminiAttempt> BuildAttempts()
    {
        for (var i = 0; i < _apiKeys.Count; i++)
            yield return new GeminiAttempt(_apiKeys[i], _model, i == 0 ? "primary" : "secondary", "primary");

        if (!string.Equals(_model, _fallbackModel, StringComparison.OrdinalIgnoreCase))
        {
            for (var i = 0; i < _apiKeys.Count; i++)
                yield return new GeminiAttempt(_apiKeys[i], _fallbackModel, i == 0 ? "primary" : "secondary", "fallback");
        }
    }

    private static GeminiFailureDisposition ClassifyFailure(HttpStatusCode statusCode, string errorBody)
    {
        if (statusCode == HttpStatusCode.TooManyRequests)
            return GeminiFailureDisposition.TryOtherGeminiRoutes;

        if ((int)statusCode is >= 500 and <= 599)
            return GeminiFailureDisposition.TryOtherGeminiRoutes;

        if (IsQuotaOrResourceExhausted(errorBody))
            return GeminiFailureDisposition.TryOtherGeminiRoutes;

        if (statusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden)
            return GeminiFailureDisposition.TryOtherKeysOnly;

        return GeminiFailureDisposition.Stop;
    }

    private static bool IsQuotaOrResourceExhausted(string? message)
    {
        if (string.IsNullOrWhiteSpace(message))
            return false;

        var normalized = message.ToLowerInvariant();
        return normalized.Contains("quota")
            || normalized.Contains("resource_exhausted")
            || normalized.Contains("rpd")
            || normalized.Contains("daily")
            || normalized.Contains("limit exceeded")
            || normalized.Contains("exceeded your current quota");
    }

    private Task<HttpResponseMessage> SendGenerateAsync(string model, string apiKey, object payload, CancellationToken ct)
    {
        var url = $"{_endpoint.TrimEnd('/')}/{model}:generateContent?key={apiKey}";
        var body = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
        var request = new HttpRequestMessage(HttpMethod.Post, url) { Content = body };
        return _http.SendAsync(request, ct);
    }

    private enum GeminiFailureDisposition
    {
        Stop,
        TryOtherGeminiRoutes,
        TryOtherKeysOnly
    }

    private sealed record GeminiAttempt(string ApiKey, string Model, string KeySlot, string ModelSlot);
}

