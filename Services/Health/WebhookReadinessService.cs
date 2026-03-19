namespace LineBotWebhook.Services;

public sealed class WebhookReadinessService(
    Ai429BackoffService aiBackoff,
    ConversationHistoryService conversationHistory) : IWebhookReadinessService
{
    private readonly Ai429BackoffService _aiBackoff = aiBackoff;
    private readonly ConversationHistoryService _conversationHistory = conversationHistory;
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
        var ready = _started && coreServicesReady;

        return new WebhookReadinessSnapshot(
            IsReady: ready,
            Status: ready ? "ready" : "starting",
            AppStarted: _started,
            CoreServicesReady: coreServicesReady,
            AiCooldownActive: cooldownActive,
            AiRetryAfterSeconds: cooldownActive ? retryAfterSeconds : 0,
            CanAcceptAiTraffic: aiTrafficReady);
    }
}

public sealed record WebhookReadinessSnapshot(
    bool IsReady,
    string Status,
    bool AppStarted,
    bool CoreServicesReady,
    bool AiCooldownActive,
    int AiRetryAfterSeconds,
    bool CanAcceptAiTraffic);
