namespace LineBotWebhook.Services;

public class Ai429BackoffService
{
    private readonly object _lock = new();
    private DateTime _cooldownUntilUtc = DateTime.MinValue;

    public bool TryPass(out int retryAfterSeconds)
    {
        lock (_lock)
        {
            var now = DateTime.UtcNow;
            if (now >= _cooldownUntilUtc)
            {
                retryAfterSeconds = 0;
                return true;
            }

            retryAfterSeconds = Math.Max(1, (int)Math.Ceiling((_cooldownUntilUtc - now).TotalSeconds));
            return false;
        }
    }

    public void Trigger(int cooldownSeconds)
    {
        lock (_lock)
        {
            var until = DateTime.UtcNow.AddSeconds(Math.Max(1, cooldownSeconds));
            if (until > _cooldownUntilUtc)
                _cooldownUntilUtc = until;
        }
    }
}
