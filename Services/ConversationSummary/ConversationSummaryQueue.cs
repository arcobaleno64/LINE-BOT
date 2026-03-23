using System.Threading.Channels;

namespace LineBotWebhook.Services;

public sealed class ConversationSummaryQueue : IConversationSummaryQueue
{
    private const int Capacity = 64;

    private readonly Channel<ConversationSummaryWorkItem> _channel;
    private readonly ILogger<ConversationSummaryQueue> _logger;
    private long _queueDepth;
    private long _totalEnqueued;
    private long _totalDropped;
    private long _totalDequeued;

    public ConversationSummaryQueue(ILogger<ConversationSummaryQueue> logger)
    {
        _logger = logger;
        _channel = Channel.CreateBounded<ConversationSummaryWorkItem>(new BoundedChannelOptions(Capacity)
        {
            FullMode = BoundedChannelFullMode.Wait,
            SingleReader = true,
            SingleWriter = false
        });
    }

    public bool TryEnqueue(ConversationSummaryWorkItem item)
    {
        var written = _channel.Writer.TryWrite(item);
        if (written)
        {
            Interlocked.Increment(ref _totalEnqueued);
            Interlocked.Increment(ref _queueDepth);
            _logger.LogDebug(
                "Conversation summary work enqueued. UserKeyFingerprint={UserKeyFingerprint} PendingCount={PendingCount} MessageCount={MessageCount}",
                item.UserKeyFingerprint,
                item.PendingCount,
                item.MessageCount);
            return true;
        }

        Interlocked.Increment(ref _totalDropped);
        _logger.LogWarning(
            "Dropped conversation summary work because summary queue is full. UserKeyFingerprint={UserKeyFingerprint} PendingCount={PendingCount} MessageCount={MessageCount}",
            item.UserKeyFingerprint,
            item.PendingCount,
            item.MessageCount);
        return false;
    }

    public async IAsyncEnumerable<ConversationSummaryWorkItem> DequeueAllAsync([System.Runtime.CompilerServices.EnumeratorCancellation] CancellationToken cancellationToken)
    {
        while (await _channel.Reader.WaitToReadAsync(cancellationToken))
        {
            while (_channel.Reader.TryRead(out var item))
            {
                Interlocked.Increment(ref _totalDequeued);
                Interlocked.Decrement(ref _queueDepth);
                yield return item;
            }
        }
    }

    public ConversationSummaryQueueSnapshot GetSnapshot()
    {
        return new ConversationSummaryQueueSnapshot(
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
