using LineBotWebhook.Services;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;

namespace LineBotWebhook.Tests;

public class ConversationSummaryWorkflowTests
{
    [Fact]
    public void ConversationHistoryService_ExceedingThreshold_EnqueuesSummaryWork()
    {
        var queue = new FakeConversationSummaryQueue();
        var history = new ConversationHistoryService(queue, NullLogger<ConversationHistoryService>.Instance, maxRounds: 2, idleMinutes: -1);

        history.Append("user-1", "u1", "a1");
        history.Append("user-1", "u2", "a2");
        history.Append("user-1", "u3", "a3");

        var item = Assert.Single(queue.Items);
        Assert.Equal("user-1", item.UserKey);
        Assert.Equal(6, item.PendingCount);
        Assert.Equal(6, item.MessageCount);

        var snapshot = history.GetSessionSnapshot("user-1");
        Assert.NotNull(snapshot);
        Assert.True(snapshot!.IsSummarizing);
        Assert.Equal(6, snapshot.PendingSummaryCount);
    }

    [Fact]
    public async Task ConversationSummaryWorker_Success_UpdatesSummary_TrimsMessages_AndClearsSummarizing()
    {
        var queue = new ConversationSummaryQueue(new TestLogger<ConversationSummaryQueue>());
        var history = new ConversationHistoryService(queue, NullLogger<ConversationHistoryService>.Instance, maxRounds: 2, idleMinutes: -1);
        var generator = new FakeConversationSummaryGenerator
        {
            OnGenerateAsync = (existingSummary, pendingMessages, ct) => Task.FromResult("這是新的摘要")
        };
        var logger = new TestLogger<ConversationSummaryWorker>();

        history.Append("user-1", "u1", "a1");
        history.Append("user-1", "u2", "a2");
        history.Append("user-1", "u3", "a3");

        using var worker = new ConversationSummaryWorker(queue, history, generator, logger);
        await worker.StartAsync(CancellationToken.None);
        await WaitForAsync(() =>
        {
            var snapshot = history.GetSessionSnapshot("user-1");
            return snapshot is not null && !snapshot.IsSummarizing && snapshot.SessionSummary == "這是新的摘要";
        });
        await worker.StopAsync(CancellationToken.None);

        var session = history.GetSessionSnapshot("user-1");
        Assert.NotNull(session);
        Assert.False(session!.IsSummarizing);
        Assert.Equal("這是新的摘要", session.SessionSummary);
        Assert.Equal(0, session.PendingSummaryCount);
        Assert.True(session.Messages.Count <= 4);

        var historyMessages = history.GetHistory("user-1");
        Assert.Contains("先前對話摘要：", historyMessages[0].Content, StringComparison.Ordinal);
        Assert.Contains(logger.Entries, entry => entry.Level == LogLevel.Information && entry.Message.Contains("Conversation summary completed", StringComparison.Ordinal));
    }

    [Fact]
    public async Task ConversationSummaryWorker_Failure_ClearsSummarizing_AndSessionCanContinue()
    {
        var queue = new ConversationSummaryQueue(new TestLogger<ConversationSummaryQueue>());
        var history = new ConversationHistoryService(queue, NullLogger<ConversationHistoryService>.Instance, maxRounds: 2, idleMinutes: -1);
        var logger = new TestLogger<ConversationSummaryWorker>();
        var generator = new FakeConversationSummaryGenerator
        {
            OnGenerateAsync = (existingSummary, pendingMessages, ct) => throw new HttpRequestException("raw-summary=secret raw-user-text=u3", null, System.Net.HttpStatusCode.BadGateway)
        };

        history.Append("user-1", "u1", "a1");
        history.Append("user-1", "u2", "a2");
        history.Append("user-1", "u3", "a3");

        using var worker = new ConversationSummaryWorker(queue, history, generator, logger);
        await worker.StartAsync(CancellationToken.None);
        await WaitForAsync(() =>
        {
            var snapshot = history.GetSessionSnapshot("user-1");
            return snapshot is not null && !snapshot.IsSummarizing;
        });

        var session = history.GetSessionSnapshot("user-1");
        Assert.NotNull(session);
        Assert.False(session!.IsSummarizing);
        Assert.Null(session.SessionSummary);
        Assert.Equal(0, session.PendingSummaryCount);

        history.Append("user-1", "u4", "a4");
        await WaitForAsync(() => queue.GetSnapshot().TotalEnqueued >= 2);

        await worker.StopAsync(CancellationToken.None);

        var retriggered = history.GetSessionSnapshot("user-1");
        Assert.NotNull(retriggered);
        Assert.True(queue.GetSnapshot().TotalEnqueued >= 2);
        var errors = logger.Entries.Where(entry => entry.Level == LogLevel.Error && entry.Message.Contains("Conversation summary failed", StringComparison.Ordinal)).ToArray();
        Assert.NotEmpty(errors);
        foreach (var error in errors)
        {
            Assert.Null(error.Exception);
            Assert.Equal(502, error.Properties["StatusCode"]);
            Assert.Equal("HttpRequestException", error.Properties["ExceptionType"]);
            Assert.DoesNotContain("raw-summary=secret", error.Message, StringComparison.Ordinal);
            Assert.DoesNotContain("raw-user-text=u3", error.Message, StringComparison.Ordinal);
        }
    }

    [Fact]
    public async Task ConversationSummaryWorker_StopAsync_CompletesCleanly()
    {
        var queue = new ConversationSummaryQueue(new TestLogger<ConversationSummaryQueue>());
        var history = new ConversationHistoryService(queue, NullLogger<ConversationHistoryService>.Instance, maxRounds: 2, idleMinutes: -1);
        var generator = new FakeConversationSummaryGenerator();
        var logger = new TestLogger<ConversationSummaryWorker>();

        using var worker = new ConversationSummaryWorker(queue, history, generator, logger);

        await worker.StartAsync(CancellationToken.None);
        await WaitForAsync(() => logger.Entries.Any(entry => entry.Level == LogLevel.Information && entry.Message.Contains("Conversation summary worker started", StringComparison.Ordinal)));
        await worker.StopAsync(CancellationToken.None);

        Assert.Contains(logger.Entries, entry => entry.Level == LogLevel.Information && entry.Message.Contains("Conversation summary worker started", StringComparison.Ordinal));
        Assert.Contains(logger.Entries, entry => entry.Level == LogLevel.Information && entry.Message.Contains("Conversation summary worker stopping", StringComparison.Ordinal));
    }

    [Fact]
    public void ConversationHistoryService_FallbackTrimming_RemainsWhenSummaryUnavailable()
    {
        var queue = new FakeConversationSummaryQueue { TryEnqueueResult = false };
        var logger = new TestLogger<ConversationHistoryService>();
        var history = new ConversationHistoryService(queue, logger, maxRounds: 2, idleMinutes: -1);

        history.Append("user-1", "u1", "a1");
        history.Append("user-1", "u2", "a2");
        history.Append("user-1", "u3", "a3");

        var session = history.GetSessionSnapshot("user-1");
        Assert.NotNull(session);
        Assert.False(session!.IsSummarizing);
        Assert.Null(session.SessionSummary);
        Assert.Equal(0, session.PendingSummaryCount);
        Assert.Equal(4, session.Messages.Count);
        Assert.Contains(logger.Entries, entry => entry.Level == LogLevel.Warning && entry.Message.Contains("Failed to enqueue conversation summary work", StringComparison.Ordinal));
    }

    [Fact]
    public void ConversationHistoryService_AppendGetClear_Behavior_RemainsIntact()
    {
        var history = new ConversationHistoryService(maxRounds: 2, idleMinutes: -1);

        history.Append("user-1", "u1", "a1");

        var messages = history.GetHistory("user-1");
        Assert.Equal(2, messages.Count);
        Assert.Equal("u1", messages[0].Content);
        Assert.Equal("a1", messages[1].Content);

        history.Clear("user-1");

        Assert.Empty(history.GetHistory("user-1"));
    }

    private static async Task WaitForAsync(Func<bool> condition)
    {
        var timeout = TimeSpan.FromSeconds(2);
        var started = DateTime.UtcNow;
        while (DateTime.UtcNow - started < timeout)
        {
            if (condition())
                return;

            await Task.Delay(20);
        }

        Assert.Fail("Timed out waiting for condition.");
    }
}
