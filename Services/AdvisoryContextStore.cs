using System.Collections.Concurrent;

namespace LineBotWebhook.Services;

/// <summary>
/// 暫存「諮詢三段制」之上下文，使得 postback 動作（給範例、列改進、啟用搜尋）可以以
/// 一個短 token 帶回原始 prompt 與結論，避免將完整 prompt 塞進 300-byte 之 postback data。
/// 採用短 TTL 防止記憶體無限增長；超過 MaxEntries 時以最舊者淘汰。
/// </summary>
public sealed class AdvisoryContextStore
{
    private static readonly TimeSpan EntryTtl = TimeSpan.FromMinutes(30);
    private const int MaxEntries = 2000;

    private readonly ConcurrentDictionary<string, Entry> _entries = new(StringComparer.Ordinal);

    public string Save(AdvisoryContext context)
    {
        var token = Guid.NewGuid().ToString("N")[..12];
        _entries[token] = new Entry(context, DateTimeOffset.UtcNow);
        PruneIfNeeded();
        return token;
    }

    public AdvisoryContext? Get(string? token)
    {
        if (string.IsNullOrEmpty(token))
            return null;
        if (!_entries.TryGetValue(token, out var entry))
            return null;
        if (DateTimeOffset.UtcNow - entry.CreatedAt > EntryTtl)
        {
            _entries.TryRemove(token, out _);
            return null;
        }
        return entry.Context;
    }

    private void PruneIfNeeded()
    {
        if (_entries.Count <= MaxEntries)
        {
            // Best-effort expiry sweep.
            var now = DateTimeOffset.UtcNow;
            foreach (var kvp in _entries)
            {
                if (now - kvp.Value.CreatedAt > EntryTtl)
                    _entries.TryRemove(kvp.Key, out _);
            }
            return;
        }

        // 超過上限：依舊起算淘汰至 MaxEntries 之 80%。
        var target = (int)(MaxEntries * 0.8);
        foreach (var kvp in _entries.OrderBy(kvp => kvp.Value.CreatedAt))
        {
            if (_entries.Count <= target)
                break;
            _entries.TryRemove(kvp.Key, out _);
        }
    }

    private sealed record Entry(AdvisoryContext Context, DateTimeOffset CreatedAt);
}

public sealed record AdvisoryContext(string UserKey, string OriginalPrompt, string Conclusion);
