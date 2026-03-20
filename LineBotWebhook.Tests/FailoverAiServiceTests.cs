using System.Net;
using LineBotWebhook.Services;
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
            NullLoggerFactory.Instance,
            NullLogger<FailoverAiService>.Instance);

        var providers = GetProviderNames(service);

        Assert.Equal(["Gemini"], providers);
    }

    [Fact]
    public async Task GeminiRetryableFailures_FallBackToOpenAi_AfterAllGeminiRoutesAreExhausted()
    {
        var requests = new List<string>();
        var handler = new RecordingHttpMessageHandler((request, ct) =>
        {
            var uri = request.RequestUri!.ToString();
            requests.Add(uri);

            if (uri.Contains("generativelanguage.googleapis.com", StringComparison.Ordinal))
            {
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.TooManyRequests)
                {
                    Content = new StringContent("""{"error":{"message":"resource_exhausted"}}""")
                });
            }

            if (uri.Contains("api.openai.com", StringComparison.Ordinal))
            {
                return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent("""
                    {"choices":[{"message":{"content":"OpenAI 接手成功"}}]}
                    """)
                });
            }

            throw new InvalidOperationException($"Unexpected uri: {uri}");
        });

        var config = TestFactory.BuildConfig(new Dictionary<string, string?>
        {
            ["Ai:Provider"] = "Gemini",
            ["Ai:FallbackProvider"] = "OpenAI",
            ["Ai:Gemini:ApiKey"] = "primary-key",
            ["Ai:Gemini:SecondaryApiKey"] = "secondary-key",
            ["Ai:Gemini:Model"] = "gemini-2.5-flash",
            ["Ai:Gemini:FallbackModel"] = "gemini-2.0-flash-lite",
            ["Ai:OpenAI:ApiKey"] = "openai-key"
        });

        var service = new FailoverAiService(
            new StubHttpClientFactory(new HttpClient(handler)),
            config,
            new ConversationHistoryService(),
            NullLoggerFactory.Instance,
            NullLogger<FailoverAiService>.Instance);

        var reply = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.Equal("OpenAI 接手成功", reply);
        Assert.Equal(5, requests.Count);
        Assert.Collection(
            requests.Take(4),
            uri => AssertGeminiAttempt(uri, "primary-key", "gemini-2.5-flash"),
            uri => AssertGeminiAttempt(uri, "secondary-key", "gemini-2.5-flash"),
            uri => AssertGeminiAttempt(uri, "primary-key", "gemini-2.0-flash-lite"),
            uri => AssertGeminiAttempt(uri, "secondary-key", "gemini-2.0-flash-lite"));
        Assert.Contains("api.openai.com/v1/chat/completions", requests[4], StringComparison.Ordinal);
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

    private static void AssertGeminiAttempt(string requestUri, string expectedKey, string expectedModel)
    {
        Assert.Contains($"key={expectedKey}", requestUri, StringComparison.Ordinal);
        Assert.Contains(expectedModel, requestUri, StringComparison.Ordinal);
    }
}

internal sealed class StubHttpClientFactory(HttpClient client) : IHttpClientFactory
{
    public HttpClient CreateClient(string name) => client;
}
