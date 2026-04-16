using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public class LineWebhookDispatcher : ILineWebhookDispatcher
{
    private readonly ITextMessageHandler _textMessageHandler;
    private readonly IImageMessageHandler _imageMessageHandler;
    private readonly IFileMessageHandler _fileMessageHandler;
    private readonly LineReplyService _reply;
    private readonly LoadingIndicatorService _loading;
    private readonly IWebhookMetrics _metrics;
    private readonly ILogger<LineWebhookDispatcher> _logger;

    public LineWebhookDispatcher(
        ITextMessageHandler textMessageHandler,
        IImageMessageHandler imageMessageHandler,
        IFileMessageHandler fileMessageHandler,
        LineReplyService reply,
        LoadingIndicatorService loading,
        IWebhookMetrics metrics,
        ILogger<LineWebhookDispatcher> logger)
    {
        _textMessageHandler = textMessageHandler;
        _imageMessageHandler = imageMessageHandler;
        _fileMessageHandler = fileMessageHandler;
        _reply = reply;
        _loading = loading;
        _metrics = metrics;
        _logger = logger;
    }

    public Task DispatchAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
        return DispatchCoreAsync(evt, publicBaseUrl, ct);
    }

    private async Task DispatchCoreAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
        if (evt.Type == "postback")
        {
            await HandlePostbackAsync(evt, ct);
            return;
        }

        if (evt.Type != "message" || evt.Message is null)
            return;

        if (string.IsNullOrEmpty(evt.ReplyToken))
        {
            _logger.LogWarning(
                "Skipped reply because reply token is missing. EventId={EventId} MessageType={MessageType} SourceType={SourceType}",
                evt.WebhookEventId,
                evt.Message.Type,
                evt.Source?.Type ?? "unknown");
            return;
        }

        // 顯示讀取動畫（僅對已知需處理的訊息類型，fire-and-forget）
        if (evt.Message.Type is "text" or "image" or "file")
            _ = _loading.ShowAsync(evt, ct);

        if (await _textMessageHandler.HandleAsync(evt, publicBaseUrl, ct))
        {
            _metrics.RecordMessageHandled("text", evt.Source?.Type);
            _logger.LogInformation(
                "Dispatched event {EventId} to {HandlerType} for message type {MessageType} from {SourceType}",
                evt.WebhookEventId,
                "text",
                evt.Message.Type,
                evt.Source?.Type ?? "unknown");
            return;
        }

        if (await _imageMessageHandler.HandleAsync(evt, publicBaseUrl, ct))
        {
            _metrics.RecordMessageHandled("image", evt.Source?.Type);
            _logger.LogInformation(
                "Dispatched event {EventId} to {HandlerType} for message type {MessageType} from {SourceType}",
                evt.WebhookEventId,
                "image",
                evt.Message.Type,
                evt.Source?.Type ?? "unknown");
            return;
        }

        if (await _fileMessageHandler.HandleAsync(evt, publicBaseUrl, ct))
        {
            _metrics.RecordMessageHandled("file", evt.Source?.Type);
            _logger.LogInformation(
                "Dispatched event {EventId} to {HandlerType} for message type {MessageType} from {SourceType}",
                evt.WebhookEventId,
                "file",
                evt.Message.Type,
                evt.Source?.Type ?? "unknown");
            return;
        }

        _metrics.RecordMessageHandled("unsupported", evt.Source?.Type);

        if (evt.Source?.Type == "user")
        {
            var logContext = WebhookLogContext.FromEvent(evt, handlerType: "unsupported");
            _logger.LogDebug(
                "Unsupported fallback for event {EventId} with message type {MessageType} from {SourceType}",
                logContext.EventId,
                logContext.MessageType,
                logContext.SourceType);
            await _reply.ReplyTextAsync(
                evt.ReplyToken,
                "目前我支援文字、圖片與檔案（txt/md/csv/json/xml/log/pdf）。PDF 目前先支援文字型 PDF。",
                logContext,
                ct);
            return;
        }

        _logger.LogDebug(
            "Ignored unsupported event {EventId} with message type {MessageType} from {SourceType}",
            evt.WebhookEventId,
            evt.Message.Type,
            evt.Source?.Type ?? "unknown");
    }

    private async Task HandlePostbackAsync(LineEvent evt, CancellationToken ct)
    {
        if (string.IsNullOrEmpty(evt.ReplyToken) || evt.Postback is null)
        {
            _logger.LogDebug(
                "Ignored postback with missing token or data. EventId={EventId}",
                evt.WebhookEventId);
            return;
        }

        _metrics.RecordMessageHandled("postback", evt.Source?.Type);

        var data = evt.Postback.Data;
        var logContext = WebhookLogContext.FromEvent(evt, handlerType: "postback");

        _logger.LogInformation(
            "Handling postback event. EventId={EventId} SourceType={SourceType} DataPrefix={DataPrefix}",
            evt.WebhookEventId,
            evt.Source?.Type ?? "unknown",
            data.Length > 30 ? data[..30] : data);

        var parameters = ParsePostbackData(data);

        var action = parameters.GetValueOrDefault("action", "");
        switch (action)
        {
            default:
                _logger.LogDebug(
                    "Unhandled postback action. EventId={EventId} Action={Action}",
                    evt.WebhookEventId,
                    action);
                break;
        }
    }

    internal static Dictionary<string, string> ParsePostbackData(string data)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(data))
            return result;

        foreach (var pair in data.Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var eqIndex = pair.IndexOf('=');
            if (eqIndex > 0)
            {
                var key = Uri.UnescapeDataString(pair[..eqIndex]);
                var value = Uri.UnescapeDataString(pair[(eqIndex + 1)..]);
                result[key] = value;
            }
        }

        return result;
    }
}
