namespace LineBotWebhook.Services;

public sealed record WebhookQueueSnapshot(
    int QueueDepth,
    int QueueCapacity,
    long TotalEnqueued,
    long TotalDropped,
    long TotalDequeued);
