using Microsoft.Extensions.Caching.Memory;

namespace LineBotWebhook.Services;

public interface IWebhookEventDeduplicationService
{
    /// <summary>
    /// Returns true if this eventId is new (first time seen) and marks it as seen.
    /// Returns false if the eventId was already seen within the TTL window (duplicate).
    /// Events with empty/null eventId are always treated as new (cannot be deduplicated).
    /// </summary>
    bool TryMarkSeen(string? eventId);
}

public sealed class WebhookEventDeduplicationService : IWebhookEventDeduplicationService, IDisposable
{
    private readonly MemoryCache _cache = new(new MemoryCacheOptions());
    private readonly Lock _gate = new();
    private static readonly TimeSpan Ttl = TimeSpan.FromSeconds(60);

    public bool TryMarkSeen(string? eventId)
    {
        if (string.IsNullOrEmpty(eventId))
            return true; // Cannot deduplicate without an ID — treat as new

        // 鎖以保證 TryGetValue+Set 為原子操作：避免並行同 eventId 各自被視為新事件，
        // 造成 replyToken 競態與 AI 呼叫重複。
        lock (_gate)
        {
            if (_cache.TryGetValue(eventId, out _))
                return false; // Duplicate

            _cache.Set(eventId, true, Ttl);
            return true; // New
        }
    }

    public void Dispose() => _cache.Dispose();
}
