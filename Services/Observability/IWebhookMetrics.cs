namespace LineBotWebhook.Services;

public interface IWebhookMetrics
{
    void RecordWebhookRequest();
    void RecordInvalidSignature();
    void RecordWebhookEvents(int eventCount);
    void RecordMessageHandled(string messageType, string? sourceType = null);
    void RecordThrottleRejected(string handlerType, string messageType);
    void RecordAiBackoffRejected(string handlerType);
    void RecordAiTooManyRequests(string handlerType);
    void RecordAiQuotaExhausted(string handlerType);
    void RecordCacheHit(string handlerType);
    void RecordMergeJoined(string handlerType);
    void RecordReplySent(int messageCount);
    void RecordReplyFailed(int? statusCode = null);
}
