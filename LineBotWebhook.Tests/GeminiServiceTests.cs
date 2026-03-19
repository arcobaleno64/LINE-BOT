using System.Net;
using LineBotWebhook.Services;

namespace LineBotWebhook.Tests;

public class GeminiServiceTests
{
    [Fact]
    public async Task SecondaryApiKey_IsUsed_WhenPrimaryHitsRateLimit()
    {
        var attempts = new List<string>();
        var handler = new RecordingHttpMessageHandler(async (request, ct) =>
        {
            attempts.Add(request.RequestUri!.Query);

            if (attempts.Count == 1)
                return new HttpResponseMessage(HttpStatusCode.TooManyRequests);

            var response = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent("""
                {"candidates":[{"content":{"parts":[{"text":"第二把 key 成功"}]}}]}
                """)
            };
            return await Task.FromResult(response);
        });

        var config = TestFactory.BuildConfig(new Dictionary<string, string?>
        {
            ["Ai:Gemini:ApiKey"] = "primary-key",
            ["Ai:Gemini:SecondaryApiKey"] = "secondary-key",
            ["Ai:Gemini:Model"] = "gemini-2.5-flash",
            ["Ai:Gemini:FallbackModel"] = "gemini-2.0-flash-lite"
        });

        var service = new GeminiService(
            new HttpClient(handler),
            config,
            new ConversationHistoryService());

        var reply = await service.GetReplyAsync("你好", "u1", CancellationToken.None);

        Assert.Equal("第二把 key 成功", reply);
        Assert.Equal(2, attempts.Count);
        Assert.Contains("key=primary-key", attempts[0], StringComparison.Ordinal);
        Assert.Contains("key=secondary-key", attempts[1], StringComparison.Ordinal);
    }
}
