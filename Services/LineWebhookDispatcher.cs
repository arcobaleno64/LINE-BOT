using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public class LineWebhookDispatcher : ILineWebhookDispatcher
{
    private readonly ITextMessageHandler _textMessageHandler;
    private readonly IImageMessageHandler _imageMessageHandler;
    private readonly IFileMessageHandler _fileMessageHandler;
    private readonly LineReplyService _reply;

    public LineWebhookDispatcher(
        ITextMessageHandler textMessageHandler,
        IImageMessageHandler imageMessageHandler,
        IFileMessageHandler fileMessageHandler,
        LineReplyService reply)
    {
        _textMessageHandler = textMessageHandler;
        _imageMessageHandler = imageMessageHandler;
        _fileMessageHandler = fileMessageHandler;
        _reply = reply;
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
            return;

        if (await _textMessageHandler.HandleAsync(evt, publicBaseUrl, ct))
            return;

        if (await _imageMessageHandler.HandleAsync(evt, publicBaseUrl, ct))
            return;

        if (await _fileMessageHandler.HandleAsync(evt, publicBaseUrl, ct))
            return;

        if (evt.Source?.Type == "user")
        {
            await _reply.ReplyTextAsync(evt.ReplyToken, "目前我支援文字、圖片與檔案（txt/md/csv/json/xml/log/pdf）。PDF 目前先支援文字型 PDF。", ct);
        }
    }
}
