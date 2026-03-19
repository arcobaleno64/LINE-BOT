using System.Net;

namespace LineBotWebhook.Services;

public class FailoverAiService : IAiService
{
    private readonly IReadOnlyList<ProviderEntry> _providers;
    private readonly ILogger<FailoverAiService> _logger;

    public FailoverAiService(
        IHttpClientFactory httpClientFactory,
        IConfiguration config,
        ConversationHistoryService history,
        ILogger<FailoverAiService> logger)
    {
        _logger = logger;
        _providers = BuildProviders(httpClientFactory, config, history);

        if (_providers.Count == 0)
            throw new InvalidOperationException("No AI providers are configured. Please set at least one provider API key.");
    }

    public Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default)
        => ExecuteWithFailoverAsync(
            provider => provider.Service.GetReplyAsync(userMessage, userKey, ct),
            "text");

    public Task<string> GetReplyFromImageAsync(byte[] imageBytes, string mimeType, string userPrompt, string userKey, CancellationToken ct = default)
        => ExecuteWithFailoverAsync(
            provider => provider.Service.GetReplyFromImageAsync(imageBytes, mimeType, userPrompt, userKey, ct),
            "image");

    public Task<string> GetReplyFromDocumentAsync(string fileName, string mimeType, string extractedText, string userPrompt, string userKey, CancellationToken ct = default)
        => ExecuteWithFailoverAsync(
            provider => provider.Service.GetReplyFromDocumentAsync(fileName, mimeType, extractedText, userPrompt, userKey, ct),
            "document");

    private async Task<string> ExecuteWithFailoverAsync(Func<ProviderEntry, Task<string>> call, string requestType)
    {
        Exception? lastException = null;

        foreach (var provider in _providers)
        {
            try
            {
                var reply = await call(provider);
                _logger.LogInformation("AI request ({RequestType}) served by provider {Provider}", requestType, provider.Name);
                return reply;
            }
            catch (Exception ex) when (ShouldFailover(ex))
            {
                _logger.LogWarning(ex, "Provider {Provider} failed for {RequestType}; trying next provider", provider.Name, requestType);
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
        }

        return ex.InnerException is not null && ShouldFailover(ex.InnerException);
    }

    private static IReadOnlyList<ProviderEntry> BuildProviders(IHttpClientFactory httpClientFactory, IConfiguration config, ConversationHistoryService history)
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
            var provider = TryCreateProvider(name, httpClientFactory, config, history);
            if (provider is not null)
                providers.Add(provider);
        }

        return providers;
    }

    private static ProviderEntry? TryCreateProvider(string name, IHttpClientFactory httpClientFactory, IConfiguration config, ConversationHistoryService history)
    {
        if (name.Equals("Gemini", StringComparison.OrdinalIgnoreCase))
        {
            if (string.IsNullOrWhiteSpace(config["Ai:Gemini:ApiKey"]))
                return null;

            return new ProviderEntry("Gemini", new GeminiService(httpClientFactory.CreateClient(), config, history));
        }

        if (name.Equals("OpenAI", StringComparison.OrdinalIgnoreCase))
        {
            if (string.IsNullOrWhiteSpace(config["Ai:OpenAI:ApiKey"]))
                return null;

            return new ProviderEntry("OpenAI", new OpenAiService(httpClientFactory.CreateClient(), config, history));
        }

        if (name.Equals("Claude", StringComparison.OrdinalIgnoreCase))
        {
            if (string.IsNullOrWhiteSpace(config["Ai:Claude:ApiKey"]))
                return null;

            return new ProviderEntry("Claude", new ClaudeService(httpClientFactory.CreateClient(), config, history));
        }

        return null;
    }

    private sealed record ProviderEntry(string Name, IAiService Service);
}
