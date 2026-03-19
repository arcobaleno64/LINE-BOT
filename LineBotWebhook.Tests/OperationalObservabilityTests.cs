using System.Net;
using LineBotWebhook.Controllers;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging.Abstractions;

namespace LineBotWebhook.Tests;

public class OperationalObservabilityTests
{
    [Fact]
    public async Task InvalidSignature_RecordsRequestAndInvalidSignatureMetrics()
    {
        var dispatcher = new FakeDispatcher();
        var metrics = new FakeWebhookMetrics();
        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysFalseSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            dispatcher: dispatcher,
            metrics: metrics,
            logger: NullLogger<LineWebhookController>.Instance)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext("{\"destination\":\"x\",\"events\":[]}", "bad")
            }
        };

        var result = await controller.Webhook(CancellationToken.None);

        Assert.IsType<UnauthorizedResult>(result);
        Assert.Equal(1, metrics.WebhookRequests);
        Assert.Equal(1, metrics.InvalidSignatures);
    }

    [Fact]
    public async Task Dispatcher_UnsupportedMessage_RecordsUnsupportedMetric()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var dispatcher = TestFactory.CreateDispatcher(config, handler, metrics, textHandled: false, imageHandled: false, fileHandled: false);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "sticker" }
        };

        await dispatcher.DispatchAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.Equal(1, metrics.MessageHandledByType["unsupported"]);
    }

    [Fact]
    public async Task TextCacheHit_RecordsMetric()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var ai = new FakeAiService
        {
            OnTextAsync = (msg, key, ct) => Task.FromResult("快取測試回覆")
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, metrics: metrics);

        _ = await TestFactory.InvokeMergedTextReplyAsync(textHandler, "u1:u1", "同一句測試", CancellationToken.None);
        _ = await TestFactory.InvokeMergedTextReplyAsync(textHandler, "u1:u1", "同一句測試", CancellationToken.None);

        Assert.Equal(1, metrics.CacheHits);
    }

    [Fact]
    public async Task TextMergeJoined_RecordsMetric()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var gate = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var firstCallStarted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var ai = new FakeAiService
        {
            OnTextAsync = async (msg, key, ct) =>
            {
                firstCallStarted.TrySetResult(true);
                return await gate.Task;
            }
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, metrics: metrics);

        var first = TestFactory.InvokeMergedTextReplyAsync(textHandler, "u1:u1", "merge test", CancellationToken.None);
        await firstCallStarted.Task;
        var second = TestFactory.InvokeMergedTextReplyAsync(textHandler, "u1:u1", "merge test", CancellationToken.None);

        gate.SetResult("合併成功");
        await Task.WhenAll(first, second);

        Assert.Equal(1, metrics.MergeJoined);
    }

    [Fact]
    public async Task Ai429NonQuota_Records429MetricButNotQuotaMetric()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var ai = new FakeAiService
        {
            OnTextAsync = (msg, key, ct) => throw new HttpRequestException("rate limit temporary", null, HttpStatusCode.TooManyRequests)
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, metrics: metrics, backoff: new Ai429BackoffService());

        await textHandler.HandleAsync(BuildTextEvent("user", "請幫我整理"), "https://unit.test", CancellationToken.None);

        Assert.Equal(1, metrics.AiTooManyRequests);
        Assert.Equal(0, metrics.AiQuotaExhausted);
    }

    [Fact]
    public void ReadinessSnapshot_ReportsCooldownWithoutFailingReadiness()
    {
        var readiness = new WebhookReadinessService(new Ai429BackoffService(), new ConversationHistoryService());
        readiness.MarkStarted();

        var before = readiness.GetSnapshot();
        Assert.True(before.IsReady);
        Assert.False(before.AiCooldownActive);
        Assert.True(before.CanAcceptAiTraffic);

        var backoff = new Ai429BackoffService();
        backoff.Trigger(30);
        readiness = new WebhookReadinessService(backoff, new ConversationHistoryService());
        readiness.MarkStarted();

        var after = readiness.GetSnapshot();
        Assert.True(after.IsReady);
        Assert.True(after.AiCooldownActive);
        Assert.False(after.CanAcceptAiTraffic);
        Assert.True(after.AiRetryAfterSeconds >= 1);
    }

    private static LineEvent BuildTextEvent(string sourceType, string text)
    {
        var source = new LineSource
        {
            Type = sourceType,
            UserId = "u1"
        };

        return new LineEvent
        {
            Type = "message",
            ReplyToken = "reply-token",
            Source = source,
            Message = new LineMessage
            {
                Id = "m1",
                Type = "text",
                Text = text
            }
        };
    }

    private sealed class AlwaysFalseSignatureVerifier : IWebhookSignatureVerifier
    {
        public bool Verify(string body, string signature) => false;
    }
}
