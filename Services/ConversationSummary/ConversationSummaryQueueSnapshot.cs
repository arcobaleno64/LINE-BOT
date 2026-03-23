namespace LineBotWebhook.Services;

public sealed record ConversationSummaryQueueSnapshot(
    int QueueDepth,
    int QueueCapacity,
    long TotalEnqueued,
    long TotalDropped,
    long TotalDequeued);
