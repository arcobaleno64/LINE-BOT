namespace LineBotWebhook.Services;

public class InFlightRequestMergeService
{
    private readonly object _lock = new();
    private readonly Dictionary<string, Task<string>> _inFlight = new(StringComparer.Ordinal);

    public Task<string> RunAsync(string key, Func<Task<string>> workFactory)
    {
        lock (_lock)
        {
            if (_inFlight.TryGetValue(key, out var existingTask))
                return existingTask;

            var task = RunAndReleaseAsync(key, workFactory);
            _inFlight[key] = task;
            return task;
        }
    }

    private async Task<string> RunAndReleaseAsync(string key, Func<Task<string>> workFactory)
    {
        try
        {
            return await workFactory();
        }
        finally
        {
            lock (_lock)
            {
                _inFlight.Remove(key);
            }
        }
    }
}