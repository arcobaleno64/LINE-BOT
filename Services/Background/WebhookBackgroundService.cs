namespace LineBotWebhook.Services;

public sealed class WebhookBackgroundService : BackgroundService
{
    private readonly IWebhookBackgroundQueue _queue;
    private readonly ILineWebhookDispatcher _dispatcher;
    private readonly ILogger<WebhookBackgroundService> _logger;

    public WebhookBackgroundService(
        IWebhookBackgroundQueue queue,
        ILineWebhookDispatcher dispatcher,
        ILogger<WebhookBackgroundService> logger)
    {
        _queue = queue;
        _dispatcher = dispatcher;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("Webhook background worker started");

        try
        {
            await foreach (var item in _queue.DequeueAllAsync(stoppingToken))
            {
                try
                {
                    await _dispatcher.DispatchAsync(item.Event, item.PublicBaseUrl, stoppingToken);
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    break;
                }
                catch (Exception ex)
                {
                    _logger.LogError(
                        ex,
                        "Error handling event {EventId} from {SourceType} with message type {MessageType}",
                        item.EventId,
                        item.SourceType,
                        item.MessageType);
                }
            }
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
        {
        }
    }

    public override async Task StopAsync(CancellationToken cancellationToken)
    {
        _logger.LogInformation("Webhook background worker stopping");
        _queue.Complete();
        await base.StopAsync(cancellationToken);
    }
}
