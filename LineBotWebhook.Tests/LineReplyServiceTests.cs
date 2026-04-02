using System.Net;

namespace LineBotWebhook.Tests;

public class LineReplyServiceTests
{
    [Fact]
    public async Task ReplyTextAsync_WithQuickReplies_BuildsQuickReplyPayload()
    {
        var config = TestFactory.BuildConfig();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var service = TestFactory.CreateReplyService(config, handler);

        await service.ReplyTextAsync("reply-token", "主回覆", ["分析文件", "分析圖片"], logContext: null, CancellationToken.None);

        using var payload = TestFactory.GetLastReplyPayload(handler);
        Assert.NotNull(payload);
        var message = payload!.RootElement.GetProperty("messages")[0];
        Assert.Equal("主回覆", message.GetProperty("text").GetString());
        var items = message.GetProperty("quickReply").GetProperty("items");
        Assert.Equal(2, items.GetArrayLength());
        Assert.Equal("分析文件", items[0].GetProperty("action").GetProperty("text").GetString());
        Assert.Equal("分析圖片", items[1].GetProperty("action").GetProperty("text").GetString());
    }

    [Fact]
    public async Task ReplyTextAsync_WithoutQuickReplies_RemainsPlainText()
    {
        var config = TestFactory.BuildConfig();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var service = TestFactory.CreateReplyService(config, handler);

        await service.ReplyTextAsync("reply-token", "主回覆", CancellationToken.None);

        using var payload = TestFactory.GetLastReplyPayload(handler);
        Assert.NotNull(payload);
        var message = payload!.RootElement.GetProperty("messages")[0];
        Assert.False(message.TryGetProperty("quickReply", out _));
    }

    [Fact]
    public async Task ReplyAiTextAsync_SanitizesMarkdown_InsideReplyService()
    {
        var config = TestFactory.BuildConfig();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var service = TestFactory.CreateReplyService(config, handler);

        await service.ReplyAiTextAsync("reply-token", "# 標題\n* **重點**\n詳見[來源](https://example.com)", ["分析文件"], logContext: null, CancellationToken.None);

        using var payload = TestFactory.GetLastReplyPayload(handler);
        Assert.NotNull(payload);
        var message = payload!.RootElement.GetProperty("messages")[0];
        var text = message.GetProperty("text").GetString();
        Assert.NotNull(text);
        Assert.DoesNotContain("#", text!, StringComparison.Ordinal);
        Assert.DoesNotContain("**", text!, StringComparison.Ordinal);
        Assert.Contains("• 重點", text!, StringComparison.Ordinal);
        Assert.Contains("來源 (https://example.com)", text!, StringComparison.Ordinal);

        var quickReplyItems = message.GetProperty("quickReply").GetProperty("items");
        Assert.Equal(1, quickReplyItems.GetArrayLength());
    }

    [Fact]
    public async Task ReplyTextAsync_DoesNotSanitize_WhenUsingRawTextChannel()
    {
        var config = TestFactory.BuildConfig();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var service = TestFactory.CreateReplyService(config, handler);

        await service.ReplyTextAsync("reply-token", "# 原文", CancellationToken.None);

        using var payload = TestFactory.GetLastReplyPayload(handler);
        Assert.NotNull(payload);
        var text = payload!.RootElement.GetProperty("messages")[0].GetProperty("text").GetString();
        Assert.Equal("# 原文", text);
    }

    [Fact]
    public async Task ReplyTextAsync_LongContent_SplitsIntoMultipleLineMessages()
    {
        var config = TestFactory.BuildConfig();
        var handler = new RecordingHttpMessageHandler((request, ct) => Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        var service = TestFactory.CreateReplyService(config, handler);
        var longText = string.Join('\n', Enumerable.Repeat(new string('a', 1200), 6));

        await service.ReplyTextAsync("reply-token", longText, CancellationToken.None);

        using var payload = TestFactory.GetLastReplyPayload(handler);
        Assert.NotNull(payload);
        var messages = payload!.RootElement.GetProperty("messages");
        Assert.True(messages.GetArrayLength() >= 2);
        Assert.True(messages.GetArrayLength() <= 5);
        Assert.All(messages.EnumerateArray(), message =>
        {
            var text = message.GetProperty("text").GetString();
            Assert.False(string.IsNullOrWhiteSpace(text));
            Assert.True(text!.Length <= 5000);
        });
    }
}
