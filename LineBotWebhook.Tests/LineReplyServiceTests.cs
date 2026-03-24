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
}
