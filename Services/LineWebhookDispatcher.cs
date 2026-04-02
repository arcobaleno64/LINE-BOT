using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public class LineWebhookDispatcher : ILineWebhookDispatcher
{
    private readonly ITextMessageHandler _textMessageHandler;
    private readonly IImageMessageHandler _imageMessageHandler;
    private readonly IFileMessageHandler _fileMessageHandler;
    private readonly LineReplyService _reply;
    private readonly IWebhookMetrics _metrics;
    private readonly ILogger<LineWebhookDispatcher> _logger;

    public LineWebhookDispatcher(
        ITextMessageHandler textMessageHandler,
        IImageMessageHandler imageMessageHandler,
        IFileMessageHandler fileMessageHandler,
        LineReplyService reply,
        IWebhookMetrics metrics,
        ILogger<LineWebhookDispatcher> logger)
    {
        _textMessageHandler = textMessageHandler;
        _imageMessageHandler = imageMessageHandler;
        _fileMessageHandler = fileMessageHandler;
        _reply = reply;
        _metrics = metrics;
        _logger = logger;
    }

    public Task DispatchAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
        return DispatchCoreAsync(evt, publicBaseUrl, ct);
    }

    private async Task DispatchCoreAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
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
}
