namespace LineBotWebhook.Services;

public class InFlightRequestMergeService
{
    private readonly object _lock = new();
    private readonly Dictionary<string, Task<string>> _inFlight = new(StringComparer.Ordinal);

    public MergeExecution JoinOrRun(string key, Func<Task<string>> workFactory)
    {
        lock (_lock)
        {
            if (_inFlight.TryGetValue(key, out var existingTask))
                return new MergeExecution(existingTask, true);

            var task = RunAndReleaseAsync(key, workFactory);
            _inFlight[key] = task;
            return new MergeExecution(task, false);
        }
    }

    public Task<string> RunAsync(string key, Func<Task<string>> workFactory)
    {
        return JoinOrRun(key, workFactory).Task;
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

    public readonly record struct MergeExecution(Task<string> Task, bool JoinedExisting);
}