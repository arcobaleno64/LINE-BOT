using System.Net;
using LineBotWebhook.Models;

namespace LineBotWebhook.Tests;

public class GroupAdminTestCommandTests
{
    private const string AdminUserId = "U0123456789abcdef0123456789abcdef";

    [Fact]
    public async Task MentionedGroupCommand_AllowlistedUser_ReturnsAdminStatusWithoutCallingAi()
    {
        var config = TestFactory.BuildConfig(new Dictionary<string, string?>
        {
            ["App:GroupAdminUserIds"] = $" {AdminUserId} , Uabcdef0123456789abcdef0123456789 "
        });
        var ai = new FakeAiService();
        var http = CreateHttpHandler();
        var handler = TestFactory.CreateTextHandler(config, ai, http);

        await handler.HandleAsync(CreateGroupTextEvent(AdminUserId, "@Bot 管理員測試", mentionedBot: true), "https://unit.test", CancellationToken.None);

        Assert.Equal(0, ai.TextCalls);
        Assert.Contains("已列入此 Bot 的管理員名單", TestFactory.GetLastReplyText(http), StringComparison.Ordinal);
    }

    [Fact]
    public async Task MentionedGroupCommand_NonAllowlistedUser_ReturnsNotAdminStatus()
    {
        var config = TestFactory.BuildConfig(new Dictionary<string, string?>
        {
            ["App:GroupAdminUserIds"] = AdminUserId
        });
        var ai = new FakeAiService();
        var http = CreateHttpHandler();
        var handler = TestFactory.CreateTextHandler(config, ai, http);
        const string otherUserId = "U0123456789abcdef0123456789abcde0";

        await handler.HandleAsync(CreateGroupTextEvent(otherUserId, "@Bot 管理員測試", mentionedBot: true), "https://unit.test", CancellationToken.None);

        Assert.Equal(0, ai.TextCalls);
        Assert.Contains("未列入此 Bot 的管理員名單", TestFactory.GetLastReplyText(http), StringComparison.Ordinal);
    }

    [Fact]
    public async Task MentionedGroupCommand_MissingAllowlist_DeniesAdminStatus()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var http = CreateHttpHandler();
        var handler = TestFactory.CreateTextHandler(config, ai, http);

        await handler.HandleAsync(CreateGroupTextEvent(AdminUserId, "@Bot 管理員測試", mentionedBot: true), "https://unit.test", CancellationToken.None);

        Assert.Equal(0, ai.TextCalls);
        Assert.Contains("未列入此 Bot 的管理員名單", TestFactory.GetLastReplyText(http), StringComparison.Ordinal);
    }

    [Fact]
    public async Task MentionedGroupCommand_MissingUserId_DeniesAdminStatus()
    {
        var config = TestFactory.BuildConfig(new Dictionary<string, string?>
        {
            ["App:GroupAdminUserIds"] = AdminUserId
        });
        var ai = new FakeAiService();
        var http = CreateHttpHandler();
        var handler = TestFactory.CreateTextHandler(config, ai, http);

        await handler.HandleAsync(CreateGroupTextEvent(null, "@Bot 管理員測試", mentionedBot: true), "https://unit.test", CancellationToken.None);

        Assert.Equal(0, ai.TextCalls);
        Assert.Contains("未列入此 Bot 的管理員名單", TestFactory.GetLastReplyText(http), StringComparison.Ordinal);
    }

    [Fact]
    public async Task GroupCommandWithoutMention_IsIgnored()
    {
        var config = TestFactory.BuildConfig(new Dictionary<string, string?>
        {
            ["App:GroupAdminUserIds"] = AdminUserId
        });
        var ai = new FakeAiService();
        var http = CreateHttpHandler();
        var handler = TestFactory.CreateTextHandler(config, ai, http);

        await handler.HandleAsync(CreateGroupTextEvent(AdminUserId, "管理員測試", mentionedBot: false), "https://unit.test", CancellationToken.None);

        Assert.Equal(0, ai.TextCalls);
        Assert.Empty(http.Requests);
    }

    [Fact]
    public async Task HelpCommand_ExplainsAdminTestCommand()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var http = CreateHttpHandler();
        var handler = TestFactory.CreateTextHandler(config, ai, http);

        await handler.HandleAsync(CreateGroupTextEvent("U0123456789abcdef0123456789abcdef", "@Bot 說明", mentionedBot: true), "https://unit.test", CancellationToken.None);

        Assert.Equal(0, ai.TextCalls);
        Assert.Contains("管理員測試", TestFactory.GetLastReplyText(http), StringComparison.Ordinal);
    }

    private static RecordingHttpMessageHandler CreateHttpHandler() => new((_, _) =>
        Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));

    private static LineEvent CreateGroupTextEvent(string? userId, string text, bool mentionedBot) => new()
    {
        Type = "message",
        ReplyToken = "reply-admin-test",
        Source = new LineSource { Type = "group", GroupId = "G1", UserId = userId },
        Message = new LineMessage
        {
            Id = "message-admin-test",
            Type = "text",
            Text = text,
            Mention = mentionedBot
                ? new LineMention
                {
                    Mentionees = [new LineMentionee { Index = 0, Length = 4, IsSelf = true }]
                }
                : null
        }
    };
}