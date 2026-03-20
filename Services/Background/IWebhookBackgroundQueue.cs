namespace LineBotWebhook.Services;

public interface IWebhookBackgroundQueue
{
    bool TryEnqueue(WebhookQueueItem item);
    IAsyncEnumerable<WebhookQueueItem> DequeueAllAsync(CancellationToken cancellationToken);
    WebhookQueueSnapshot GetSnapshot();
    void Complete();
}
