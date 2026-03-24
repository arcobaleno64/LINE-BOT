using System.Net;
using System.Text;
using LineBotWebhook.Controllers;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace LineBotWebhook.Tests;

public class OperationalObservabilityTests
{
    [Fact]
    public async Task InvalidSignature_RecordsRequestAndInvalidSignatureMetrics()
    {
        var queue = new FakeWebhookBackgroundQueue();
        var metrics = new FakeWebhookMetrics();
        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysFalseSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            backgroundQueue: queue,
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
    public async Task InvalidSignature_Log_IncludesHasSignatureHeader_AndBodyLength()
    {
        const string body = "{\"destination\":\"x\",\"events\":[]}";
        var queue = new FakeWebhookBackgroundQueue();
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<LineWebhookController>();
        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysFalseSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            backgroundQueue: queue,
            metrics: metrics,
            logger: logger)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext(body, "bad")
            }
        };

        _ = await controller.Webhook(CancellationToken.None);

        var warning = Assert.Single(logger.Entries, x => x.Level == LogLevel.Warning && x.Message.Contains("Invalid LINE signature", StringComparison.Ordinal));
        Assert.Equal(true, warning.Properties["HasSignatureHeader"]);
        Assert.Equal(Encoding.UTF8.GetByteCount(body), warning.Properties["BodyLength"]);
    }

    [Fact]
    public async Task WebhookReceipt_Log_IncludesEventCount_AndFirstEventId_WhenAvailable()
    {
        var queue = new FakeWebhookBackgroundQueue();
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<LineWebhookController>();
        var evt = BuildTextEvent("user", "hello");
        evt.WebhookEventId = "evt-first";
        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysTrueSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            backgroundQueue: queue,
            metrics: metrics,
            logger: logger)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext(TestFactory.BuildWebhookJson(evt))
            }
        };

        _ = await controller.Webhook(CancellationToken.None);

        var info = Assert.Single(logger.Entries, x => x.Level == LogLevel.Information && x.Message.Contains("Received LINE webhook with", StringComparison.Ordinal));
        Assert.Equal(1, info.Properties["EventCount"]);
        Assert.Equal("evt-first", info.Properties["FirstEventId"]);
    }

    [Fact]
    public async Task WebhookReceipt_Log_ForEmptyEvents_DoesNotIncludeSummaryFields()
    {
        var queue = new FakeWebhookBackgroundQueue();
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<LineWebhookController>();
        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysTrueSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            backgroundQueue: queue,
            metrics: metrics,
            logger: logger)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext("{\"destination\":\"x\",\"events\":[]}")
            }
        };

        _ = await controller.Webhook(CancellationToken.None);

        var info = Assert.Single(logger.Entries, x => x.Level == LogLevel.Information && x.Message.Contains("no events", StringComparison.Ordinal));
        Assert.False(info.Properties.ContainsKey("EventCount"));
        Assert.False(info.Properties.ContainsKey("FirstEventId"));
    }

    [Fact]
    public async Task WebhookReceipt_Log_OmitsFirstEventId_WhenFirstEventIdIsMissing()
    {
        var queue = new FakeWebhookBackgroundQueue();
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<LineWebhookController>();
        var evt = BuildTextEvent("user", "hello");
        evt.WebhookEventId = " ";
        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysTrueSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            backgroundQueue: queue,
            metrics: metrics,
            logger: logger)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext(TestFactory.BuildWebhookJson(evt))
            }
        };

        _ = await controller.Webhook(CancellationToken.None);

        var info = Assert.Single(logger.Entries, x => x.Level == LogLevel.Information && x.Message.Contains("Received LINE webhook with", StringComparison.Ordinal));
        Assert.Equal(1, info.Properties["EventCount"]);
        Assert.False(info.Properties.ContainsKey("FirstEventId"));
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
            OnTextAsync = (msg, key, ct, enableQuickReplies) => Task.FromResult("快取測試回覆")
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
            OnTextAsync = async (msg, key, ct, enableQuickReplies) =>
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
            OnTextAsync = (msg, key, ct, enableQuickReplies) => throw new HttpRequestException("rate limit temporary", null, HttpStatusCode.TooManyRequests)
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, metrics: metrics, backoff: new Ai429BackoffService());

        await textHandler.HandleAsync(BuildTextEvent("user", "請幫我整理"), "https://unit.test", CancellationToken.None);

        Assert.Equal(1, metrics.AiTooManyRequests);
        Assert.Equal(0, metrics.AiQuotaExhausted);
    }

    [Fact]
    public async Task ReplySuccess_RecordsMetric_AndStructuredLogContext()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<LineReplyService>();
        var httpHandler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var reply = TestFactory.CreateReplyService(config, httpHandler, metrics, logger);
        var logContext = new WebhookLogContext("evt-123", "text", "text", "user", "FINGERPRINT1");

        await reply.ReplyTextAsync("reply-token", "這是一段回覆", logContext, CancellationToken.None);

        Assert.Equal(1, metrics.RepliesSent);
        var successLog = Assert.Single(logger.Entries, x => x.Level == LogLevel.Information && x.Message.Contains("Sent LINE reply", StringComparison.Ordinal));
        Assert.Equal("evt-123", successLog.Properties["EventId"]);
        Assert.Equal("text", successLog.Properties["HandlerType"]);
        Assert.Equal("text", successLog.Properties["MessageType"]);
        Assert.Equal("user", successLog.Properties["SourceType"]);
        Assert.Equal(1, successLog.Properties["MessageCount"]);
    }

    [Fact]
    public async Task TextHandler_ReplyLog_IncludesEventCorrelationKey()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var replyLogger = new TestLogger<LineReplyService>();
        var ai = new FakeAiService
        {
            OnTextAsync = (msg, key, ct, enableQuickReplies) => Task.FromResult("AI 回覆")
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, metrics: metrics, replyLogger: replyLogger);
        var evt = BuildTextEvent("user", "請幫我整理");
        evt.WebhookEventId = "evt-correlation";

        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var successLog = Assert.Single(replyLogger.Entries, x => x.Level == LogLevel.Information && x.Message.Contains("Sent LINE reply", StringComparison.Ordinal));
        Assert.Equal("evt-correlation", successLog.Properties["EventId"]);
    }

    [Fact]
    public async Task ThrottleReject_Log_UsesFingerprintInsteadOfRawUserKey()
    {
        var config = TestFactory.BuildConfig(new Dictionary<string, string?> { ["App:UserThrottleSecondsText"] = "60" });
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<TextMessageHandler>();
        var ai = new FakeAiService();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var throttle = new UserRequestThrottleService();
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, metrics: metrics, throttle: throttle, logger: logger);
        var evt = BuildTextEvent("user", "你好");
        evt.WebhookEventId = "evt-throttle";

        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);
        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var log = Assert.Single(logger.Entries, x => x.Level == LogLevel.Information && x.Message.Contains("Throttle rejected request", StringComparison.Ordinal));
        Assert.Equal("evt-throttle", log.Properties["EventId"]);
        Assert.Equal("text", log.Properties["HandlerType"]);
        Assert.Equal("user", log.Properties["SourceType"]);
        Assert.Equal("text", log.Properties["MessageType"]);
        Assert.DoesNotContain("u1:u1", log.Message, StringComparison.Ordinal);
        Assert.Equal(ObservabilityKeyFingerprint.From("u1:u1"), log.Properties["UserKeyFingerprint"]);
    }

    [Fact]
    public async Task Ai429Warning_Log_UsesStandardizedFields_WithoutExceptionBody()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<TextMessageHandler>();
        var ai = new FakeAiService
        {
            OnTextAsync = (msg, key, ct, enableQuickReplies) => throw new HttpRequestException("rate limit temporary", null, HttpStatusCode.TooManyRequests)
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, metrics: metrics, backoff: new Ai429BackoffService(), logger: logger);
        var evt = BuildTextEvent("user", "請幫我整理");
        evt.WebhookEventId = "evt-429";

        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var warning = Assert.Single(logger.Entries, x => x.Level == LogLevel.Warning && x.Message.Contains("AI request hit 429", StringComparison.Ordinal));
        Assert.Null(warning.Exception);
        Assert.Equal("evt-429", warning.Properties["EventId"]);
        Assert.Equal("text", warning.Properties["HandlerType"]);
        Assert.Equal("user", warning.Properties["SourceType"]);
        Assert.Equal("text", warning.Properties["MessageType"]);
        Assert.Equal(false, warning.Properties["IsQuotaExhausted"]);
        Assert.Equal(ObservabilityKeyFingerprint.From("u1:u1"), warning.Properties["UserKeyFingerprint"]);
        Assert.DoesNotContain("rate limit temporary", warning.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task AiQuotaWarning_Log_UsesStandardizedFields_WithoutExceptionBody()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<TextMessageHandler>();
        var ai = new FakeAiService
        {
            OnTextAsync = (msg, key, ct, enableQuickReplies) => throw new HttpRequestException("quota exceeded rpd daily", null, HttpStatusCode.TooManyRequests)
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, metrics: metrics, logger: logger);
        var evt = BuildTextEvent("user", "你好");
        evt.WebhookEventId = "evt-quota";

        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var warning = Assert.Single(logger.Entries, x => x.Level == LogLevel.Warning && x.Message.Contains("AI request hit quota exhaustion", StringComparison.Ordinal));
        Assert.Null(warning.Exception);
        Assert.Equal("evt-quota", warning.Properties["EventId"]);
        Assert.Equal(true, warning.Properties["IsQuotaExhausted"]);
        Assert.DoesNotContain("quota exceeded rpd daily", warning.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void ReadinessSnapshot_ReportsCooldownWithoutFailingReadiness()
    {
        var queue = new FakeWebhookBackgroundQueue();
        var readiness = new WebhookReadinessService(new Ai429BackoffService(), new ConversationHistoryService(), queue);
        readiness.MarkStarted();

        var before = readiness.GetSnapshot();
        Assert.True(before.IsReady);
        Assert.False(before.AiCooldownActive);
        Assert.True(before.CanAcceptAiTraffic);
        Assert.Equal(0, before.QueueDepth);
        Assert.Equal(256, before.QueueCapacity);
        Assert.False(before.QueueSaturated);
        Assert.True(before.CanAcceptWebhookTraffic);

        var backoff = new Ai429BackoffService();
        backoff.Trigger(30);
        readiness = new WebhookReadinessService(backoff, new ConversationHistoryService(), queue);
        readiness.MarkStarted();

        var after = readiness.GetSnapshot();
        Assert.True(after.IsReady);
        Assert.True(after.AiCooldownActive);
        Assert.False(after.CanAcceptAiTraffic);
        Assert.True(after.AiRetryAfterSeconds >= 1);
    }

    [Fact]
    public void ReadinessSnapshot_ReportsQueuePressure_AndMarksNotReadyWhenSaturated()
    {
        var queue = new FakeWebhookBackgroundQueue
        {
            Snapshot = new WebhookQueueSnapshot(256, 256, 256, 3, 0)
        };
        var readiness = new WebhookReadinessService(new Ai429BackoffService(), new ConversationHistoryService(), queue);
        readiness.MarkStarted();

        var snapshot = readiness.GetSnapshot();

        Assert.False(snapshot.IsReady);
        Assert.Equal("backpressure", snapshot.Status);
        Assert.Equal(256, snapshot.QueueDepth);
        Assert.Equal(256, snapshot.QueueCapacity);
        Assert.True(snapshot.QueueSaturated);
        Assert.False(snapshot.CanAcceptWebhookTraffic);
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

    private sealed class AlwaysTrueSignatureVerifier : IWebhookSignatureVerifier
    {
        public bool Verify(string body, string signature) => true;
    }
}
