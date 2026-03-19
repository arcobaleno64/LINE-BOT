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
        var dispatcher = new FakeDispatcher();
        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysFalseSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            dispatcher: dispatcher,
            logger: NullLogger<LineWebhookController>.Instance)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext("{\"destination\":\"x\",\"events\":[]}", "bad")
            }
        };

        var result = await controller.Webhook(CancellationToken.None);

        Assert.IsType<UnauthorizedResult>(result);
        Assert.Equal(0, dispatcher.DispatchCalls);
    }

    [Fact]
    public async Task EmptyEvents_Returns200()
    {
        var dispatcher = new FakeDispatcher();
        var controller = new LineWebhookController(
            signatureVerifier: new AlwaysTrueSignatureVerifier(),
            publicBaseUrlResolver: new PublicBaseUrlResolver(TestFactory.BuildConfig()),
            dispatcher: dispatcher,
            logger: NullLogger<LineWebhookController>.Instance)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = TestFactory.CreateHttpContext("{\"destination\":\"x\",\"events\":[]}")
            }
        };

        var result = await controller.Webhook(CancellationToken.None);

        Assert.IsType<OkResult>(result);
        Assert.Equal(0, dispatcher.DispatchCalls);
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
