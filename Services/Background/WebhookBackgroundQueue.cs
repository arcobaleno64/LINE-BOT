using System.Threading.Channels;

namespace LineBotWebhook.Services;

public sealed class WebhookBackgroundQueue : IWebhookBackgroundQueue
{
    private const int Capacity = 256;

    private readonly Channel<WebhookQueueItem> _channel;
    private readonly IWebhookMetrics _metrics;
    private readonly ILogger<WebhookBackgroundQueue> _logger;
    private long _queueDepth;
    private long _totalEnqueued;
    private long _totalDropped;
    private long _totalDequeued;

    public WebhookBackgroundQueue(IWebhookMetrics metrics, ILogger<WebhookBackgroundQueue> logger)
    {
        _metrics = metrics;
        _logger = logger;
        _channel = Channel.CreateBounded<WebhookQueueItem>(new BoundedChannelOptions(Capacity)
        {
            // Wait mode causes TryWrite to return false immediately when the channel is full
            // (TryWrite never blocks — only WriteAsync waits). The false return value is the
            // signal we rely on to track and log dropped events in the else branch below.
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
            Interlocked.Increment(ref _totalEnqueued);
            Interlocked.Increment(ref _queueDepth);
            _metrics.RecordQueueEnqueued();
            _logger.LogDebug(
                "Webhook event enqueued. EventId={EventId} SourceType={SourceType} MessageType={MessageType}",
                item.EventId,
                item.SourceType,
                item.MessageType);
            return true;
        }

        Interlocked.Increment(ref _totalDropped);
        _metrics.RecordQueueDropped();
        _logger.LogWarning(
            "Dropped webhook event because background queue is full. EventId={EventId} SourceType={SourceType} MessageType={MessageType}",
            item.EventId,
            item.SourceType,
            item.MessageType);
        return false;
    }

    public async IAsyncEnumerable<WebhookQueueItem> DequeueAllAsync([System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
    {
        while (await _channel.Reader.WaitToReadAsync(cancellationToken))
        {
            while (_channel.Reader.TryRead(out var item))
            {
                Interlocked.Increment(ref _totalDequeued);
                Interlocked.Decrement(ref _queueDepth);
                _metrics.RecordQueueDequeued();
                yield return item;
            }
        }
    }

    public WebhookQueueSnapshot GetSnapshot()
    {
        return new WebhookQueueSnapshot(
            QueueDepth: (int)Interlocked.Read(ref _queueDepth),
            QueueCapacity: Capacity,
            TotalEnqueued: Interlocked.Read(ref _totalEnqueued),
            TotalDropped: Interlocked.Read(ref _totalDropped),
            TotalDequeued: Interlocked.Read(ref _totalDequeued));
    }

    public void Complete()
    {
        _channel.Writer.TryComplete();
    }
}
