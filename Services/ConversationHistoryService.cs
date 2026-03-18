namespace LineBotWebhook.Services;

/// <summary>
/// 每位使用者保留最近 N 輪對話，超過自動捨棄最舊的；
/// 超過閒置時間自動清除，避免記憶體無限增長。
/// </summary>
public class ConversationHistoryService
{
    public record ChatMessage(string Role, string Content);

    private sealed class Session
    {
        public List<ChatMessage> Messages { get; } = [];
        public DateTime LastAccess { get; set; } = DateTime.UtcNow;
    }

    private readonly Dictionary<string, Session> _sessions = [];
    private readonly object _lock = new();
    private readonly int _maxRounds;
    private readonly TimeSpan _idleExpiry;

    public ConversationHistoryService(int maxRounds = 15, int idleMinutes = 30)
    {
        _maxRounds  = maxRounds;
        _idleExpiry = TimeSpan.FromMinutes(idleMinutes);
    }

    /// <summary>取得指定使用者的歷史訊息（唯讀快照）</summary>
    public IReadOnlyList<ChatMessage> GetHistory(string userKey)
    {
        lock (_lock)
        {
            Prune();
            return _sessions.TryGetValue(userKey, out var s)
                ? s.Messages.AsReadOnly()
                : (IReadOnlyList<ChatMessage>)Array.Empty<ChatMessage>();
        }
    }

    /// <summary>新增一輪對話（user + assistant），超過上限自動丟掉最舊一輪</summary>
    public void Append(string userKey, string userText, string assistantText)
    {
        lock (_lock)
        {
            if (!_sessions.TryGetValue(userKey, out var session))
                session = _sessions[userKey] = new Session();

            session.Messages.Add(new ChatMessage("user",      userText));
            session.Messages.Add(new ChatMessage("assistant", assistantText));
            session.LastAccess = DateTime.UtcNow;

            // 每輪 2 則，超過 maxRounds 輪就刪掉最舊一輪
            int maxMessages = _maxRounds * 2;
            while (session.Messages.Count > maxMessages)
                session.Messages.RemoveAt(0);
        }
    }

    /// <summary>清除指定使用者的對話記憶</summary>
    public void Clear(string userKey)
    {
        lock (_lock) { _sessions.Remove(userKey); }
    }

    private void Prune()
    {
        var cutoff = DateTime.UtcNow - _idleExpiry;
        foreach (var key in _sessions.Keys
            .Where(k => _sessions[k].LastAccess < cutoff)
            .ToList())
            _sessions.Remove(key);
    }
}
