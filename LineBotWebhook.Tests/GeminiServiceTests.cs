using System.Net;
using LineBotWebhook.Services;

namespace LineBotWebhook.Tests;

public class GeminiServiceTests
{
    [Fact]
    public async Task PrimaryKey_PrimaryModel_Succeeds_WithoutUsingSecondary()
    {
        var attempts = new List<string>();
        var logger = new TestLogger<GeminiService>();
        var service = CreateService(
            attempts,
            logger,
            static attempt => BuildSuccessResponse("primary 成功"));

        var reply = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.Equal("primary 成功", reply);
        Assert.Single(attempts);
        AssertAttempt(attempts[0], "primary-key", "gemini-2.5-flash");
        var successLog = Assert.Single(logger.Entries, x => x.Message.Contains("Gemini request served", StringComparison.Ordinal));
        Assert.Equal("Gemini", successLog.Properties["Provider"]);
        Assert.Equal("text", successLog.Properties["RequestType"]);
        Assert.Equal("primary", successLog.Properties["KeySlot"]);
        Assert.Equal("primary", successLog.Properties["ModelSlot"]);
    }

    [Fact]
    public async Task Primary429_UsesSecondaryKey_OnPrimaryModel()
    {
        var attempts = new List<string>();
        var service = CreateService(
            attempts,
            new TestLogger<GeminiService>(),
            attempt => attempt switch
            {
                0 => new HttpResponseMessage(HttpStatusCode.TooManyRequests)
                {
                    Content = new StringContent("""{"error":{"message":"rate limit temporary"}}""")
                },
                _ => BuildSuccessResponse("第二把 key 成功")
            });

        var reply = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.Equal("第二把 key 成功", reply);
        Assert.Equal(2, attempts.Count);
        AssertAttempt(attempts[0], "primary-key", "gemini-2.5-flash");
        AssertAttempt(attempts[1], "secondary-key", "gemini-2.5-flash");
    }

    [Fact]
    public async Task PrimaryModel_BothKeysFail_ThenFallsBackToPrimaryKey_FallbackModel()
    {
        var attempts = new List<string>();
        var service = CreateService(
            attempts,
            new TestLogger<GeminiService>(),
            attempt => attempt switch
            {
                0 or 1 => new HttpResponseMessage(HttpStatusCode.TooManyRequests)
                {
                    Content = new StringContent("""{"error":{"message":"resource_exhausted"}}""")
                },
                _ => BuildSuccessResponse("fallback model 成功")
            });

        var reply = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.Equal("fallback model 成功", reply);
        Assert.Equal(3, attempts.Count);
        AssertAttempt(attempts[0], "primary-key", "gemini-2.5-flash");
        AssertAttempt(attempts[1], "secondary-key", "gemini-2.5-flash");
        AssertAttempt(attempts[2], "primary-key", "gemini-2.0-flash-lite");
    }

    [Fact]
    public async Task ImagePath_UsesSecondaryKey_WhenPrimaryHits429()
    {
        var attempts = new List<string>();
        var service = CreateService(
            attempts,
            new TestLogger<GeminiService>(),
            attempt => attempt == 0
                ? new HttpResponseMessage(HttpStatusCode.TooManyRequests)
                {
                    Content = new StringContent("""{"error":{"message":"rate limit temporary"}}""")
                }
                : BuildSuccessResponse("圖片成功"));

        var reply = await service.GetReplyFromImageAsync([1, 2, 3], "image/png", "請分析", "u1", CancellationToken.None);

        Assert.Equal("圖片成功", reply);
        Assert.Equal(2, attempts.Count);
        AssertAttempt(attempts[0], "primary-key", "gemini-2.5-flash");
        AssertAttempt(attempts[1], "secondary-key", "gemini-2.5-flash");
    }

    [Fact]
    public async Task DocumentPath_UsesSecondaryKey_WhenPrimaryHits429()
    {
        var attempts = new List<string>();
        var logger = new TestLogger<GeminiService>();
        var service = CreateService(
            attempts,
            logger,
            attempt => attempt == 0
                ? new HttpResponseMessage(HttpStatusCode.TooManyRequests)
                {
                    Content = new StringContent("""{"error":{"message":"rate limit temporary"}}""")
                }
                : BuildSuccessResponse("文件成功"));

        var reply = await service.GetReplyFromDocumentAsync("doc.txt", "text/plain", "文件內容", "請整理", "u1", CancellationToken.None);

        Assert.Equal("文件成功", reply);
        Assert.Equal(2, attempts.Count);
        AssertAttempt(attempts[0], "primary-key", "gemini-2.5-flash");
        AssertAttempt(attempts[1], "secondary-key", "gemini-2.5-flash");
        var successLog = Assert.Single(logger.Entries, x => x.Message.Contains("Gemini request served", StringComparison.Ordinal));
        Assert.Equal("document", successLog.Properties["RequestType"]);
    }

    [Fact]
    public async Task UnauthorizedPrimaryKey_DoesNotTryFallbackModel_WithSameKey()
    {
        var attempts = new List<string>();
        var service = CreateService(
            attempts,
            new TestLogger<GeminiService>(),
            attempt => attempt == 0
                ? new HttpResponseMessage(HttpStatusCode.Unauthorized)
                {
                    Content = new StringContent("""{"error":{"message":"invalid api key"}}""")
                }
                : BuildSuccessResponse("第二把 key 成功"));

        var reply = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.Equal("第二把 key 成功", reply);
        Assert.Equal(2, attempts.Count);
        AssertAttempt(attempts[0], "primary-key", "gemini-2.5-flash");
        AssertAttempt(attempts[1], "secondary-key", "gemini-2.5-flash");
        Assert.DoesNotContain(attempts, static uri => uri.Contains("key=primary-key", StringComparison.Ordinal) && uri.Contains("gemini-2.0-flash-lite", StringComparison.Ordinal));
    }

    [Fact]
    public async Task BadRequest_DoesNotBlindlyRetry_AllGeminiRoutes()
    {
        var attempts = new List<string>();
        var service = CreateService(
            attempts,
            new TestLogger<GeminiService>(),
            static _ => new HttpResponseMessage(HttpStatusCode.BadRequest)
            {
                Content = new StringContent("""{"error":{"message":"invalid request payload"}}""")
            });

        var ex = await Assert.ThrowsAsync<HttpRequestException>(() => service.GetReplyAsync("你好", "u1", CancellationToken.None));

        Assert.Single(attempts);
        AssertAttempt(attempts[0], "primary-key", "gemini-2.5-flash");
        Assert.Equal(HttpStatusCode.BadRequest, ex.StatusCode);
    }

    [Fact]
    public async Task Logs_DoNotExposeRawApiKey()
    {
        var attempts = new List<string>();
        var logger = new TestLogger<GeminiService>();
        var service = CreateService(
            attempts,
            logger,
            attempt => attempt == 0
                ? new HttpResponseMessage(HttpStatusCode.TooManyRequests)
                {
                    Content = new StringContent("""{"error":{"message":"rate limit temporary"}}""")
                }
                : BuildSuccessResponse("完成"));

        _ = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.DoesNotContain(logger.Entries, entry => entry.Message.Contains("primary-key", StringComparison.Ordinal) || entry.Message.Contains("secondary-key", StringComparison.Ordinal));
        var warning = Assert.Single(logger.Entries, x => x.Message.Contains("trying next Gemini route", StringComparison.Ordinal));
        Assert.Equal("primary", warning.Properties["KeySlot"]);
        Assert.Equal("primary", warning.Properties["ModelSlot"]);
    }

    private static GeminiService CreateService(
        List<string> attempts,
        TestLogger<GeminiService> logger,
        Func<int, HttpResponseMessage> responder)
    {
        var handler = new RecordingHttpMessageHandler((request, ct) =>
        {
            attempts.Add(request.RequestUri!.ToString());
            return Task.FromResult(responder(attempts.Count - 1));
        });

        var config = TestFactory.BuildConfig(new Dictionary<string, string?>
        {
            ["Ai:Gemini:ApiKey"] = "primary-key",
            ["Ai:Gemini:SecondaryApiKey"] = "secondary-key",
            ["Ai:Gemini:Model"] = "gemini-2.5-flash",
            ["Ai:Gemini:FallbackModel"] = "gemini-2.0-flash-lite"
        });

        return new GeminiService(
            new HttpClient(handler),
            config,
            new ConversationHistoryService(),
            logger);
    }

    private static HttpResponseMessage BuildSuccessResponse(string text)
    {
        return new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent($@"{{""candidates"":[{{""content"":{{""parts"":[{{""text"":""{text}""}}]}}}}]}}")
        };
    }

    private static void AssertAttempt(string requestUri, string expectedKey, string expectedModel)
    {
        Assert.Contains($"key={expectedKey}", requestUri, StringComparison.Ordinal);
        Assert.Contains(expectedModel, requestUri, StringComparison.Ordinal);
    }
}
