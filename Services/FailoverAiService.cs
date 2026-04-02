using System.Net;

namespace LineBotWebhook.Services;

public class FailoverAiService : IAiService
{
    private readonly IReadOnlyList<ProviderEntry> _providers;
    private readonly ILogger<FailoverAiService> _logger;

    private readonly PersonaContext _persona;

    public FailoverAiService(
        IHttpClientFactory httpClientFactory,
        IConfiguration config,
        ConversationHistoryService history,
        ILoggerFactory loggerFactory,
        PersonaContext persona,
        ILogger<FailoverAiService> logger)
    {
        _logger = logger;
        _persona = persona;
        _providers = BuildProviders(httpClientFactory, config, history, loggerFactory, persona);

        if (_providers.Count == 0)
            throw new InvalidOperationException("No AI providers are configured. Please set at least one provider API key.");
    }

    public Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default, bool enableQuickReplies = false)
        => ExecuteWithFailoverAsync(
            provider => provider.Service.GetReplyAsync(userMessage, userKey, ct, enableQuickReplies),
            "text");

    public Task<string> GetReplyFromImageAsync(byte[] imageBytes, string mimeType, string userPrompt, string userKey, CancellationToken ct = default)
        => ExecuteWithFailoverAsync(
            provider => provider.Service.GetReplyFromImageAsync(imageBytes, mimeType, userPrompt, userKey, ct),
            "image");

    public Task<string> GetReplyFromDocumentAsync(string fileName, string mimeType, string extractedText, string userPrompt, string userKey, CancellationToken ct = default)
        => ExecuteWithFailoverAsync(
            provider => provider.Service.GetReplyFromDocumentAsync(fileName, mimeType, extractedText, userPrompt, userKey, ct),
            "document");

    public Task<string> GenerateStatelessReplyAsync(string prompt, CancellationToken ct = default)
        => ExecuteWithFailoverAsync(
            provider => provider.Service.GenerateStatelessReplyAsync(prompt, ct),
            "stateless");

    private async Task<string> ExecuteWithFailoverAsync(Func<ProviderEntry, Task<string>> call, string requestType)
    {
        Exception? lastException = null;

        foreach (var provider in _providers)
        {
            try
            {
                var reply = await call(provider);
                if (IsImageCapabilityPlaceholder(provider.Name, requestType, reply))
                {
                    _logger.LogWarning(
                        "Provider {Provider} does not provide real image analysis for {RequestType}; trying next provider.",
                        provider.Name,
                        requestType);
                    continue;
                }

                _logger.LogInformation("AI request ({RequestType}) served by provider {Provider}", requestType, provider.Name);
                return reply;
            }
            catch (Exception ex) when (ShouldFailover(ex))
            {
                _logger.LogWarning(
                    "Provider {Provider} failed for {RequestType}; trying next provider. StatusCode={StatusCode} IsQuotaExhausted={IsQuotaExhausted}",
                    provider.Name,
                    requestType,
                    GetStatusCode(ex),
                    IsQuotaOrResourceExhausted(ex));
                lastException = ex;
            }
        }

        if (lastException is not null)
            throw lastException;

        throw new InvalidOperationException("AI call failed without a captured exception.");
    }

    private static bool ShouldFailover(Exception ex)
    {
        if (ex is HttpRequestException httpEx)
        {
            if (httpEx.StatusCode == HttpStatusCode.TooManyRequests)
                return true;

            if ((int?)httpEx.StatusCode is >= 500 and <= 599)
                return true;

            if (IsQuotaOrResourceExhausted(httpEx.Message))
                return true;
        }

        return ex.InnerException is not null && ShouldFailover(ex.InnerException);
    }

    private static IReadOnlyList<ProviderEntry> BuildProviders(IHttpClientFactory httpClientFactory, IConfiguration config, ConversationHistoryService history, ILoggerFactory loggerFactory, PersonaContext persona)
    {
        var primary = (config["Ai:Provider"] ?? "Gemini").Trim();
        var fallback = config["Ai:FallbackProvider"]?.Trim();

        var orderedNames = new List<string> { primary };
        if (!string.IsNullOrWhiteSpace(fallback))
            orderedNames.Add(fallback!);

        orderedNames.AddRange(["Gemini", "OpenAI", "Claude"]);

        var providers = new List<ProviderEntry>();
        foreach (var name in orderedNames.Distinct(StringComparer.OrdinalIgnoreCase))
        {
            var provider = TryCreateProvider(name, httpClientFactory, config, history, persona);
            var provider = TryCreateProvider(name, httpClientFactory, config, history, loggerFactory, persona);
            if (provider is not null)
                providers.Add(provider);
        }

        return providers;
    }

    private static ProviderEntry? TryCreateProvider(string name, IHttpClientFactory httpClientFactory, IConfiguration config, ConversationHistoryService history, ILoggerFactory loggerFactory, PersonaContext persona)
    {
        if (name.Equals("Gemini", StringComparison.OrdinalIgnoreCase))
        {
            if (AiConfigurationHelpers.GetConfiguredValues(config, "Ai:Gemini:ApiKey", "Ai:Gemini:SecondaryApiKey").Count == 0)
                return null;

            return new ProviderEntry("Gemini", new GeminiService(httpClientFactory.CreateClient(), config, history, persona));
        return new ProviderEntry("Gemini", new GeminiService(httpClientFactory.CreateClient(), config, history, persona, loggerFactory.CreateLogger<GeminiService>()));
        }

        if (name.Equals("OpenAI", StringComparison.OrdinalIgnoreCase))
        {
            if (AiConfigurationHelpers.GetConfiguredValue(config, "Ai:OpenAI:ApiKey") is null)
                return null;

            return new ProviderEntry("OpenAI", new OpenAiService(httpClientFactory.CreateClient(), config, history, persona));
        }

        if (name.Equals("Claude", StringComparison.OrdinalIgnoreCase))
        {
            if (AiConfigurationHelpers.GetConfiguredValue(config, "Ai:Claude:ApiKey") is null)
                return null;

            return new ProviderEntry("Claude", new ClaudeService(httpClientFactory.CreateClient(), config, history, persona));
        }

        return null;
    }

    private static int? GetStatusCode(Exception ex)
    {
        if (ex is HttpRequestException httpEx && httpEx.StatusCode is HttpStatusCode statusCode)
            return (int)statusCode;

        return ex.InnerException is not null ? GetStatusCode(ex.InnerException) : null;
    }

    private static bool IsQuotaOrResourceExhausted(Exception ex)
    {
        if (ex is HttpRequestException httpEx && IsQuotaOrResourceExhausted(httpEx.Message))
            return true;

        return ex.InnerException is not null && IsQuotaOrResourceExhausted(ex.InnerException);
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

    private static bool IsImageCapabilityPlaceholder(string providerName, string requestType, string reply)
    {
        if (!requestType.Equals("image", StringComparison.OrdinalIgnoreCase))
            return false;

        if (!providerName.Equals("OpenAI", StringComparison.OrdinalIgnoreCase)
            && !providerName.Equals("Claude", StringComparison.OrdinalIgnoreCase))
            return false;

        if (string.IsNullOrWhiteSpace(reply))
            return false;

        var normalized = reply.ToLowerInvariant();
        return normalized.Contains("未啟用圖片解析", StringComparison.Ordinal)
            || normalized.Contains("改用 gemini", StringComparison.Ordinal)
            || normalized.Contains("補充文字描述", StringComparison.Ordinal);
    }

    private sealed record ProviderEntry(string Name, IAiService Service);
}
