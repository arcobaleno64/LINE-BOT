using System.Threading.Channels;

namespace LineBotWebhook.Services;

public sealed class ConversationSummaryQueue : IConversationSummaryQueue
{
    private const int Capacity = 64;

    private readonly Channel<ConversationSummaryWorkItem> _channel;
    private readonly ILogger<ConversationSummaryQueue> _logger;
    private readonly object _scheduledLock = new();
    private readonly HashSet<string> _scheduled = [];
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
        lock (_scheduledLock)
        {
            var key = GetWorkKey(item);
            if (_scheduled.Contains(key))
                return true;

            if (_channel.Writer.TryWrite(item))
            {
                _scheduled.Add(key);
                Interlocked.Increment(ref _totalEnqueued);
                Interlocked.Increment(ref _queueDepth);
                _logger.LogDebug(
                    "Conversation summary work enqueued. UserKeyFingerprint={UserKeyFingerprint} PendingCount={PendingCount} MessageCount={MessageCount}",
                    item.UserKeyFingerprint,
                    item.PendingCount,
                    item.MessageCount);
                return true;
            }
        }

        Interlocked.Increment(ref _totalDropped);
        _logger.LogWarning(
            "Dropped conversation summary work because summary queue is full. UserKeyFingerprint={UserKeyFingerprint} PendingCount={PendingCount} MessageCount={MessageCount}",
            item.UserKeyFingerprint,
            item.PendingCount,
            item.MessageCount);
        return false;
    }

    public void Complete(ConversationSummaryWorkItem item)
    {
        lock (_scheduledLock)
            _scheduled.Remove(GetWorkKey(item));
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

    private static string GetWorkKey(ConversationSummaryWorkItem item)
        => $"{item.UserKeyHash ?? item.UserKey}:{item.SessionId:N}:{item.SummaryId:N}";
}
