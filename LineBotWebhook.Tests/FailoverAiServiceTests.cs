using System.Net;
using LineBotWebhook.Services;
using Microsoft.Extensions.Logging;
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
    public async Task GeminiAllRetryableRoutesExhausted_FallsBackToClaude_WhenConfigured()
    {
        var requests = new List<string>();
        var handler = CreateRoutingHandler(requests, request =>
        {
            var uri = request.RequestUri!.ToString();
            return uri.Contains("generativelanguage.googleapis.com", StringComparison.Ordinal)
                ? BuildGeminiError(HttpStatusCode.ServiceUnavailable, """{"error":{"message":"temporary upstream outage"}}""")
                : uri.Contains("api.anthropic.com", StringComparison.Ordinal)
                    ? BuildClaudeSuccess("Claude 接手成功")
                    : throw new InvalidOperationException($"Unexpected uri: {uri}");
        });

        var service = CreateService(
            handler,
            new Dictionary<string, string?>
            {
                ["Ai:Provider"] = "Gemini",
                ["Ai:FallbackProvider"] = "Claude",
                ["Ai:Gemini:ApiKey"] = "primary-key",
                ["Ai:Gemini:SecondaryApiKey"] = "secondary-key",
                ["Ai:Gemini:Model"] = "gemini-2.5-flash",
                ["Ai:Gemini:FallbackModel"] = "gemini-2.0-flash-lite",
                ["Ai:OpenAI:ApiKey"] = "openai-key",
                ["Ai:Claude:ApiKey"] = "claude-key"
            });

        var reply = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.Equal("Claude 接手成功", reply);
        Assert.Equal(5, requests.Count);
        Assert.Collection(
            requests.Take(4),
            uri => AssertGeminiAttempt(uri, "primary-key", "gemini-2.5-flash"),
            uri => AssertGeminiAttempt(uri, "secondary-key", "gemini-2.5-flash"),
            uri => AssertGeminiAttempt(uri, "primary-key", "gemini-2.0-flash-lite"),
            uri => AssertGeminiAttempt(uri, "secondary-key", "gemini-2.0-flash-lite"));
        Assert.Contains("api.anthropic.com/v1/messages", requests[4], StringComparison.Ordinal);
        Assert.DoesNotContain(requests, uri => uri.Contains("api.openai.com", StringComparison.Ordinal));
    }

    [Fact]
    public async Task NonRetryableBadRequest_DoesNotBlindlyFailOverAcrossProviders()
    {
        var requests = new List<string>();
        var handler = CreateRoutingHandler(requests, request =>
        {
            var uri = request.RequestUri!.ToString();
            return uri.Contains("generativelanguage.googleapis.com", StringComparison.Ordinal)
                ? BuildGeminiError(HttpStatusCode.BadRequest, """{"error":{"message":"invalid request payload"}}""")
                : throw new InvalidOperationException($"Unexpected uri: {uri}");
        });

        var service = CreateService(
            handler,
            new Dictionary<string, string?>
            {
                ["Ai:Provider"] = "Gemini",
                ["Ai:FallbackProvider"] = "OpenAI",
                ["Ai:Gemini:ApiKey"] = "primary-key",
                ["Ai:Gemini:SecondaryApiKey"] = "secondary-key",
                ["Ai:OpenAI:ApiKey"] = "openai-key",
                ["Ai:Claude:ApiKey"] = "claude-key"
            });

        var ex = await Assert.ThrowsAsync<HttpRequestException>(() => service.GetReplyAsync("你好", "u1", CancellationToken.None));

        Assert.Single(requests);
        Assert.Equal(HttpStatusCode.BadRequest, ex.StatusCode);
        Assert.DoesNotContain(requests, uri => uri.Contains("api.openai.com", StringComparison.Ordinal));
        Assert.DoesNotContain(requests, uri => uri.Contains("api.anthropic.com", StringComparison.Ordinal));
    }

    [Fact]
    public async Task RetryableServerError_FailsOverToNextProvider()
    {
        var requests = new List<string>();
        var handler = CreateRoutingHandler(requests, request =>
        {
            var uri = request.RequestUri!.ToString();
            return uri.Contains("api.openai.com", StringComparison.Ordinal)
                ? new HttpResponseMessage(HttpStatusCode.BadGateway)
                : uri.Contains("api.anthropic.com", StringComparison.Ordinal)
                    ? BuildClaudeSuccess("Claude 5xx failover 成功")
                    : throw new InvalidOperationException($"Unexpected uri: {uri}");
        });

        var service = CreateService(
            handler,
            new Dictionary<string, string?>
            {
                ["Ai:Provider"] = "OpenAI",
                ["Ai:FallbackProvider"] = "Claude",
                ["Ai:OpenAI:ApiKey"] = "openai-key",
                ["Ai:Claude:ApiKey"] = "claude-key"
            });

        var reply = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.Equal("Claude 5xx failover 成功", reply);
        Assert.Equal(2, requests.Count);
        Assert.Contains("api.openai.com/v1/chat/completions", requests[0], StringComparison.Ordinal);
        Assert.Contains("api.anthropic.com/v1/messages", requests[1], StringComparison.Ordinal);
    }

    [Fact]
    public async Task RetryableQuotaOrResourceExhausted_FailsOverToNextProvider()
    {
        var requests = new List<string>();
        var handler = CreateRoutingHandler(requests, request =>
        {
            var uri = request.RequestUri!.ToString();
            return uri.Contains("generativelanguage.googleapis.com", StringComparison.Ordinal)
                ? BuildGeminiError(HttpStatusCode.BadRequest, """{"error":{"message":"resource_exhausted: daily quota exceeded"}}""")
                : uri.Contains("api.openai.com", StringComparison.Ordinal)
                    ? BuildOpenAiSuccess("OpenAI quota failover 成功")
                    : throw new InvalidOperationException($"Unexpected uri: {uri}");
        });

        var service = CreateService(
            handler,
            new Dictionary<string, string?>
            {
                ["Ai:Provider"] = "Gemini",
                ["Ai:FallbackProvider"] = "OpenAI",
                ["Ai:Gemini:ApiKey"] = "primary-key",
                ["Ai:Gemini:SecondaryApiKey"] = "secondary-key",
                ["Ai:Gemini:Model"] = "gemini-2.5-flash",
                ["Ai:Gemini:FallbackModel"] = "gemini-2.0-flash-lite",
                ["Ai:OpenAI:ApiKey"] = "openai-key"
            });

        var reply = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.Equal("OpenAI quota failover 成功", reply);
        Assert.Equal(5, requests.Count);
        Assert.Collection(
            requests.Take(4),
            uri => AssertGeminiAttempt(uri, "primary-key", "gemini-2.5-flash"),
            uri => AssertGeminiAttempt(uri, "secondary-key", "gemini-2.5-flash"),
            uri => AssertGeminiAttempt(uri, "primary-key", "gemini-2.0-flash-lite"),
            uri => AssertGeminiAttempt(uri, "secondary-key", "gemini-2.0-flash-lite"));
        Assert.Contains("api.openai.com/v1/chat/completions", requests[4], StringComparison.Ordinal);
    }

    [Fact]
    public async Task ProviderFailoverWarning_Log_DoesNotLeakRawProviderPayload()
    {
        var requests = new List<string>();
        var logger = new TestLogger<FailoverAiService>();
        var handler = CreateRoutingHandler(requests, request =>
        {
            var uri = request.RequestUri!.ToString();
            return uri.Contains("generativelanguage.googleapis.com", StringComparison.Ordinal)
                ? BuildGeminiError(HttpStatusCode.ServiceUnavailable, """{"error":{"message":"resource_exhausted apiKey=secret-key fileToken=file-token-123"}}""")
                : uri.Contains("api.openai.com", StringComparison.Ordinal)
                    ? BuildOpenAiSuccess("OpenAI 接手成功")
                    : throw new InvalidOperationException($"Unexpected uri: {uri}");
        });

        var service = CreateService(
            handler,
            new Dictionary<string, string?>
            {
                ["Ai:Provider"] = "Gemini",
                ["Ai:FallbackProvider"] = "OpenAI",
                ["Ai:Gemini:ApiKey"] = "primary-key",
                ["Ai:Gemini:SecondaryApiKey"] = "secondary-key",
                ["Ai:Gemini:Model"] = "gemini-2.5-flash",
                ["Ai:Gemini:FallbackModel"] = "gemini-2.0-flash-lite",
                ["Ai:OpenAI:ApiKey"] = "openai-key"
            },
            logger);

        var reply = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.Equal("OpenAI 接手成功", reply);
        var warning = Assert.Single(logger.Entries, entry => entry.Level == LogLevel.Warning && entry.Message.Contains("trying next provider", StringComparison.Ordinal));
        Assert.Null(warning.Exception);
        Assert.Equal("Gemini", warning.Properties["Provider"]);
        Assert.Equal("text", warning.Properties["RequestType"]);
        Assert.Equal(503, warning.Properties["StatusCode"]);
        Assert.Equal(true, warning.Properties["IsQuotaExhausted"]);
        Assert.DoesNotContain("secret-key", warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("file-token-123", warning.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task ImagePath_PlaceholderResponses_AreNotTreatedAsSuccessfulAnalysis()
    {
        var requests = new List<string>();
        var logger = new TestLogger<FailoverAiService>();
        var handler = CreateRoutingHandler(requests, request =>
        {
            var uri = request.RequestUri!.ToString();
            return uri.Contains("generativelanguage.googleapis.com", StringComparison.Ordinal)
                ? BuildGeminiError(HttpStatusCode.TooManyRequests, """{"error":{"message":"rate limit temporary"}}""")
                : uri.Contains("api.openai.com", StringComparison.Ordinal)
                    ? BuildOpenAiSuccess("抱歉，目前提供者未啟用圖片解析，建議改用 Gemini 或補充文字描述。")
                    : uri.Contains("api.anthropic.com", StringComparison.Ordinal)
                        ? BuildClaudeSuccess("抱歉，目前提供者未啟用圖片解析，建議改用 Gemini 或補充文字描述。")
                        : throw new InvalidOperationException($"Unexpected uri: {uri}");
        });

        var service = CreateService(
            handler,
            new Dictionary<string, string?>
            {
                ["Ai:Provider"] = "Gemini",
                ["Ai:FallbackProvider"] = "OpenAI",
                ["Ai:Gemini:ApiKey"] = "primary-key",
                ["Ai:Gemini:SecondaryApiKey"] = "secondary-key",
                ["Ai:Gemini:Model"] = "gemini-2.5-flash",
                ["Ai:Gemini:FallbackModel"] = "gemini-2.0-flash-lite",
                ["Ai:OpenAI:ApiKey"] = "openai-key",
                ["Ai:Claude:ApiKey"] = "claude-key"
            },
            logger);

        await Assert.ThrowsAsync<HttpRequestException>(() =>
            service.GetReplyFromImageAsync([1, 2, 3], "image/png", "請分析這張圖", "u1", CancellationToken.None));

        Assert.Equal(6, requests.Count);
        Assert.Contains(requests, uri => uri.Contains("api.openai.com", StringComparison.Ordinal));
        Assert.Contains(requests, uri => uri.Contains("api.anthropic.com", StringComparison.Ordinal));
        Assert.Contains(logger.Entries, entry => entry.Message.Contains("does not provide real image analysis", StringComparison.Ordinal));
    }

    [Fact]
    public async Task TextPath_Regression_StillWorks()
    {
        var requests = new List<string>();
        var handler = CreateRoutingHandler(requests, request =>
        {
            var uri = request.RequestUri!.ToString();
            return uri.Contains("generativelanguage.googleapis.com", StringComparison.Ordinal)
                ? BuildGeminiError(HttpStatusCode.ServiceUnavailable, """{"error":{"message":"temporary outage"}}""")
                : uri.Contains("api.openai.com", StringComparison.Ordinal)
                    ? BuildOpenAiSuccess("OpenAI 文字接手成功")
                    : throw new InvalidOperationException($"Unexpected uri: {uri}");
        });

        var service = CreateService(
            handler,
            new Dictionary<string, string?>
            {
                ["Ai:Provider"] = "Gemini",
                ["Ai:FallbackProvider"] = "OpenAI",
                ["Ai:Gemini:ApiKey"] = "primary-key",
                ["Ai:Gemini:SecondaryApiKey"] = "secondary-key",
                ["Ai:Gemini:Model"] = "gemini-2.5-flash",
                ["Ai:Gemini:FallbackModel"] = "gemini-2.0-flash-lite",
                ["Ai:OpenAI:ApiKey"] = "openai-key"
            });

        var reply = await service.GetReplyAsync("請簡述今天重點", "u1", CancellationToken.None);

        Assert.Equal("OpenAI 文字接手成功", reply);
        Assert.Contains("api.openai.com/v1/chat/completions", requests.Last(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task DocumentPath_Regression_StillWorks()
    {
        var requests = new List<string>();
        var handler = CreateRoutingHandler(requests, request =>
        {
            var uri = request.RequestUri!.ToString();
            return uri.Contains("generativelanguage.googleapis.com", StringComparison.Ordinal)
                ? BuildGeminiError(HttpStatusCode.ServiceUnavailable, """{"error":{"message":"temporary outage"}}""")
                : uri.Contains("api.openai.com", StringComparison.Ordinal)
                    ? BuildOpenAiSuccess("OpenAI 文件接手成功")
                    : throw new InvalidOperationException($"Unexpected uri: {uri}");
        });

        var service = CreateService(
            handler,
            new Dictionary<string, string?>
            {
                ["Ai:Provider"] = "Gemini",
                ["Ai:FallbackProvider"] = "OpenAI",
                ["Ai:Gemini:ApiKey"] = "primary-key",
                ["Ai:Gemini:SecondaryApiKey"] = "secondary-key",
                ["Ai:Gemini:Model"] = "gemini-2.5-flash",
                ["Ai:Gemini:FallbackModel"] = "gemini-2.0-flash-lite",
                ["Ai:OpenAI:ApiKey"] = "openai-key"
            });

        var reply = await service.GetReplyFromDocumentAsync("contract.txt", "text/plain", "付款條款如下", "請整理重點", "u1", CancellationToken.None);

        Assert.Equal("OpenAI 文件接手成功", reply);
        Assert.Contains("api.openai.com/v1/chat/completions", requests.Last(), StringComparison.Ordinal);
    }

    private static FailoverAiService CreateService(
        RecordingHttpMessageHandler handler,
        Dictionary<string, string?> overrides,
        ILogger<FailoverAiService>? logger = null)
    {
        var config = TestFactory.BuildConfig(overrides);

        return new FailoverAiService(
            new StubHttpClientFactory(new HttpClient(handler)),
            config,
            new ConversationHistoryService(),
            NullLoggerFactory.Instance,
            logger ?? NullLogger<FailoverAiService>.Instance);
    }

    private static RecordingHttpMessageHandler CreateRoutingHandler(
        List<string> requests,
        Func<HttpRequestMessage, HttpResponseMessage> responder)
    {
        return new RecordingHttpMessageHandler((request, ct) =>
        {
            var uri = request.RequestUri!.ToString();
            if (request.Headers.TryGetValues("x-goog-api-key", out var keys))
                uri += (uri.Contains('?') ? "&" : "?") + $"key={keys.First()}";
            requests.Add(uri);
            return Task.FromResult(responder(request));
        });
    }

    private static HttpResponseMessage BuildGeminiError(HttpStatusCode statusCode, string body)
        => new(statusCode)
        {
            Content = new StringContent(body)
        };

    private static HttpResponseMessage BuildOpenAiSuccess(string text)
        => new(HttpStatusCode.OK)
        {
            Content = new StringContent($"{{\"choices\":[{{\"message\":{{\"content\":\"{text}\"}}}}]}}")
        };

    private static HttpResponseMessage BuildClaudeSuccess(string text)
        => new(HttpStatusCode.OK)
        {
            Content = new StringContent($"{{\"content\":[{{\"text\":\"{text}\"}}]}}")
        };

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
