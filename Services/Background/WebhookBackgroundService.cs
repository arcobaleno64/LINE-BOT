namespace LineBotWebhook.Services;

public sealed class WebhookBackgroundService : BackgroundService
{
    // LINE replyToken 有效期約 1 分鐘；保留 30 秒給下游 AI / LINE Reply 呼叫，
    // 超過此年齡入站之事件已難以在 60 秒窗口內完成回覆，直接丟棄以避免錯誤回覆。
    internal static readonly TimeSpan MaxQueueAge = TimeSpan.FromSeconds(30);
    // 單一 dispatch 之硬性截止時間：避免慢 AI／HTTP 呼叫阻塞唯一 reader，
    // 並確保總用時（queue age + dispatch）落在 60 秒 replyToken 視窗內。
    internal static readonly TimeSpan DispatchTimeout = TimeSpan.FromSeconds(25);

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
                var age = DateTimeOffset.UtcNow - item.EnqueuedAt;
                if (age > MaxQueueAge)
                {
                    _logger.LogWarning(
                        "Dropping stale webhook event past replyToken validity. EventId={EventId} SourceType={SourceType} MessageType={MessageType} AgeSeconds={AgeSeconds}",
                        item.EventId,
                        item.SourceType,
                        item.MessageType,
                        (int)age.TotalSeconds);
                    continue;
                }

                using var dispatchTimeout = new CancellationTokenSource(DispatchTimeout);
                using var linked = CancellationTokenSource.CreateLinkedTokenSource(stoppingToken, dispatchTimeout.Token);
                try
                {
                    await _dispatcher.DispatchAsync(item.Event, item.PublicBaseUrl, linked.Token);
                }
                catch (OperationCanceledException) when (dispatchTimeout.IsCancellationRequested && !stoppingToken.IsCancellationRequested)
                {
                    _logger.LogWarning(
                        "Dispatch exceeded per-event deadline and was cancelled. EventId={EventId} SourceType={SourceType} MessageType={MessageType} DeadlineSeconds={DeadlineSeconds}",
                        item.EventId,
                        item.SourceType,
                        item.MessageType,
                        (int)DispatchTimeout.TotalSeconds);
                    continue;
                }
                catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
                {
                    break;
                }
                catch (Exception ex)
                {
                    var statusCode = SensitiveLogHelpers.GetStatusCode(ex);
                    _logger.LogError(
                        "Error handling event {EventId} from {SourceType} with message type {MessageType}. StatusCode={StatusCode} ExceptionType={ExceptionType}",
                        item.EventId,
                        item.SourceType,
                        item.MessageType,
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
        _logger.LogInformation("Webhook background worker stopping");
        _queue.Complete();
        await base.StopAsync(cancellationToken);
    }
}
