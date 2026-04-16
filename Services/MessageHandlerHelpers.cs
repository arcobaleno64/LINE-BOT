using System.Net;
using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

/// <summary>
/// Shared helper methods used by TextMessageHandler, ImageMessageHandler, and FileMessageHandler.
/// Eliminates duplication of throttle, 429 handling, user key derivation, and exception classification.
/// </summary>
internal static class MessageHandlerHelpers
{
    public static string BuildUserKey(LineEvent evt)
    {
        var sourceId = evt.Source?.GroupId ?? evt.Source?.RoomId ?? evt.Source?.UserId ?? "unknown";
        var userId = evt.Source?.UserId ?? "unknown";
        return $"{sourceId}:{userId}";
    }

    public static bool TryThrottle(
        UserRequestThrottleService throttle,
        IConfiguration config,
        string userKey,
        string messageType,
        out int retryAfter)
    {
        var cooldown = messageType switch
        {
            "image" => GetIntConfig(config, "App:UserThrottleSecondsImage", 8),
            "file" => GetIntConfig(config, "App:UserThrottleSecondsFile", 8),
            _ => GetIntConfig(config, "App:UserThrottleSecondsText", 3)
        };

        var throttleKey = $"{userKey}:{messageType}";
        return throttle.TryAcquire(throttleKey, cooldown, out retryAfter);
    }

    public static async Task<string?> TryGetAiReplyAsync(
        Func<Task<string>> aiCall,
        string replyToken,
        string handlerType,
        Ai429BackoffService aiBackoff,
        IConfiguration config,
        LineReplyService reply,
        IWebhookMetrics metrics,
        ILogger logger,
        WebhookLogContext logContext,
        CancellationToken ct)
    {
        if (!aiBackoff.TryPass(out var cooldownRemaining))
        {
            metrics.RecordAiBackoffRejected(handlerType);
            logger.LogDebug(
                "AI cooldown active. EventId={EventId} HandlerType={HandlerType} SourceType={SourceType} MessageType={MessageType} UserKeyFingerprint={UserKeyFingerprint} RetryAfterSeconds={RetryAfterSeconds}",
                logContext.EventId,
                logContext.HandlerType,
                logContext.SourceType,
                logContext.MessageType,
                logContext.UserKeyFingerprint,
                cooldownRemaining);
            await reply.ReplyTextAsync(replyToken, $"目前流量較高，請約 {cooldownRemaining} 秒後再試。", logContext, ct);
            return null;
        }

        try
        {
            return await aiCall();
        }
        catch (Exception ex) when (IsTooManyRequests(ex))
        {
            var isQuota = IsQuotaExhausted(ex);
            metrics.RecordAiTooManyRequests(handlerType);
            logger.LogDebug(
                "AI rate limit details. EventId={EventId} HandlerType={HandlerType} SourceType={SourceType} MessageType={MessageType} UserKeyFingerprint={UserKeyFingerprint} StatusCode={StatusCode} IsQuotaExhausted={IsQuotaExhausted}",
                logContext.EventId,
                logContext.HandlerType,
                logContext.SourceType,
                logContext.MessageType,
                logContext.UserKeyFingerprint,
                SensitiveLogHelpers.GetStatusCode(ex),
                isQuota);
            if (isQuota)
            {
                metrics.RecordAiQuotaExhausted(handlerType);
                var quotaCooldown = GetIntConfig(config, "App:AiQuotaCooldownSeconds", 300);
                aiBackoff.Trigger(quotaCooldown);
                logger.LogWarning(
                    "AI request hit quota exhaustion. EventId={EventId} HandlerType={HandlerType} SourceType={SourceType} MessageType={MessageType} UserKeyFingerprint={UserKeyFingerprint} IsQuotaExhausted={IsQuotaExhausted}",
                    logContext.EventId,
                    logContext.HandlerType,
                    logContext.SourceType,
                    logContext.MessageType,
                    logContext.UserKeyFingerprint,
                    true);
                await reply.ReplyTextAsync(replyToken, "今日 AI 配額已達上限，請稍後或明天再試。", logContext, ct);
                return null;
            }

            var cooldownSeconds = GetIntConfig(config, "App:Ai429CooldownSeconds", 12);
            aiBackoff.Trigger(cooldownSeconds);
            logger.LogWarning(
                "AI request hit 429. EventId={EventId} HandlerType={HandlerType} SourceType={SourceType} MessageType={MessageType} UserKeyFingerprint={UserKeyFingerprint} IsQuotaExhausted={IsQuotaExhausted}",
                logContext.EventId,
                logContext.HandlerType,
                logContext.SourceType,
                logContext.MessageType,
                logContext.UserKeyFingerprint,
                false);
            await reply.ReplyTextAsync(replyToken, "目前流量較高，稍後再試。", logContext, ct);
            return null;
        }
    }

    public static int GetIntConfig(IConfiguration config, string key, int fallback)
    {
        return int.TryParse(config[key], out var value)
            ? Math.Max(1, value)
            : fallback;
    }

    public static bool IsTooManyRequests(Exception ex)
    {
        if (ex is HttpRequestException httpEx && httpEx.StatusCode == HttpStatusCode.TooManyRequests)
            return true;

        return ex.InnerException is not null && IsTooManyRequests(ex.InnerException);
    }

    public static bool IsQuotaExhausted(Exception ex)
    {
        var message = CollectExceptionMessage(ex);
        if (string.IsNullOrWhiteSpace(message))
            return false;

        var normalized = message.ToLowerInvariant();
        return normalized.Contains("rpd")
            || normalized.Contains("daily")
            || normalized.Contains("quota")
            || normalized.Contains("resource_exhausted")
            || normalized.Contains("limit exceeded")
            || normalized.Contains("exceeded your current quota");
    }

    public static string CollectExceptionMessage(Exception ex)
    {
        var messages = new List<string>();
        var cursor = ex;
        while (cursor is not null)
        {
            if (!string.IsNullOrWhiteSpace(cursor.Message))
                messages.Add(cursor.Message);
            cursor = cursor.InnerException;
        }

        return string.Join("\n", messages);
    }
}
