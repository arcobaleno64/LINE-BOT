namespace LineBotWebhook.Services;

public sealed class WebhookReadinessService(
    Ai429BackoffService aiBackoff,
    ConversationHistoryService conversationHistory,
    IWebhookBackgroundQueue backgroundQueue) : IWebhookReadinessService
{
    private readonly Ai429BackoffService _aiBackoff = aiBackoff;
    private readonly ConversationHistoryService _conversationHistory = conversationHistory;
    private readonly IWebhookBackgroundQueue _backgroundQueue = backgroundQueue;
    private volatile bool _started;

    public void MarkStarted()
    {
        _started = true;
    }

    public WebhookReadinessSnapshot GetSnapshot()
    {
        var coreServicesReady = _conversationHistory.GetHistory("__readiness__") is not null;
        var aiTrafficReady = _aiBackoff.TryPass(out var retryAfterSeconds);
        var cooldownActive = !aiTrafficReady;
        var queueSnapshot = _backgroundQueue.GetSnapshot();
        var queueSaturated = queueSnapshot.QueueDepth >= queueSnapshot.QueueCapacity;
        var canAcceptWebhookTraffic = queueSnapshot.QueueDepth < queueSnapshot.QueueCapacity;
        var ready = _started && coreServicesReady && !queueSaturated;
        var status = (!_started || !coreServicesReady)
            ? "starting"
            : ready
                ? "ready"
                : "backpressure";

        return new WebhookReadinessSnapshot(
            IsReady: ready,
            Status: status,
            AppStarted: _started,
            CoreServicesReady: coreServicesReady,
            AiCooldownActive: cooldownActive,
            AiRetryAfterSeconds: cooldownActive ? retryAfterSeconds : 0,
            CanAcceptAiTraffic: aiTrafficReady,
            QueueDepth: queueSnapshot.QueueDepth,
            QueueCapacity: queueSnapshot.QueueCapacity,
            QueueSaturated: queueSaturated,
            CanAcceptWebhookTraffic: canAcceptWebhookTraffic);
    }
}

public sealed record WebhookReadinessSnapshot(
    bool IsReady,
    string Status,
    bool AppStarted,
    bool CoreServicesReady,
    bool AiCooldownActive,
    int AiRetryAfterSeconds,
    bool CanAcceptAiTraffic,
    int QueueDepth,
    int QueueCapacity,
    bool QueueSaturated,
    bool CanAcceptWebhookTraffic);
