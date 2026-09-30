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
                if (!_history.TryGetSummaryRequest(item, out var request) || request is null)
                    continue;

                try
                {
                    var summary = await _generator.GenerateAsync(request.ExistingSummary, request.PendingMessages, stoppingToken);
                    if (_history.ApplySummarySuccess(request, summary))
                    {
                        _logger.LogInformation(
                            "Conversation summary completed. UserKeyFingerprint={UserKeyFingerprint} PendingCount={PendingCount} MessageCount={MessageCount}",
                            item.UserKeyFingerprint,
                            item.PendingCount,
                            item.MessageCount);
                    }
                    else
                    {
                        _logger.LogDebug(
                            "Discarded stale conversation summary. UserKeyFingerprint={UserKeyFingerprint} PendingCount={PendingCount}",
                            item.UserKeyFingerprint,
                            item.PendingCount);
                    }
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    _history.ApplySummaryFailure(request);
                    break;
                }
                catch (Exception ex)
                {
                    _history.ApplySummaryFailure(request);
                    var statusCode = SensitiveLogHelpers.GetStatusCode(ex);
                    _logger.LogError(
                        "Conversation summary failed. UserKeyFingerprint={UserKeyFingerprint} PendingCount={PendingCount} MessageCount={MessageCount} StatusCode={StatusCode} ExceptionType={ExceptionType}",
                        item.UserKeyFingerprint,
                        item.PendingCount,
                        item.MessageCount,
                        statusCode,
                        ex.GetType().Name);
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
