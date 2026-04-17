using System.Net;
using System.Text;
using System.Text.Json;
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
            deduplication: new WebhookEventDeduplicationService(),
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
            deduplication: new WebhookEventDeduplicationService(),
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
        Assert.DoesNotContain(body, warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("bad", warning.Message, StringComparison.Ordinal);
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
            deduplication: new WebhookEventDeduplicationService(),
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
            deduplication: new WebhookEventDeduplicationService(),
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
            deduplication: new WebhookEventDeduplicationService(),
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
    public async Task Webhook_WhenQueueDropsEvents_StillReturns200_AndLogsDroppedSummary()
    {
        var queue = new FakeWebhookBackgroundQueue { TryEnqueueResult = false };
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<LineWebhookController>();
        var firstEvent = BuildTextEvent("user", "raw-user-text");
        firstEvent.WebhookEventId = "evt-first";
        var secondEvent = BuildTextEvent("user", "second-text");
        secondEvent.WebhookEventId = "evt-second";
        var body = JsonSerializer.Serialize(new LineWebhookBody
        {
            Destination = "dest",
            Events = [firstEvent, secondEvent]
        });

        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysTrueSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            backgroundQueue: queue,
            metrics: metrics,
            deduplication: new WebhookEventDeduplicationService(),
            logger: logger)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext(body, "sig")
            }
        };

        var result = await controller.Webhook(CancellationToken.None);

        Assert.IsType<OkResult>(result);
        var warning = Assert.Single(
            logger.Entries,
            x => x.Level == LogLevel.Warning && x.Message.Contains("Webhook enqueue dropped events", StringComparison.Ordinal));
        Assert.Equal(2, warning.Properties["EventCount"]);
        Assert.Equal(2, warning.Properties["DroppedCount"]);
        Assert.Equal("evt-first", warning.Properties["FirstEventId"]);
        Assert.DoesNotContain(body, warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("sig", warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("reply-token", warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("raw-user-text", warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("u1", warning.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Webhook_WhenAllEventsEnqueued_DoesNotLogDroppedSummary()
    {
        var queue = new FakeWebhookBackgroundQueue { TryEnqueueResult = true };
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<LineWebhookController>();
        var evt = BuildTextEvent("user", "hello");
        evt.WebhookEventId = "evt-ok";
        var body = TestFactory.BuildWebhookJson(evt);

        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysTrueSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            backgroundQueue: queue,
            metrics: metrics,
            deduplication: new WebhookEventDeduplicationService(),
            logger: logger)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext(body)
            }
        };

        var result = await controller.Webhook(CancellationToken.None);

        Assert.IsType<OkResult>(result);
        Assert.DoesNotContain(
            logger.Entries,
            x => x.Level == LogLevel.Warning && x.Message.Contains("Webhook enqueue dropped events", StringComparison.Ordinal));
    }

    [Fact]
    public async Task Webhook_WhenQueuePartiallyDropsEvents_StillReturns200_AndLogsAccurateDropSummary()
    {
        const string signature = "sig-partial";
        var queue = new PartialAcceptWebhookQueue(successCountLimit: 1);
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<LineWebhookController>();

        var firstEvent = BuildTextEvent("user", "raw-user-text-1");
        firstEvent.WebhookEventId = "evt-first";
        firstEvent.ReplyToken = "raw-reply-token-1";
        firstEvent.Source!.UserId = "u-stable-id-1";

        var secondEvent = BuildTextEvent("user", "raw-user-text-2");
        secondEvent.WebhookEventId = "evt-second";
        secondEvent.ReplyToken = "raw-reply-token-2";
        secondEvent.Source!.UserId = "u-stable-id-2";

        var thirdEvent = BuildTextEvent("user", "raw-user-text-3");
        thirdEvent.WebhookEventId = "evt-third";
        thirdEvent.ReplyToken = "raw-reply-token-3";
        thirdEvent.Source!.UserId = "u-stable-id-3";

        var body = JsonSerializer.Serialize(new LineWebhookBody
        {
            Destination = "dest",
            Events = [firstEvent, secondEvent, thirdEvent]
        });

        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysTrueSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            backgroundQueue: queue,
            metrics: metrics,
            deduplication: new WebhookEventDeduplicationService(),
            logger: logger)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext(body, signature)
            }
        };

        var result = await controller.Webhook(CancellationToken.None);

        Assert.IsType<OkResult>(result);
        var warning = Assert.Single(
            logger.Entries,
            x => x.Level == LogLevel.Warning && x.Message.Contains("Webhook enqueue dropped events", StringComparison.Ordinal));

        Assert.Equal(3, warning.Properties["EventCount"]);
        Assert.Equal(1, warning.Properties["EnqueuedCount"]);
        Assert.Equal(2, warning.Properties["DroppedCount"]);
        Assert.Equal("evt-first", warning.Properties["FirstEventId"]);

        Assert.DoesNotContain(body, warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain(signature, warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("raw-reply-token", warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("raw-user-text", warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("u-stable-id", warning.Message, StringComparison.Ordinal);
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
    public async Task TextRateLimitDebug_Log_DoesNotLeakRawUserTextOrStableIds()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<TextMessageHandler>();
        var ai = new FakeAiService
        {
            OnTextAsync = (msg, key, ct, enableQuickReplies) =>
                throw new HttpRequestException("rate limit temporary raw-user-text=u1:u1 token-like-abc", null, HttpStatusCode.TooManyRequests)
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, metrics: metrics, logger: logger);
        var evt = BuildTextEvent("user", "raw-user-text");
        evt.WebhookEventId = "evt-debug-text";

        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var debug = Assert.Single(logger.Entries, x => x.Level == LogLevel.Debug && x.Message.Contains("AI rate limit details", StringComparison.Ordinal));
        Assert.Null(debug.Exception);
        Assert.Equal("evt-debug-text", debug.Properties["EventId"]);
        Assert.Equal(429, debug.Properties["StatusCode"]);
        Assert.Equal(false, debug.Properties["IsQuotaExhausted"]);
        Assert.Equal(ObservabilityKeyFingerprint.From("u1:u1"), debug.Properties["UserKeyFingerprint"]);
        Assert.DoesNotContain("raw-user-text", debug.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("u1:u1", debug.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("token-like-abc", debug.Message, StringComparison.Ordinal);
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
    public async Task ImageRateLimitDebug_Log_DoesNotLeakStableIds()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<ImageMessageHandler>();
        var ai = new FakeAiService
        {
            OnImageAsync = (bytes, mime, prompt, key, ct) =>
                throw new HttpRequestException("rate limit image raw-user=u1:u1", null, HttpStatusCode.TooManyRequests)
        };
        var handler = new RecordingHttpMessageHandler((request, ct) =>
        {
            if (request.RequestUri!.ToString().Contains("api-data.line.me", StringComparison.Ordinal))
            {
                var response = new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new ByteArrayContent([1, 2, 3])
                };
                response.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("image/png");
                return Task.FromResult(response);
            }

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK));
        });
        var imageHandler = TestFactory.CreateImageHandler(config, ai, handler, metrics: metrics, logger: logger);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            WebhookEventId = "evt-debug-image",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "image" }
        };

        await imageHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var debug = Assert.Single(logger.Entries, x => x.Level == LogLevel.Debug && x.Message.Contains("AI rate limit details", StringComparison.Ordinal));
        Assert.Null(debug.Exception);
        Assert.Equal("evt-debug-image", debug.Properties["EventId"]);
        Assert.Equal(429, debug.Properties["StatusCode"]);
        Assert.Equal(ObservabilityKeyFingerprint.From("u1:u1"), debug.Properties["UserKeyFingerprint"]);
        Assert.DoesNotContain("u1:u1", debug.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task FileRateLimitDebug_Log_DoesNotLeakExtractedTextOrTokenLikeValues()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var logger = new TestLogger<FileMessageHandler>();
        var ai = new FakeAiService
        {
            OnTextAsync = (message, key, ct, enableQuickReplies) =>
                throw new HttpRequestException("rate limit file-token-123 extracted-secret-body", null, HttpStatusCode.TooManyRequests)
        };
        var handler = new RecordingHttpMessageHandler((request, ct) =>
        {
            if (request.RequestUri!.ToString().Contains("api-data.line.me", StringComparison.Ordinal))
            {
                var response = new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new ByteArrayContent(Encoding.UTF8.GetBytes("extracted-secret-body"))
                };
                response.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("text/plain");
                return Task.FromResult(response);
            }

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK));
        });
        var fileHandler = TestFactory.CreateFileHandler(config, ai, handler, metrics: metrics, logger: logger);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            WebhookEventId = "evt-debug-file",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "file", FileName = "a.txt" }
        };

        await fileHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var debug = Assert.Single(logger.Entries, x => x.Level == LogLevel.Debug && x.Message.Contains("AI rate limit details", StringComparison.Ordinal));
        Assert.Null(debug.Exception);
        Assert.Equal("evt-debug-file", debug.Properties["EventId"]);
        Assert.Equal(429, debug.Properties["StatusCode"]);
        Assert.Equal(ObservabilityKeyFingerprint.From("u1:u1"), debug.Properties["UserKeyFingerprint"]);
        Assert.DoesNotContain("extracted-secret-body", debug.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("file-token-123", debug.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task DocumentSemanticFallbackWarning_DoesNotLeakPromptOrChunkText()
    {
        var logger = new TestLogger<DocumentGroundingService>();
        var semantic = new FakeSemanticChunkSelector
        {
            OnSelectAsync = (chunks, prompt, ct) =>
                throw new HttpRequestException($"semantic failure prompt={prompt} raw-chunk={chunks[0].Text} token-like-xyz", null, HttpStatusCode.BadRequest)
        };
        var service = new DocumentGroundingService(
            new DocumentChunker(),
            new DocumentChunkSelector(),
            semantic,
            logger);

        var longText = string.Join("\n\n", Enumerable.Repeat("第一段敏感片段 " + new string('A', 400), 6));
        var result = await service.PrepareAsync("a.txt", "text/plain", longText, "截止日是什麼？");

        Assert.NotEmpty(result.SelectedChunks);
        var warning = Assert.Single(logger.Entries, x => x.Level == LogLevel.Warning && x.Message.Contains("Document semantic selection failed", StringComparison.Ordinal));
        Assert.Null(warning.Exception);
        Assert.Equal("document", warning.Properties["RequestType"]);
        Assert.Equal(DocumentTaskMode.QuestionAnswer, warning.Properties["Mode"]);
        Assert.Equal(true, warning.Properties["HasSemanticSelector"]);
        Assert.Equal(true, warning.Properties["HasFallback"]);
        Assert.Equal(400, warning.Properties["StatusCode"]);
        Assert.Equal("HttpRequestException", warning.Properties["ExceptionType"]);
        Assert.DoesNotContain("截止日是什麼", warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("第一段敏感片段", warning.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("token-like-xyz", warning.Message, StringComparison.Ordinal);
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

    private sealed class PartialAcceptWebhookQueue : IWebhookBackgroundQueue
    {
        private readonly int _successCountLimit;
        private int _attempts;
        private int _enqueued;
        private int _dropped;

        public PartialAcceptWebhookQueue(int successCountLimit)
        {
            _successCountLimit = successCountLimit;
        }

        public bool TryEnqueue(WebhookQueueItem item)
        {
            _attempts++;
            if (_attempts <= _successCountLimit)
            {
                _enqueued++;
                return true;
            }

            _dropped++;
            return false;
        }

        public async IAsyncEnumerable<WebhookQueueItem> DequeueAllAsync([System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
        {
            await Task.CompletedTask;
            yield break;
        }

        public WebhookQueueSnapshot GetSnapshot()
            => new(0, 256, _enqueued, _dropped, 0);

        public void Complete()
        {
        }
    }
}
