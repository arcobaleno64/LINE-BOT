using System.Net;
using LineBotWebhook.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;

namespace LineBotWebhook.Tests;

public class FailoverAiServiceTests
{
    [Fact]
    public void PlaceholderOpenAiKey_IsIgnored_WhenBuildingProviders()
    {
        var config = TestFactory.BuildConfig(new Dictionary<string, string?>
        {
            ["Ai:Provider"] = "Gemini",
            ["Ai:FallbackProvider"] = "OpenAI",
            ["Ai:Gemini:ApiKey"] = "gemini-primary-key",
            ["Ai:OpenAI:ApiKey"] = "<YOUR_OPENAI_API_KEY>"
        });

        var service = new FailoverAiService(
            new StubHttpClientFactory(new HttpClient(new RecordingHttpMessageHandler((request, ct) =>
                Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK))))),
            config,
            new ConversationHistoryService(),
            NullLogger<FailoverAiService>.Instance);

        var providers = GetProviderNames(service);

        Assert.Equal(["Gemini"], providers);
    }

    private static string[] GetProviderNames(FailoverAiService service)
    {
        var field = typeof(FailoverAiService).GetField("_providers", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)!;
        var providers = (System.Collections.IEnumerable)field.GetValue(service)!;
        return providers
            .Cast<object>()
            .Select(p => (string)p.GetType().GetProperty("Name")!.GetValue(p)!)
            .ToArray();
    }
}

internal sealed class StubHttpClientFactory(HttpClient client) : IHttpClientFactory
{
    public HttpClient CreateClient(string name) => client;
}
