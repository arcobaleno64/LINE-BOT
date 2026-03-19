using System.Net;
using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public class ImageMessageHandler : IImageMessageHandler
{
    private const string HandlerType = "image";

    private readonly IConfiguration _config;
    private readonly IAiService _ai;
    private readonly LineReplyService _reply;
    private readonly LineContentService _content;
    private readonly UserRequestThrottleService _throttle;
    private readonly Ai429BackoffService _aiBackoff;
    private readonly IWebhookMetrics _metrics;
    private readonly ILogger<ImageMessageHandler> _logger;

    public ImageMessageHandler(
        IConfiguration config,
        IAiService ai,
        LineReplyService reply,
        LineContentService content,
        UserRequestThrottleService throttle,
        Ai429BackoffService aiBackoff,
        IWebhookMetrics metrics,
        ILogger<ImageMessageHandler> logger)
    {
        _config = config;
        _ai = ai;
        _reply = reply;
        _content = content;
        _throttle = throttle;
        _aiBackoff = aiBackoff;
        _metrics = metrics;
        _logger = logger;
    }

    public async Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
        if (evt.Message?.Type != "image")
            return false;

        if (evt.Source?.Type is "group" or "room")
            return true;

        var userKey = BuildUserKey(evt);
        if (!TryThrottle(userKey, evt.Message.Type, out var retryAfter))
        {
            _metrics.RecordThrottleRejected(HandlerType, evt.Message.Type);
            _logger.LogInformation(
                "Throttle rejected {HandlerType} request for {UserKey}. MessageType={MessageType} RetryAfterSeconds={RetryAfterSeconds}",
                HandlerType,
                userKey,
                evt.Message.Type,
                retryAfter);
            await _reply.ReplyTextAsync(evt.ReplyToken!, $"訊息有點密集，請在 {retryAfter} 秒後再試。", ct);
            return true;
        }

        _logger.LogInformation("Processing {HandlerType} message from {UserId}", HandlerType, evt.Source?.UserId ?? "unknown");
        var (bytes, mimeType) = await _content.DownloadMessageContentAsync(evt.Message.Id, ct);
        var aiReply = await TryGetAiReplyAsync(
            () => _ai.GetReplyFromImageAsync(bytes, mimeType, "請幫我分析這張圖片重點。", userKey, ct),
            evt.ReplyToken!,
            userKey,
            ct);
        if (aiReply is null)
            return true;

        await _reply.ReplyTextAsync(evt.ReplyToken!, aiReply, ct);
        return true;
    }

    private async Task<string?> TryGetAiReplyAsync(Func<Task<string>> aiCall, string replyToken, string userKey, CancellationToken ct)
    {
        if (!_aiBackoff.TryPass(out var cooldownRemaining))
        {
            _metrics.RecordAiBackoffRejected(HandlerType);
            _logger.LogInformation(
                "AI cooldown active for {HandlerType} request by {UserKey}. RetryAfterSeconds={RetryAfterSeconds}",
                HandlerType,
                userKey,
                cooldownRemaining);
            await _reply.ReplyTextAsync(replyToken, $"目前流量較高，請約 {cooldownRemaining} 秒後再試。", ct);
            return null;
        }

        try
        {
            return await aiCall();
        }
        catch (Exception ex) when (IsTooManyRequests(ex))
        {
            _metrics.RecordAiTooManyRequests(HandlerType);
            if (IsQuotaExhausted(ex))
            {
                _metrics.RecordAiQuotaExhausted(HandlerType);
                var quotaCooldown = GetIntConfig("App:AiQuotaCooldownSeconds", 300);
                _aiBackoff.Trigger(quotaCooldown);
                _logger.LogWarning(ex, "AI quota exhausted in {HandlerType} handler for {UserKey}", HandlerType, userKey);
                await _reply.ReplyTextAsync(replyToken, "今日 AI 配額已達上限，請稍後或明天再試。", ct);
                return null;
            }

            var cooldownSeconds = GetIntConfig("App:Ai429CooldownSeconds", 12);
            _aiBackoff.Trigger(cooldownSeconds);
            _logger.LogWarning(ex, "AI 429 in {HandlerType} handler for {UserKey}", HandlerType, userKey);
            await _reply.ReplyTextAsync(replyToken, "目前流量較高，稍後再試。", ct);
            return null;
        }
    }

    private bool TryThrottle(string userKey, string messageType, out int retryAfter)
    {
        var cooldown = messageType switch
        {
            "image" => GetIntConfig("App:UserThrottleSecondsImage", 8),
            "file" => GetIntConfig("App:UserThrottleSecondsFile", 8),
            _ => GetIntConfig("App:UserThrottleSecondsText", 3)
        };

        var throttleKey = $"{userKey}:{messageType}";
        return _throttle.TryAcquire(throttleKey, cooldown, out retryAfter);
    }

    private int GetIntConfig(string key, int fallback)
    {
        return int.TryParse(_config[key], out var value)
            ? Math.Max(1, value)
            : fallback;
    }

    private static bool IsTooManyRequests(Exception ex)
    {
        if (ex is HttpRequestException httpEx && httpEx.StatusCode == HttpStatusCode.TooManyRequests)
            return true;

        return ex.InnerException is not null && IsTooManyRequests(ex.InnerException);
    }

    private static bool IsQuotaExhausted(Exception ex)
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

    private static string CollectExceptionMessage(Exception ex)
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

    private static string BuildUserKey(LineEvent evt)
    {
        var sourceId = evt.Source?.GroupId ?? evt.Source?.RoomId ?? evt.Source?.UserId ?? "unknown";
        var userId = evt.Source?.UserId ?? "unknown";
        return $"{sourceId}:{userId}";
    }
}
