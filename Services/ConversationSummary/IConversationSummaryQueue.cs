namespace LineBotWebhook.Services;

public interface IConversationSummaryQueue
{
    bool TryEnqueue(ConversationSummaryWorkItem item);
    IAsyncEnumerable<ConversationSummaryWorkItem> DequeueAllAsync(CancellationToken cancellationToken);
    ConversationSummaryQueueSnapshot GetSnapshot();
    void Complete();
}
