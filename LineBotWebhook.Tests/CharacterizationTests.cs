using System.Net;
using LineBotWebhook.Controllers;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging.Abstractions;

namespace LineBotWebhook.Tests;

public class CharacterizationTests
{
    [Fact]
    public async Task InvalidSignature_Returns401()
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
        Assert.Empty(queue.Items);
    }

    [Fact]
    public async Task EmptyEvents_Returns200()
    {
        var queue = new FakeWebhookBackgroundQueue();
        var metrics = new FakeWebhookMetrics();
        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysTrueSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            backgroundQueue: queue,
            metrics: metrics,
            logger: NullLogger<LineWebhookController>.Instance)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext("{\"destination\":\"x\",\"events\":[]}")
            }
        };

        var result = await controller.Webhook(CancellationToken.None);

        Assert.IsType<OkResult>(result);
        Assert.Empty(queue.Items);
    }

    [Fact]
    public async Task Webhook_ValidBody_Returns200_AndEnqueuesEvent()
    {
        var queue = new FakeWebhookBackgroundQueue();
        var metrics = new FakeWebhookMetrics();
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "text", Text = "hello" }
        };

        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysTrueSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            backgroundQueue: queue,
            metrics: metrics,
            logger: NullLogger<LineWebhookController>.Instance)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext(TestFactory.BuildWebhookJson(evt))
            }
        };

        var result = await controller.Webhook(CancellationToken.None);

        Assert.IsType<OkResult>(result);
        var queued = Assert.Single(queue.Items);
        Assert.Equal(evt.WebhookEventId, queued.Event.WebhookEventId);
        Assert.Equal(evt.Message!.Type, queued.Event.Message!.Type);
        Assert.Equal(evt.Message.Text, queued.Event.Message.Text);
        Assert.Equal("https://unit.test", queued.PublicBaseUrl);
    }

    [Theory]
    [InlineData("現在：幾點", "現在時間：")]
    [InlineData("今天：（幾號）", "今天日期：")]
    [InlineData("今天;星期幾", "今天：星期")]
    public void DateTimeIntentResponder_Parity_ValidatesSemanticOutput(string input, string expectedKeyPhrase)
    {
        var responder = new DateTimeIntentResponder(TestFactory.BuildConfig());

        var hit = responder.TryBuildReply(input, out var reply);

        Assert.True(hit, $"Should recognize intent in '{input}'");
        Assert.NotNull(reply);
        Assert.Contains(expectedKeyPhrase, reply, StringComparison.Ordinal);
    }

    [Fact]
    public async Task GroupTextWithoutMention_IsIgnored()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler);

        var evt = BuildTextEvent("group", "大家好", mentioned: false);
        var handled = await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.True(handled);
        Assert.Equal(0, ai.TextCalls);
        Assert.Empty(handler.Requests);
    }

    [Fact]
    public async Task GroupTextWithMention_IsHandled()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler);

        var evt = BuildTextEvent("group", "@bot 哈囉", mentioned: true);
        var handled = await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.True(handled);
        Assert.Equal(1, ai.TextCalls);
        Assert.NotNull(TestFactory.GetLastReplyText(handler));
    }

    [Fact]
    public async Task DateTimeShortcut_DoesNotCallAi()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler);

        var evt = BuildTextEvent("user", "現在幾點");
        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var replyText = TestFactory.GetLastReplyText(handler);
        Assert.NotNull(replyText);
        Assert.Contains("現在時間", replyText!);
        Assert.Equal(0, ai.TextCalls);
    }

    [Fact]
    public async Task ThrottleReject_ReturnsThrottleMessage()
    {
        var config = TestFactory.BuildConfig(new Dictionary<string, string?> { ["App:UserThrottleSecondsText"] = "60" });
        var ai = new FakeAiService();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var throttle = new UserRequestThrottleService();
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, throttle: throttle);

        var evt = BuildTextEvent("user", "你好");
        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);
        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var replyText = TestFactory.GetLastReplyText(handler);
        Assert.NotNull(replyText);
        Assert.Contains("訊息有點密集", replyText!);
    }

    [Fact]
    public async Task ImageInUserChat_IsHandled()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var handler = new RecordingHttpMessageHandler((request, ct) =>
        {
            if (request.RequestUri!.ToString().Contains("api-data.line.me"))
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

        var imageHandler = TestFactory.CreateImageHandler(config, ai, handler);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "image" }
        };

        var handled = await imageHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.True(handled);
        Assert.Equal(1, ai.ImageCalls);
        Assert.NotNull(TestFactory.GetLastReplyText(handler));
    }

    [Fact]
    public async Task ImageInGroup_IsIgnored()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var imageHandler = TestFactory.CreateImageHandler(config, ai, handler);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "group", GroupId = "g1", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "image" }
        };

        var handled = await imageHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.True(handled);
        Assert.Equal(0, ai.ImageCalls);
        Assert.Empty(handler.Requests);
    }

    [Fact]
    public async Task FileUnsupported_ReturnsUnsupportedMessage()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var handler = new RecordingHttpMessageHandler((request, ct) =>
        {
            if (request.RequestUri!.ToString().Contains("api-data.line.me"))
            {
                var response = new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new ByteArrayContent([0x00, 0x01])
                };
                response.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/octet-stream");
                return Task.FromResult(response);
            }

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK));
        });

        var fileHandler = TestFactory.CreateFileHandler(config, ai, handler);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "file", FileName = "a.bin" }
        };

        await fileHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var replyText = TestFactory.GetLastReplyText(handler);
        Assert.NotNull(replyText);
        Assert.Contains("目前僅支援文字型檔案", replyText!);
    }

    [Fact]
    public async Task FileScannedPdf_ReturnsExistingPdfMessage()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var handler = new RecordingHttpMessageHandler((request, ct) =>
        {
            if (request.RequestUri!.ToString().Contains("api-data.line.me"))
            {
                var response = new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new ByteArrayContent(System.Text.Encoding.UTF8.GetBytes("%PDF-1.4"))
                };
                response.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/pdf");
                return Task.FromResult(response);
            }

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK));
        });

        var fileHandler = TestFactory.CreateFileHandler(config, ai, handler);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "file", FileName = "scan.pdf" }
        };

        await fileHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var replyText = TestFactory.GetLastReplyText(handler);
        Assert.NotNull(replyText);
        Assert.Contains("掃描型或圖片型 PDF", replyText!, StringComparison.Ordinal);
    }

    [Fact]
    public async Task FileSupported_IncludesDownloadUrl()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService
        {
            OnFileAsync = (name, mime, text, prompt, userKey, ct) => Task.FromResult("整理完成")
        };
        var handler = new RecordingHttpMessageHandler((request, ct) =>
        {
            if (request.RequestUri!.ToString().Contains("api-data.line.me"))
            {
                var response = new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new ByteArrayContent(System.Text.Encoding.UTF8.GetBytes("hello"))
                };
                response.Content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("text/plain");
                return Task.FromResult(response);
            }

            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK));
        });

        var fileHandler = TestFactory.CreateFileHandler(config, ai, handler);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "file", FileName = "a.txt" }
        };

        await fileHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var replyText = TestFactory.GetLastReplyText(handler);
        Assert.NotNull(replyText);
        Assert.Contains("下載整理檔", replyText!);
        Assert.Contains("https://unit.test/downloads/", replyText!);
    }

    [Fact]
    public async Task Ai429QuotaExhausted_ReturnsQuotaMessage()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService
        {
            OnTextAsync = (msg, key, ct) => throw new HttpRequestException("quota exceeded rpd daily", null, HttpStatusCode.TooManyRequests)
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler);

        var evt = BuildTextEvent("user", "你好");
        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var replyText = TestFactory.GetLastReplyText(handler);
        Assert.NotNull(replyText);
        Assert.Contains("今日 AI 配額已達上限", replyText!);
    }

    [Fact]
    public async Task Ai429NonQuota_ReturnsBusyMessage_AndCooldownApplied()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService
        {
            OnTextAsync = (msg, key, ct) => throw new HttpRequestException("rate limit temporary", null, HttpStatusCode.TooManyRequests)
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var backoff = new Ai429BackoffService();
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler, backoff: backoff);

        var evt = BuildTextEvent("user", "請幫我整理");
        await textHandler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        var replyText = TestFactory.GetLastReplyText(handler);
        Assert.NotNull(replyText);
        Assert.Contains("目前流量較高，稍後再試。", replyText!);

        var pass = backoff.TryPass(out var retryAfterSeconds);
        Assert.False(pass);
        Assert.True(retryAfterSeconds >= 1);
    }

    [Fact]
    public async Task TextCacheHit_SecondCall_DoesNotCallAiAgain()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService
        {
            OnTextAsync = (msg, key, ct) => Task.FromResult("快取測試回覆")
        };
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler);

        var first = await TestFactory.InvokeMergedTextReplyAsync(textHandler, "u1:u1", "同一句測試", CancellationToken.None);
        var second = await TestFactory.InvokeMergedTextReplyAsync(textHandler, "u1:u1", "同一句測試", CancellationToken.None);

        Assert.Equal("快取測試回覆", first);
        Assert.Equal("快取測試回覆", second);
        Assert.Equal(1, ai.TextCalls);
    }

    [Fact]
    public async Task TextMergeJoined_SameWindow_UsesSingleInFlightAiCall()
    {
        var config = TestFactory.BuildConfig();
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
        var textHandler = TestFactory.CreateTextHandler(config, ai, handler);

        var t1 = TestFactory.InvokeMergedTextReplyAsync(textHandler, "u1:u1", "merge test", CancellationToken.None);
        await firstCallStarted.Task;
        var t2 = TestFactory.InvokeMergedTextReplyAsync(textHandler, "u1:u1", "merge test", CancellationToken.None);

        Assert.Equal(1, ai.TextCalls);

        gate.SetResult("合併成功");
        var r1 = await t1;
        var r2 = await t2;

        Assert.Equal("合併成功", r1);
        Assert.Equal("合併成功", r2);
        Assert.Equal(1, ai.TextCalls);
    }

    [Fact]
    public async Task Dispatcher_UnsupportedMessage_UserSource_RepliesFallback()
    {
        var config = TestFactory.BuildConfig();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var dispatcher = TestFactory.CreateDispatcher(config, handler, metrics: new FakeWebhookMetrics(), textHandled: false, imageHandled: false, fileHandled: false);

        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "user", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "sticker" }
        };

        await dispatcher.DispatchAsync(evt, "https://unit.test", CancellationToken.None);

        var replyText = TestFactory.GetLastReplyText(handler);
        Assert.Equal("目前我支援文字、圖片與檔案（txt/md/csv/json/xml/log/pdf）。PDF 目前先支援文字型 PDF。", replyText);
    }

    [Fact]
    public async Task Dispatcher_UnsupportedMessage_GroupSource_NoFallbackReply()
    {
        var config = TestFactory.BuildConfig();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var dispatcher = TestFactory.CreateDispatcher(config, handler, metrics: new FakeWebhookMetrics(), textHandled: false, imageHandled: false, fileHandled: false);

        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "group", GroupId = "g1", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "sticker" }
        };

        await dispatcher.DispatchAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.Empty(handler.Requests);
    }

    private static LineEvent BuildTextEvent(string sourceType, string text, bool mentioned = false)
    {
        var message = new LineMessage
        {
            Id = "m1",
            Type = "text",
            Text = text
        };

        if (mentioned)
        {
            message.Mention = new LineMention
            {
                Mentionees = [new LineMentionee { Index = 0, Length = 4, IsSelf = true, Type = "user" }]
            };
        }

        var source = new LineSource
        {
            Type = sourceType,
            UserId = "u1",
            GroupId = sourceType == "group" ? "g1" : null,
            RoomId = sourceType == "room" ? "r1" : null
        };

        return new LineEvent
        {
            Type = "message",
            ReplyToken = "reply-token",
            Source = source,
            Message = message
        };
    }

    private sealed class AlwaysTrueSignatureVerifier : IWebhookSignatureVerifier
    {
        public bool Verify(string body, string signature) => true;
    }

    private sealed class AlwaysFalseSignatureVerifier : IWebhookSignatureVerifier
    {
        public bool Verify(string body, string signature) => false;
    }
}
