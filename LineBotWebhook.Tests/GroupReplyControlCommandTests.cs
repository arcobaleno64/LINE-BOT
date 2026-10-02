using System.Net;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.Extensions.Configuration;

namespace LineBotWebhook.Tests;

public class GroupReplyControlCommandTests
{
    [Fact]
    public async Task MentionedAllowlistedAdminPauseCommand_IsHandledWithoutCallingAi()
    {
        var config = TestFactory.BuildConfig(new Dictionary<string, string?>
        {
            ["App:GroupAdminUserIds"] = "U-admin"
        });
        var ai = new FakeAiService();
        var groupReplyControl = new GroupReplyControlService();
        var httpHandler = CreateSuccessHttpHandler();
        var handler = TestFactory.CreateTextHandler(config, ai, httpHandler, groupReplyControl: groupReplyControl);

        var handled = await handler.HandleAsync(BuildGroupTextEvent("U-admin", "暫停回覆 30 分鐘", "reply-pause"), "https://unit.test", CancellationToken.None);

        Assert.True(handled);
        Assert.Equal(0, ai.TextCalls);
        Assert.True(groupReplyControl.IsPaused("group:G1"));
        Assert.Contains("30 分鐘", TestFactory.GetLastReplyText(httpHandler), StringComparison.Ordinal);
    }

    [Fact]
    public async Task NonAllowlistedUser_CannotPauseGroup()
    {
        var config = BuildAdminConfig();
        var control = new GroupReplyControlService();
        var httpHandler = CreateSuccessHttpHandler();
        var handler = TestFactory.CreateTextHandler(config, new FakeAiService(), httpHandler, groupReplyControl: control);

        await handler.HandleAsync(BuildGroupTextEvent("U-other", "暫停回覆 30 分鐘", "reply-denied"), "https://unit.test", CancellationToken.None);

        Assert.False(control.IsPaused("group:G1"));
        Assert.Contains("僅限 Bot 管理員", TestFactory.GetLastReplyText(httpHandler), StringComparison.Ordinal);
    }

    [Fact]
    public async Task NonAllowlistedUser_CannotResumePausedGroup()
    {
        var config = BuildAdminConfig();
        var control = new GroupReplyControlService();
        control.PauseFor("group:G1", TimeSpan.FromMinutes(30));
        var httpHandler = CreateSuccessHttpHandler();
        var handler = TestFactory.CreateTextHandler(config, new FakeAiService(), httpHandler, groupReplyControl: control);

        await handler.HandleAsync(BuildGroupTextEvent("U-other", "恢復回覆", "reply-resume-denied"), "https://unit.test", CancellationToken.None);

        Assert.True(control.IsPaused("group:G1"));
        Assert.Contains("僅限 Bot 管理員", TestFactory.GetLastReplyText(httpHandler), StringComparison.Ordinal);
    }

    [Fact]
    public async Task GroupPauseCommand_WithoutMentionDoesNotChangeState()
    {
        var control = new GroupReplyControlService();
        var httpHandler = CreateSuccessHttpHandler();
        var handler = TestFactory.CreateTextHandler(BuildAdminConfig(), new FakeAiService(), httpHandler, groupReplyControl: control);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "reply-pause-unmentioned",
            Source = new LineSource { Type = "group", GroupId = "G1", UserId = "U-admin" },
            Message = new LineMessage { Id = "pause-unmentioned", Type = "text", Text = "暫停回覆 30 分鐘" }
        };

        await handler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.False(control.IsPaused("group:G1"));
        Assert.Empty(httpHandler.Requests);
    }

    [Fact]
    public async Task PausedGroup_IgnoresQuestionsButStillAnswersHelpAndAdminTest()
    {
        var control = new GroupReplyControlService();
        control.PauseFor("group:G1", TimeSpan.FromMinutes(30));
        var ai = new FakeAiService();
        var httpHandler = CreateSuccessHttpHandler();
        var handler = TestFactory.CreateTextHandler(BuildAdminConfig(), ai, httpHandler, groupReplyControl: control);

        await handler.HandleAsync(BuildGroupTextEvent("U-admin", "請幫我整理這段文字", "reply-question"), "https://unit.test", CancellationToken.None);
        Assert.Equal(0, ai.TextCalls);
        Assert.Empty(httpHandler.Requests);

        await handler.HandleAsync(BuildGroupTextEvent("U-admin", "說明", "reply-help"), "https://unit.test", CancellationToken.None);
        Assert.Contains("恢復回覆", TestFactory.GetLastReplyText(httpHandler), StringComparison.Ordinal);

        await handler.HandleAsync(BuildGroupTextEvent("U-admin-2", "管理員測試", "reply-admin"), "https://unit.test", CancellationToken.None);
        Assert.Contains("已列入此 Bot 的管理員名單", TestFactory.GetLastReplyText(httpHandler), StringComparison.Ordinal);
    }

    [Fact]
    public async Task MentionedAllowlistedAdminResumeCommand_ResumesOnlyThatGroup()
    {
        var control = new GroupReplyControlService();
        control.PauseFor("group:G1", TimeSpan.FromMinutes(30));
        var httpHandler = CreateSuccessHttpHandler();
        var handler = TestFactory.CreateTextHandler(BuildAdminConfig(), new FakeAiService(), httpHandler, groupReplyControl: control);

        await handler.HandleAsync(BuildGroupTextEvent("U-admin", "恢復回覆", "reply-resume"), "https://unit.test", CancellationToken.None);

        Assert.False(control.IsPaused("group:G1"));
        Assert.Contains("已恢復", TestFactory.GetLastReplyText(httpHandler), StringComparison.Ordinal);
    }

    [Fact]
    public async Task PrivatePauseCommand_DoesNotPauseAnyGroup()
    {
        var control = new GroupReplyControlService();
        var httpHandler = CreateSuccessHttpHandler();
        var handler = TestFactory.CreateTextHandler(BuildAdminConfig(), new FakeAiService(), httpHandler, groupReplyControl: control);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "reply-private-pause",
            Source = new LineSource { Type = "user", UserId = "U-admin" },
            Message = new LineMessage { Id = "private-pause", Type = "text", Text = "暫停回覆 30 分鐘" }
        };

        await handler.HandleAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.False(control.IsPaused("group:G1"));
        Assert.Contains("群組指令", TestFactory.GetLastReplyText(httpHandler), StringComparison.Ordinal);
    }

    [Fact]
    public void PauseAutomaticallyExpiresAfterThirtyMinutes()
    {
        var timeProvider = new AdjustableTimeProvider(new DateTimeOffset(2026, 10, 2, 0, 0, 0, TimeSpan.Zero));
        var control = new GroupReplyControlService(timeProvider);
        control.PauseFor("group:G1", TimeSpan.FromMinutes(30));

        timeProvider.Advance(TimeSpan.FromMinutes(30));

        Assert.False(control.IsPaused("group:G1"));
    }

    [Theory]
    [InlineData("image")]
    [InlineData("file")]
    public async Task PausedGroupMedia_IsNotPassedToMessageHandlers(string messageType)
    {
        var config = TestFactory.BuildConfig();
        var metrics = new FakeWebhookMetrics();
        var httpHandler = CreateSuccessHttpHandler();
        var httpClient = new HttpClient(httpHandler);
        var handlers = new CountingMessageHandlers();
        var control = new GroupReplyControlService();
        control.PauseFor("group:G1", TimeSpan.FromMinutes(30));
        var dispatcher = new LineWebhookDispatcher(
            handlers,
            handlers,
            handlers,
            new LineReplyService(httpClient, config, metrics, Microsoft.Extensions.Logging.Abstractions.NullLogger<LineReplyService>.Instance),
            new LoadingIndicatorService(httpClient, config, Microsoft.Extensions.Logging.Abstractions.NullLogger<LoadingIndicatorService>.Instance),
            config,
            new TestFactory.NoopAdvisoryPostbackHandler(),
            new TestFactory.NoopJoinLeaveHandler(),
            metrics,
            Microsoft.Extensions.Logging.Abstractions.NullLogger<LineWebhookDispatcher>.Instance,
            control);
        var evt = new LineEvent
        {
            Type = "message",
            ReplyToken = "reply-paused-media",
            Source = new LineSource { Type = "group", GroupId = "G1", UserId = "U1" },
            Message = new LineMessage { Id = "paused-media", Type = messageType, FileName = "example.txt" }
        };

        await dispatcher.DispatchAsync(evt, "https://unit.test", CancellationToken.None);

        Assert.Equal(0, handlers.TextCalls);
        Assert.Equal(0, handlers.ImageCalls);
        Assert.Equal(0, handlers.FileCalls);
        Assert.Empty(httpHandler.Requests);
    }

    [Fact]
    public async Task PausingOneGroup_DoesNotAffectAnotherGroupOrPrivateChat()
    {
        var control = new GroupReplyControlService();
        control.PauseFor("group:G1", TimeSpan.FromMinutes(30));
        var ai = new FakeAiService();
        var httpHandler = CreateSuccessHttpHandler();
        var handler = TestFactory.CreateTextHandler(BuildAdminConfig(), ai, httpHandler, groupReplyControl: control);

        await handler.HandleAsync(BuildGroupTextEvent("U-other", "另一個群組的問題", "reply-other-group", "G2"), "https://unit.test", CancellationToken.None);
        await handler.HandleAsync(BuildPrivateTextEvent("U-other", "私聊問題", "reply-private"), "https://unit.test", CancellationToken.None);

        Assert.Equal(2, ai.TextCalls);
        Assert.True(control.IsPaused("group:G1"));
    }

    private static IConfiguration BuildAdminConfig() => TestFactory.BuildConfig(new Dictionary<string, string?>
    {
        ["App:GroupAdminUserIds"] = "U-admin,U-admin-2"
    });

    private static RecordingHttpMessageHandler CreateSuccessHttpHandler() => new((_, _) =>
        Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));

    private static LineEvent BuildGroupTextEvent(string userId, string text, string replyToken, string groupId = "G1") => new()
    {
        Type = "message",
        ReplyToken = replyToken,
        Source = new LineSource { Type = "group", GroupId = groupId, UserId = userId },
        Message = new LineMessage
        {
            Id = replyToken,
            Type = "text",
            Text = $"@Bot {text}",
            Mention = new LineMention
            {
                Mentionees = [new LineMentionee { Index = 0, Length = 4, IsSelf = true }]
            }
        }
    };

    private static LineEvent BuildPrivateTextEvent(string userId, string text, string replyToken) => new()
    {
        Type = "message",
        ReplyToken = replyToken,
        Source = new LineSource { Type = "user", UserId = userId },
        Message = new LineMessage { Id = replyToken, Type = "text", Text = text }
    };

    private sealed class AdjustableTimeProvider(DateTimeOffset utcNow) : TimeProvider
    {
        private DateTimeOffset _utcNow = utcNow;

        public override DateTimeOffset GetUtcNow() => _utcNow;

        public void Advance(TimeSpan duration) => _utcNow += duration;
    }

    private sealed class CountingMessageHandlers : ITextMessageHandler, IImageMessageHandler, IFileMessageHandler
    {
        public int TextCalls { get; private set; }
        public int ImageCalls { get; private set; }
        public int FileCalls { get; private set; }

        public Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
        {
            if (evt.Message?.Type == "text")
                TextCalls++;
            else if (evt.Message?.Type == "image")
                ImageCalls++;
            else if (evt.Message?.Type == "file")
                FileCalls++;
            return Task.FromResult(false);
        }
    }
}
