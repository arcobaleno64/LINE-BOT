using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.Extensions.Logging;

namespace LineBotWebhook.Tests;

public class WebhookBackgroundServiceTests
{
    [Fact]
    public async Task Worker_ConsumesQueuedItem_AndDispatchesIt()
    {
        var queue = new WebhookBackgroundQueue(new TestLogger<WebhookBackgroundQueue>());
        var dispatcher = new FakeDispatcher();
        var logger = new TestLogger<WebhookBackgroundService>();
        using var worker = new WebhookBackgroundService(queue, dispatcher, logger);

        await worker.StartAsync(CancellationToken.None);

        var evt = BuildEvent("evt-1");
        Assert.True(queue.TryEnqueue(new WebhookQueueItem(evt, "https://unit.test")));

        var dispatched = await dispatcher.WaitForDispatchAsync(TimeSpan.FromSeconds(2));

        await worker.StopAsync(CancellationToken.None);

        Assert.True(dispatched);
        Assert.Equal(1, dispatcher.DispatchCalls);
        Assert.Equal("https://unit.test", dispatcher.Dispatches[0].PublicBaseUrl);
    }

    [Fact]
    public async Task Worker_LogsError_WhenDispatcherThrows_AndContinuesToNextItem()
    {
        var queue = new WebhookBackgroundQueue(new TestLogger<WebhookBackgroundQueue>());
        var dispatcher = new FakeDispatcher();
        var logger = new TestLogger<WebhookBackgroundService>();
        var secondDispatch = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var callCount = 0;
        dispatcher.OnDispatchAsync = (evt, publicBaseUrl, ct) =>
        {
            callCount++;
            if (callCount == 1)
                throw new InvalidOperationException("boom");

            secondDispatch.TrySetResult(true);
            return Task.CompletedTask;
        };

        using var worker = new WebhookBackgroundService(queue, dispatcher, logger);
        await worker.StartAsync(CancellationToken.None);

        Assert.True(queue.TryEnqueue(new WebhookQueueItem(BuildEvent("evt-fail"), "https://unit.test")));
        Assert.True(queue.TryEnqueue(new WebhookQueueItem(BuildEvent("evt-next"), "https://unit.test")));

        var completed = await Task.WhenAny(secondDispatch.Task, Task.Delay(TimeSpan.FromSeconds(2)));

        await worker.StopAsync(CancellationToken.None);

        Assert.Same(secondDispatch.Task, completed);
        var errorLog = Assert.Single(logger.Entries, x => x.Level == LogLevel.Error && x.Message.Contains("Error handling event", StringComparison.Ordinal));
        Assert.Equal("evt-fail", errorLog.Properties["EventId"]);
        Assert.Equal("user", errorLog.Properties["SourceType"]);
        Assert.Equal("text", errorLog.Properties["MessageType"]);
        Assert.Equal(2, dispatcher.DispatchCalls);
    }

    [Fact]
    public async Task Worker_StopAsync_CompletesWithoutThrowing()
    {
        var queue = new WebhookBackgroundQueue(new TestLogger<WebhookBackgroundQueue>());
        var dispatcher = new FakeDispatcher();
        var logger = new TestLogger<WebhookBackgroundService>();
        using var worker = new WebhookBackgroundService(queue, dispatcher, logger);

        await worker.StartAsync(CancellationToken.None);
        await worker.StopAsync(CancellationToken.None);

        Assert.Contains(logger.Entries, x => x.Level == LogLevel.Information && x.Message.Contains("Webhook background worker started", StringComparison.Ordinal));
        Assert.Contains(logger.Entries, x => x.Level == LogLevel.Information && x.Message.Contains("Webhook background worker stopping", StringComparison.Ordinal));
    }

    [Fact]
    public void FakeQueue_CanVerifyControllerEnqueuePath_WithoutDispatching()
    {
        var queue = new FakeWebhookBackgroundQueue();

        var written = queue.TryEnqueue(new WebhookQueueItem(BuildEvent("evt-queue"), "https://unit.test"));

        Assert.True(written);
        Assert.Single(queue.Items);
    }

    [Fact]
    public void BoundedQueue_WhenFull_DropsNewItem()
    {
        var logger = new TestLogger<WebhookBackgroundQueue>();
        var queue = new WebhookBackgroundQueue(logger);

        for (var i = 0; i < 256; i++)
            Assert.True(queue.TryEnqueue(new WebhookQueueItem(BuildEvent($"evt-{i}"), "https://unit.test")));

        var written = queue.TryEnqueue(new WebhookQueueItem(BuildEvent("evt-overflow"), "https://unit.test"));

        Assert.False(written);
        Assert.Contains(logger.Entries, x => x.Level == LogLevel.Warning && x.Message.Contains("background queue is full", StringComparison.Ordinal));
    }

    private static LineEvent BuildEvent(string eventId)
    {
        return new LineEvent
        {
            Type = "message",
            ReplyToken = "reply-token",
            WebhookEventId = eventId,
            Source = new LineSource
            {
                Type = "user",
                UserId = "u1"
            },
            Message = new LineMessage
            {
                Id = "m1",
                Type = "text",
                Text = "hello"
            }
        };
    }
}
