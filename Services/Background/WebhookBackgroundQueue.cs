using System.Threading.Channels;

namespace LineBotWebhook.Services;

public sealed class WebhookBackgroundQueue : IWebhookBackgroundQueue
{
    private const int Capacity = 256;

    private readonly Channel<WebhookQueueItem> _channel;
    private readonly ILogger<WebhookBackgroundQueue> _logger;

    public WebhookBackgroundQueue(ILogger<WebhookBackgroundQueue> logger)
    {
        _logger = logger;
        _channel = Channel.CreateBounded<WebhookQueueItem>(new BoundedChannelOptions(Capacity)
        {
            FullMode = BoundedChannelFullMode.Wait,
            SingleReader = true,
            SingleWriter = false
        });
    }

    public bool TryEnqueue(WebhookQueueItem item)
    {
        var written = _channel.Writer.TryWrite(item);
        if (written)
        {
            _logger.LogDebug(
                "Webhook event enqueued. EventId={EventId} SourceType={SourceType} MessageType={MessageType}",
                item.EventId,
                item.SourceType,
                item.MessageType);
            return true;
        }

        _logger.LogWarning(
            "Dropped webhook event because background queue is full. EventId={EventId} SourceType={SourceType} MessageType={MessageType}",
            item.EventId,
            item.SourceType,
            item.MessageType);
        return false;
    }

    public IAsyncEnumerable<WebhookQueueItem> DequeueAllAsync(CancellationToken cancellationToken)
        => _channel.Reader.ReadAllAsync(cancellationToken);

    public void Complete()
    {
        _channel.Writer.TryComplete();
    }
}
