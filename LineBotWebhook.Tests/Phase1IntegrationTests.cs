using System.Net;
using System.Text.Json;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;

namespace LineBotWebhook.Tests;

public class Phase1IntegrationTests
{
    // ── Loading Indicator ──

    [Fact]
    public void ResolveChatId_User_ReturnsUserId()
    {
        var evt = new LineEvent
        {
            Source = new LineSource { Type = "user", UserId = "U123" }
        };

        Assert.Equal("U123", LoadingIndicatorService.ResolveChatId(evt));
    }

    [Fact]
    public void ResolveChatId_Group_ReturnsGroupId()
    {
        var evt = new LineEvent
        {
            Source = new LineSource { Type = "group", GroupId = "G456", UserId = "U123" }
        };

        Assert.Equal("G456", LoadingIndicatorService.ResolveChatId(evt));
    }

    [Fact]
    public void ResolveChatId_Room_ReturnsRoomId()
    {
        var evt = new LineEvent
        {
            Source = new LineSource { Type = "room", RoomId = "R789", UserId = "U123" }
        };

        Assert.Equal("R789", LoadingIndicatorService.ResolveChatId(evt));
    }

    [Fact]
    public void ResolveChatId_NoSource_ReturnsNull()
    {
        var evt = new LineEvent();

        Assert.Null(LoadingIndicatorService.ResolveChatId(evt));
    }

    [Fact]
    public async Task LoadingIndicator_SendsCorrectRequest()
    {
        var handler = new RecordingHttpMessageHandler((req, ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var config = TestFactory.BuildConfig();
        var svc = new LoadingIndicatorService(new HttpClient(handler), config, NullLogger<LoadingIndicatorService>.Instance);

        var evt = new LineEvent
        {
            Source = new LineSource { Type = "user", UserId = "U123" }
        };

        await svc.ShowAsync(evt);

        Assert.Single(handler.Requests);
        var req = handler.Requests[0];
        Assert.Equal("https://api.line.me/v2/bot/chat/loading/start", req.RequestUri!.ToString());
        Assert.Equal(HttpMethod.Post, req.Method);

        var body = await req.Content!.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(body);
        Assert.Equal("U123", doc.RootElement.GetProperty("chatId").GetString());
        Assert.Equal(20, doc.RootElement.GetProperty("loadingSeconds").GetInt32());
    }

    [Fact]
    public async Task LoadingIndicator_FailureDoesNotThrow()
    {
        var handler = new RecordingHttpMessageHandler((req, ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.InternalServerError)));
        var config = TestFactory.BuildConfig();
        var svc = new LoadingIndicatorService(new HttpClient(handler), config, NullLogger<LoadingIndicatorService>.Instance);

        var evt = new LineEvent
        {
            Source = new LineSource { Type = "user", UserId = "U123" }
        };

        await svc.ShowAsync(evt); // should not throw
    }

    [Fact]
    public async Task LoadingIndicator_NoSource_NoRequest()
    {
        var handler = new RecordingHttpMessageHandler((req, ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var config = TestFactory.BuildConfig();
        var svc = new LoadingIndicatorService(new HttpClient(handler), config, NullLogger<LoadingIndicatorService>.Instance);

        var evt = new LineEvent();

        await svc.ShowAsync(evt);

        Assert.Empty(handler.Requests);
    }

    // ── Dispatcher Loading Indicator Integration ──

    [Fact]
    public async Task Dispatcher_TextMessage_TriggersLoading()
    {
        var config = TestFactory.BuildConfig();
        var handler = new RecordingHttpMessageHandler((req, ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var dispatcher = TestFactory.CreateDispatcher(config, handler, metrics: null, textHandled: true, imageHandled: false, fileHandled: false);

        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "user", UserId = "U1" },
            Message = new LineMessage { Id = "m1", Type = "text", Text = "hello" }
        };

        await dispatcher.DispatchAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.Contains(handler.Requests, r => r.RequestUri!.ToString().Contains("loading/start"));
    }

    [Fact]
    public async Task Dispatcher_StickerMessage_NoLoading()
    {
        var config = TestFactory.BuildConfig();
        var handler = new RecordingHttpMessageHandler((req, ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var dispatcher = TestFactory.CreateDispatcher(config, handler, metrics: null, textHandled: false, imageHandled: false, fileHandled: false);

        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "r1",
            Source = new LineSource { Type = "group", GroupId = "g1", UserId = "u1" },
            Message = new LineMessage { Id = "m1", Type = "sticker" }
        };

        await dispatcher.DispatchAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.DoesNotContain(handler.Requests, r => r.RequestUri!.ToString().Contains("loading/start"));
    }

    // ── Postback Handling ──

    [Fact]
    public async Task Dispatcher_PostbackEvent_Dispatches()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var handler = new RecordingHttpMessageHandler((req, ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var dispatcher = TestFactory.CreateDispatcher(config, handler, metrics: metrics, textHandled: false, imageHandled: false, fileHandled: false);

        var evt = new LineEvent
        {
            Type = "postback",
            ReplyToken = "r1",
            WebhookEventId = "ev1",
            Source = new LineSource { Type = "user", UserId = "U1" },
            Postback = new LinePostback { Data = "action=test&key=value" }
        };

        await dispatcher.DispatchAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.True(metrics.MessageHandledByType.ContainsKey("postback"));
    }

    [Fact]
    public async Task Dispatcher_PostbackEvent_NoReplyToken_Ignored()
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var handler = new RecordingHttpMessageHandler((req, ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var dispatcher = TestFactory.CreateDispatcher(config, handler, metrics: metrics, textHandled: false, imageHandled: false, fileHandled: false);

        var evt = new LineEvent
        {
            Type = "postback",
            WebhookEventId = "ev1",
            Source = new LineSource { Type = "user", UserId = "U1" },
            Postback = new LinePostback { Data = "action=test" }
        };

        await dispatcher.DispatchAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.False(metrics.MessageHandledByType.ContainsKey("postback"));
    }

    [Fact]
    public void ParsePostbackData_Standard()
    {
        var result = LineWebhookDispatcher.ParsePostbackData("action=test&key=value");
        Assert.Equal("test", result["action"]);
        Assert.Equal("value", result["key"]);
    }

    [Fact]
    public void ParsePostbackData_Empty()
    {
        var result = LineWebhookDispatcher.ParsePostbackData("");
        Assert.Empty(result);
    }

    [Fact]
    public void ParsePostbackData_EncodedValues()
    {
        var result = LineWebhookDispatcher.ParsePostbackData("action=hello%20world&key=%E6%B8%AC%E8%A9%A6");
        Assert.Equal("hello world", result["action"]);
        Assert.Equal("測試", result["key"]);
    }

    // ── Flex Message ──

    [Fact]
    public async Task ReplyFlex_SendsCorrectPayload()
    {
        var handler = new RecordingHttpMessageHandler((req, ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var config = TestFactory.BuildConfig();
        var reply = TestFactory.CreateReplyService(config, handler);

        var flexContents = new
        {
            type = "bubble",
            body = new
            {
                type = "box",
                layout = "vertical",
                contents = new[]
                {
                    new { type = "text", text = "Hello Flex" }
                }
            }
        };

        await reply.ReplyFlexAsync("token1", "測試 Flex", flexContents, logContext: null);

        Assert.Single(handler.Requests);
        var body = await handler.Requests[0].Content!.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(body);
        var messages = doc.RootElement.GetProperty("messages");
        Assert.Equal(1, messages.GetArrayLength());
        Assert.Equal("flex", messages[0].GetProperty("type").GetString());
        Assert.Equal("測試 Flex", messages[0].GetProperty("altText").GetString());
        Assert.Equal("bubble", messages[0].GetProperty("contents").GetProperty("type").GetString());
    }

    [Fact]
    public async Task ReplyFlex_WithQuickReplies_IncludesItems()
    {
        var handler = new RecordingHttpMessageHandler((req, ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var config = TestFactory.BuildConfig();
        var reply = TestFactory.CreateReplyService(config, handler);

        var flexContents = new { type = "bubble", body = new { type = "box", layout = "vertical", contents = Array.Empty<object>() } };

        await reply.ReplyFlexAsync("token1", "alt", flexContents, quickReplies: new[] { "選項A", "選項B" }, logContext: null);

        var body = await handler.Requests[0].Content!.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(body);
        var msg = doc.RootElement.GetProperty("messages")[0];
        Assert.True(msg.TryGetProperty("quickReply", out var qr));
        Assert.Equal(2, qr.GetProperty("items").GetArrayLength());
    }

    // ── Model Deserialization ──

    [Fact]
    public void PostbackEvent_Deserializes()
    {
        var json = """
        {
            "type": "postback",
            "replyToken": "rtoken",
            "webhookEventId": "ev1",
            "timestamp": 1234567890,
            "source": { "type": "user", "userId": "U1" },
            "postback": { "data": "action=test" }
        }
        """;

        var evt = JsonSerializer.Deserialize<LineEvent>(json)!;
        Assert.Equal("postback", evt.Type);
        Assert.NotNull(evt.Postback);
        Assert.Equal("action=test", evt.Postback.Data);
    }

    [Fact]
    public void PostbackEvent_WithDatetimeParams_Deserializes()
    {
        var json = """
        {
            "type": "postback",
            "replyToken": "rtoken",
            "webhookEventId": "ev1",
            "timestamp": 1234567890,
            "source": { "type": "user", "userId": "U1" },
            "postback": { "data": "action=schedule", "params": { "datetime": "2025-03-15T10:00" } }
        }
        """;

        var evt = JsonSerializer.Deserialize<LineEvent>(json)!;
        Assert.NotNull(evt.Postback?.Params);
        Assert.Equal("2025-03-15T10:00", evt.Postback.Params.Datetime);
    }

    [Fact]
    public void QuoteToken_Deserializes()
    {
        var json = """
        {
            "type": "message",
            "replyToken": "rtoken",
            "webhookEventId": "ev1",
            "timestamp": 1234567890,
            "source": { "type": "group", "groupId": "G1", "userId": "U1" },
            "message": { "id": "m1", "type": "text", "text": "hello", "quoteToken": "q3Plxr4AgKd" }
        }
        """;

        var evt = JsonSerializer.Deserialize<LineEvent>(json)!;
        Assert.Equal("q3Plxr4AgKd", evt.Message?.QuoteToken);
    }
}
