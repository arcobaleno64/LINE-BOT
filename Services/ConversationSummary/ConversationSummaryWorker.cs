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
            await _history.RequeuePendingSummaryWorkAsync(stoppingToken);
            await foreach (var item in _queue.DequeueAllAsync(stoppingToken))
            {
                try
                {
                    var request = await _history.GetSummaryRequestAsync(item, stoppingToken);
                    if (request is null)
                        continue;

                    var summary = await _generator.GenerateAsync(request.ExistingSummary, request.PendingMessages, stoppingToken);
                    if (await _history.ApplySummarySuccessAsync(item, summary, stoppingToken))
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
                    if (string.IsNullOrWhiteSpace(item.UserKeyHash))
                        await _history.ApplySummaryFailureAsync(item, CancellationToken.None);
                    break;
                }
                catch (Exception ex)
                {
                    try
                    {
                        await _history.ApplySummaryFailureAsync(item, CancellationToken.None);
                    }
                    catch (Exception persistenceException)
                    {
                        _logger.LogError(
                            "Conversation summary state update failed. UserKeyFingerprint={UserKeyFingerprint} ExceptionType={ExceptionType}",
                            item.UserKeyFingerprint,
                            persistenceException.GetType().Name);
                    }

                    var statusCode = SensitiveLogHelpers.GetStatusCode(ex);
                    _logger.LogError(
                        "Conversation summary failed. UserKeyFingerprint={UserKeyFingerprint} PendingCount={PendingCount} MessageCount={MessageCount} StatusCode={StatusCode} ExceptionType={ExceptionType}",
                        item.UserKeyFingerprint,
                        item.PendingCount,
                        item.MessageCount,
                        statusCode,
                        ex.GetType().Name);
                }
                finally
                {
                    _queue.Complete(item);
                    if (!stoppingToken.IsCancellationRequested)
                    {
                        try
                        {
                            await _history.RequeuePendingSummaryWorkAsync(stoppingToken);
                        }
                        catch (Exception ex)
                        {
                            _logger.LogError(
                                "Pending conversation summary scan failed. ExceptionType={ExceptionType}",
                                ex.GetType().Name);
                        }
                    }
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
