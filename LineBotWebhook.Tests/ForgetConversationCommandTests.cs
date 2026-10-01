using System.Net;
using LineBotWebhook.Models;
using LineBotWebhook.Services;

namespace LineBotWebhook.Tests;

public class ForgetConversationCommandTests
{
    [Fact]
    public async Task GroupMention_ClearsOnlyInvokingMembersState()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var http = new RecordingHttpMessageHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var history = new ConversationHistoryService(maxRounds: 5, idleMinutes: -1);
        var cache = new AiResponseCacheService();
        var advisoryStore = new AdvisoryContextStore();
        const string userKey = "g1:u1";
        const string otherUserKey = "g1:u2";
        const string userCacheKey = userKey + ":text:question";
        const string otherCacheKey = otherUserKey + ":text:question";

        history.Append(userKey, "old question", "old answer");
        history.Append(otherUserKey, "other question", "other answer");
        cache.Set(userCacheKey, "old cached answer", 180);
        cache.Set(otherCacheKey, "other cached answer", 180);
        var userAdvisoryToken = advisoryStore.Save(new AdvisoryContext(userKey, "old question", "old conclusion"));
        var otherAdvisoryToken = advisoryStore.Save(new AdvisoryContext(otherUserKey, "other question", "other conclusion"));
        var handler = TestFactory.CreateTextHandler(
            config,
            ai,
            http,
            cache: cache,
            history: history,
            advisoryStore: advisoryStore);

        await handler.HandleAsync(BuildTextEvent("group", "@bot 忘記對話", mentioned: true), "https://unit.test", CancellationToken.None);

        Assert.Empty(history.GetHistory(userKey));
        Assert.Equal(["other question", "other answer"], history.GetHistory(otherUserKey).Select(message => message.Content));
        Assert.False(cache.TryGet(userCacheKey, out _));
        Assert.True(cache.TryGet(otherCacheKey, out var otherCachedAnswer));
        Assert.Equal("other cached answer", otherCachedAnswer);
        Assert.Null(advisoryStore.Get(userAdvisoryToken));
        Assert.NotNull(advisoryStore.Get(otherAdvisoryToken));
        Assert.Equal(0, ai.TextCalls);
        Assert.Contains("其他成員不受影響", TestFactory.GetLastReplyText(http));
    }

    [Fact]
    public async Task GroupCommandWithoutMention_DoesNotClearState()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var http = new RecordingHttpMessageHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var history = new ConversationHistoryService(maxRounds: 5, idleMinutes: -1);
        var cache = new AiResponseCacheService();
        var advisoryStore = new AdvisoryContextStore();
        const string userKey = "g1:u1";
        const string cacheKey = userKey + ":text:question";

        history.Append(userKey, "old question", "old answer");
        cache.Set(cacheKey, "cached answer", 180);
        var advisoryToken = advisoryStore.Save(new AdvisoryContext(userKey, "old question", "old conclusion"));
        var handler = TestFactory.CreateTextHandler(
            config,
            ai,
            http,
            cache: cache,
            history: history,
            advisoryStore: advisoryStore);

        await handler.HandleAsync(BuildTextEvent("group", "忘記對話"), "https://unit.test", CancellationToken.None);

        Assert.Equal(["old question", "old answer"], history.GetHistory(userKey).Select(message => message.Content));
        Assert.True(cache.TryGet(cacheKey, out _));
        Assert.NotNull(advisoryStore.Get(advisoryToken));
        Assert.Empty(http.Requests);
        Assert.Equal(0, ai.TextCalls);
    }

    [Fact]
    public async Task DirectMessage_ClearsInvokingUsersState()
    {
        var config = TestFactory.BuildConfig();
        var ai = new FakeAiService();
        var http = new RecordingHttpMessageHandler((_, _) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var history = new ConversationHistoryService(maxRounds: 5, idleMinutes: -1);
        var cache = new AiResponseCacheService();
        var advisoryStore = new AdvisoryContextStore();
        const string userKey = "u1:u1";
        const string cacheKey = userKey + ":text:question";

        history.Append(userKey, "old question", "old answer");
        cache.Set(cacheKey, "cached answer", 180);
        var advisoryToken = advisoryStore.Save(new AdvisoryContext(userKey, "old question", "old conclusion"));
        var handler = TestFactory.CreateTextHandler(
            config,
            ai,
            http,
            cache: cache,
            history: history,
            advisoryStore: advisoryStore);

        await handler.HandleAsync(BuildTextEvent("user", "  忘記對話  "), "https://unit.test", CancellationToken.None);

        Assert.Empty(history.GetHistory(userKey));
        Assert.False(cache.TryGet(cacheKey, out _));
        Assert.Null(advisoryStore.Get(advisoryToken));
        Assert.Contains("暫存脈絡", TestFactory.GetLastReplyText(http));
        Assert.Equal(0, ai.TextCalls);
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

        return new LineEvent
        {
            Type = "message",
            ReplyToken = "reply-token",
            Source = new LineSource
            {
                Type = sourceType,
                UserId = "u1",
                GroupId = sourceType == "group" ? "g1" : null,
                RoomId = sourceType == "room" ? "r1" : null
            },
            Message = message
        };
    }
}
