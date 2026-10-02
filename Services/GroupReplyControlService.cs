using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public sealed class GroupReplyControlService
{
    private readonly object _sync = new();
    private readonly Dictionary<string, DateTimeOffset> _pausedUntilByScope = new(StringComparer.Ordinal);
    private readonly TimeProvider _timeProvider;

    public GroupReplyControlService(TimeProvider? timeProvider = null)
    {
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public static string? GetScopeKey(LineEvent evt)
    {
        var source = evt.Source;
        if (source?.Type == "group" && !string.IsNullOrWhiteSpace(source.GroupId))
            return $"group:{source.GroupId}";

        if (source?.Type == "room" && !string.IsNullOrWhiteSpace(source.RoomId))
            return $"room:{source.RoomId}";

        return null;
    }

    public DateTimeOffset PauseFor(string scopeKey, TimeSpan duration)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(scopeKey);
        ArgumentOutOfRangeException.ThrowIfLessThanOrEqual(duration, TimeSpan.Zero);

        var pausedUntil = _timeProvider.GetUtcNow() + duration;
        lock (_sync)
            _pausedUntilByScope[scopeKey] = pausedUntil;
        return pausedUntil;
    }

    public bool Resume(string scopeKey)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(scopeKey);
        lock (_sync)
            return _pausedUntilByScope.Remove(scopeKey);
    }

    public bool IsPaused(string scopeKey)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(scopeKey);
        lock (_sync)
        {
            if (!_pausedUntilByScope.TryGetValue(scopeKey, out var pausedUntil))
                return false;

            if (pausedUntil > _timeProvider.GetUtcNow())
                return true;

            _pausedUntilByScope.Remove(scopeKey);
            return false;
        }
    }
}
