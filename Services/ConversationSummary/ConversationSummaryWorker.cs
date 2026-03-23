namespace LineBotWebhook.Services;

public sealed class ConversationSummaryWorker : BackgroundService
{
    private readonly IConversationSummaryQueue _queue;
    private readonly ConversationHistoryService _history;
    private readonly IConversationSummaryGenerator _generator;
    private readonly ILogger<ConversationSummaryWorker> _logger;

    public ConversationSummaryWorker(
        IConversationSummaryQueue queue,
        ConversationHistoryService history,
        IConversationSummaryGenerator generator,
        ILogger<ConversationSummaryWorker> logger)
    {
        _queue = queue;
        _history = history;
        _generator = generator;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("Conversation summary worker started");

        try
        {
            await foreach (var item in _queue.DequeueAllAsync(stoppingToken))
            {
                if (!_history.TryGetSummaryRequest(item.UserKey, out var request) || request is null)
                    continue;

                try
                {
                    var summary = await _generator.GenerateAsync(request.ExistingSummary, request.PendingMessages, stoppingToken);
                    _history.ApplySummarySuccess(item.UserKey, summary);
                    _logger.LogInformation(
                        "Conversation summary completed. UserKeyFingerprint={UserKeyFingerprint} PendingCount={PendingCount} MessageCount={MessageCount}",
                        item.UserKeyFingerprint,
                        item.PendingCount,
                        item.MessageCount);
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    _history.ApplySummaryFailure(item.UserKey);
                    break;
                }
                catch (Exception ex)
                {
                    _history.ApplySummaryFailure(item.UserKey);
                    _logger.LogError(
                        ex,
                        "Conversation summary failed. UserKeyFingerprint={UserKeyFingerprint} PendingCount={PendingCount} MessageCount={MessageCount}",
                        item.UserKeyFingerprint,
                        item.PendingCount,
                        item.MessageCount);
                }
            }
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
        }
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("Conversation summary worker stopping");
        _queue.Complete();
        await base.StopAsync(cancellationToken);
    }
}
