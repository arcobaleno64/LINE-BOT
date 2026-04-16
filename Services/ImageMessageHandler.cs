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

        var userKey = MessageHandlerHelpers.BuildUserKey(evt);
        var logContext = WebhookLogContext.FromEvent(evt, HandlerType, userKey);
        if (!MessageHandlerHelpers.TryThrottle(_throttle, _config, userKey, evt.Message.Type, out var retryAfter))
        {
            _metrics.RecordThrottleRejected(HandlerType, evt.Message.Type);
            _logger.LogInformation(
                "Throttle rejected request. EventId={EventId} HandlerType={HandlerType} SourceType={SourceType} MessageType={MessageType} UserKeyFingerprint={UserKeyFingerprint} RetryAfterSeconds={RetryAfterSeconds}",
                logContext.EventId,
                logContext.HandlerType,
                logContext.SourceType,
                logContext.MessageType,
                logContext.UserKeyFingerprint,
                retryAfter);
            await _reply.ReplyTextAsync(evt.ReplyToken!, $"訊息有點密集，請在 {retryAfter} 秒後再試。", logContext, ct);
            return true;
        }

        var (bytes, mimeType) = await _content.DownloadMessageContentAsync(evt.Message.Id, ct);
        var aiReply = await MessageHandlerHelpers.TryGetAiReplyAsync(
            () => _ai.GetReplyFromImageAsync(bytes, mimeType, "請幫我分析這張圖片重點。", userKey, ct),
            evt.ReplyToken!,
            HandlerType,
            _aiBackoff,
            _config,
            _reply,
            _metrics,
            _logger,
            logContext,
            ct);
        if (aiReply is null)
            return true;

        await _reply.ReplyAiTextAsync(evt.ReplyToken!, aiReply, logContext, ct);
        return true;
    }
}
