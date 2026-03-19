namespace LineBotWebhook.Services;

public class UserRequestThrottleService
{
    private readonly Dictionary<string, DateTime> _lastRequestUtc = [];
    private readonly object _lock = new();
    private readonly TimeSpan _cooldown;

    public UserRequestThrottleService(int cooldownSeconds = 5)
    {
        _cooldown = TimeSpan.FromSeconds(Math.Max(1, cooldownSeconds));
    }

    public bool TryAcquire(string userKey, out int retryAfterSeconds)
    {
        lock (_lock)
        {
            var now = DateTime.UtcNow;

            if (_lastRequestUtc.TryGetValue(userKey, out var last))
            {
                var elapsed = now - last;
                if (elapsed < _cooldown)
                {
                    retryAfterSeconds = Math.Max(1, (int)Math.Ceiling((_cooldown - elapsed).TotalSeconds));
                    return false;
                }
            }

            _lastRequestUtc[userKey] = now;
            retryAfterSeconds = 0;

            if (_lastRequestUtc.Count > 2000)
            {
                var cutoff = now - TimeSpan.FromHours(1);
                foreach (var key in _lastRequestUtc.Where(x => x.Value < cutoff).Select(x => x.Key).ToList())
                    _lastRequestUtc.Remove(key);
            }

            return true;
        }
    }
}
