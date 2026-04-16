namespace LineBotWebhook.Services;

public class AiResponseCacheService
{
    private const int MaxCacheEntries = 5000;
    private readonly object _lock = new();
    private readonly Dictionary<string, CacheEntry> _cache = new(StringComparer.Ordinal);

    public bool TryGet(string key, out string value)
    {
        lock (_lock)
        {
            if (!_cache.TryGetValue(key, out var entry))
            {
                value = string.Empty;
                return false;
            }

            if (DateTime.UtcNow > entry.ExpiresAtUtc)
            {
                _cache.Remove(key);
                value = string.Empty;
                return false;
            }

            value = entry.Value;
            return true;
        }
    }

    public void Set(string key, string value, int ttlSeconds)
    {
        var ttl = Math.Max(1, ttlSeconds);
        var entry = new CacheEntry(value, DateTime.UtcNow.AddSeconds(ttl));

        lock (_lock)
        {
            _cache[key] = entry;
            PruneExpiredUnsafe();
        }
    }

    private void PruneExpiredUnsafe()
    {
        var now = DateTime.UtcNow;
        var expiredKeys = _cache
            .Where(kvp => kvp.Value.ExpiresAtUtc <= now)
            .Select(kvp => kvp.Key)
            .ToList();

        foreach (var key in expiredKeys)
            _cache.Remove(key);

        while (_cache.Count > MaxCacheEntries)
        {
            var oldest = _cache.MinBy(kvp => kvp.Value.ExpiresAtUtc).Key;
            _cache.Remove(oldest);
        }
    }

    private sealed record CacheEntry(string Value, DateTime ExpiresAtUtc);
}