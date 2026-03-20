using System.Diagnostics;
using System.Diagnostics.Metrics;

namespace LineBotWebhook.Services;

public sealed class WebhookMetrics : IWebhookMetrics
{
    private readonly Meter _meter = new("LineBotWebhook.Webhook", "1.0.0");
    private readonly Counter<long> _webhookRequestsTotal;
    private readonly Counter<long> _invalidSignatureTotal;
    private readonly Counter<long> _webhookEventsTotal;
    private readonly Counter<long> _messageHandledTotal;
    private readonly Counter<long> _throttleRejectedTotal;
    private readonly Counter<long> _aiBackoffRejectedTotal;
    private readonly Counter<long> _aiTooManyRequestsTotal;
    private readonly Counter<long> _aiQuotaExhaustedTotal;
    private readonly Counter<long> _cacheHitTotal;
    private readonly Counter<long> _mergeJoinedTotal;
    private readonly Counter<long> _queueEnqueuedTotal;
    private readonly Counter<long> _queueDroppedTotal;
    private readonly Counter<long> _queueDequeuedTotal;
    private readonly Counter<long> _replySentTotal;
    private readonly Counter<long> _replyFailedTotal;

    public WebhookMetrics()
    {
        _webhookRequestsTotal = _meter.CreateCounter<long>("linebot.webhook.requests.total");
        _invalidSignatureTotal = _meter.CreateCounter<long>("linebot.webhook.invalid_signature.total");
        _webhookEventsTotal = _meter.CreateCounter<long>("linebot.webhook.events.total");
        _messageHandledTotal = _meter.CreateCounter<long>("linebot.webhook.message_handled.total");
        _throttleRejectedTotal = _meter.CreateCounter<long>("linebot.webhook.throttle_rejected.total");
        _aiBackoffRejectedTotal = _meter.CreateCounter<long>("linebot.webhook.ai_backoff_rejected.total");
        _aiTooManyRequestsTotal = _meter.CreateCounter<long>("linebot.webhook.ai_429.total");
        _aiQuotaExhaustedTotal = _meter.CreateCounter<long>("linebot.webhook.ai_quota_exhausted.total");
        _cacheHitTotal = _meter.CreateCounter<long>("linebot.webhook.cache_hit.total");
        _mergeJoinedTotal = _meter.CreateCounter<long>("linebot.webhook.merge_joined.total");
        _queueEnqueuedTotal = _meter.CreateCounter<long>("linebot.webhook.queue_enqueued.total");
        _queueDroppedTotal = _meter.CreateCounter<long>("linebot.webhook.queue_dropped.total");
        _queueDequeuedTotal = _meter.CreateCounter<long>("linebot.webhook.queue_dequeued.total");
        _replySentTotal = _meter.CreateCounter<long>("linebot.webhook.reply_sent.total");
        _replyFailedTotal = _meter.CreateCounter<long>("linebot.webhook.reply_failed.total");
    }

    public void RecordWebhookRequest() => SafeRecord(() => _webhookRequestsTotal.Add(1));

    public void RecordInvalidSignature() => SafeRecord(() => _invalidSignatureTotal.Add(1));

    public void RecordWebhookEvents(int eventCount)
    {
        if (eventCount <= 0)
            return;

        SafeRecord(() => _webhookEventsTotal.Add(eventCount));
    }

    public void RecordMessageHandled(string messageType, string? sourceType = null)
    {
        SafeRecord(() =>
        {
            var tags = new TagList
            {
                { "message.type", NormalizeTag(messageType) },
                { "source.type", NormalizeTag(sourceType) }
            };
            _messageHandledTotal.Add(1, tags);
        });
    }

    public void RecordThrottleRejected(string handlerType, string messageType)
    {
        SafeRecord(() =>
        {
            var tags = new TagList
            {
                { "handler.type", NormalizeTag(handlerType) },
                { "message.type", NormalizeTag(messageType) }
            };
            _throttleRejectedTotal.Add(1, tags);
        });
    }

    public void RecordAiBackoffRejected(string handlerType)
    {
        SafeRecord(() =>
        {
            var tags = new TagList
            {
                { "handler.type", NormalizeTag(handlerType) }
            };
            _aiBackoffRejectedTotal.Add(1, tags);
        });
    }

    public void RecordAiTooManyRequests(string handlerType)
    {
        SafeRecord(() =>
        {
            var tags = new TagList
            {
                { "handler.type", NormalizeTag(handlerType) }
            };
            _aiTooManyRequestsTotal.Add(1, tags);
        });
    }

    public void RecordAiQuotaExhausted(string handlerType)
    {
        SafeRecord(() =>
        {
            var tags = new TagList
            {
                { "handler.type", NormalizeTag(handlerType) }
            };
            _aiQuotaExhaustedTotal.Add(1, tags);
        });
    }

    public void RecordCacheHit(string handlerType)
    {
        SafeRecord(() =>
        {
            var tags = new TagList
            {
                { "handler.type", NormalizeTag(handlerType) }
            };
            _cacheHitTotal.Add(1, tags);
        });
    }

    public void RecordMergeJoined(string handlerType)
    {
        SafeRecord(() =>
        {
            var tags = new TagList
            {
                { "handler.type", NormalizeTag(handlerType) }
            };
            _mergeJoinedTotal.Add(1, tags);
        });
    }

    public void RecordQueueEnqueued() => SafeRecord(() => _queueEnqueuedTotal.Add(1));

    public void RecordQueueDropped() => SafeRecord(() => _queueDroppedTotal.Add(1));

    public void RecordQueueDequeued() => SafeRecord(() => _queueDequeuedTotal.Add(1));

    public void RecordReplySent(int messageCount)
    {
        SafeRecord(() =>
        {
            var tags = new TagList
            {
                { "message.count", Math.Max(1, messageCount) }
            };
            _replySentTotal.Add(1, tags);
        });
    }

    public void RecordReplyFailed(int? statusCode = null)
    {
        SafeRecord(() =>
        {
            var tags = new TagList
            {
                { "status.code", statusCode?.ToString() ?? "unknown" }
            };
            _replyFailedTotal.Add(1, tags);
        });
    }

    private static void SafeRecord(Action action)
    {
        try
        {
            action();
        }
        catch
        {
        }
    }

    private static string NormalizeTag(string? value)
        => string.IsNullOrWhiteSpace(value) ? "unknown" : value;
}
