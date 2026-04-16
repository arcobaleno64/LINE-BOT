using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public class FileMessageHandler : IFileMessageHandler
{
    private const string HandlerType = "file";
    private const string DefaultDocumentSummaryPrompt = "請幫我整理重點、關鍵結論與待辦事項。";

    private readonly IConfiguration _config;
    private readonly IAiService _ai;
    private readonly LineReplyService _reply;
    private readonly LineContentService _content;
    private readonly DocumentGroundingService _documents;
    private readonly GeneratedFileService _files;
    private readonly UserRequestThrottleService _throttle;
    private readonly Ai429BackoffService _aiBackoff;
    private readonly IWebhookMetrics _metrics;
    private readonly ILogger<FileMessageHandler> _logger;
    private readonly int _flexBodyMaxLength;

    public FileMessageHandler(
        IConfiguration config,
        IAiService ai,
        LineReplyService reply,
        LineContentService content,
        DocumentGroundingService documents,
        GeneratedFileService files,
        UserRequestThrottleService throttle,
        Ai429BackoffService aiBackoff,
        IWebhookMetrics metrics,
        ILogger<FileMessageHandler> logger)
    {
        _config = config;
        _ai = ai;
        _reply = reply;
        _content = content;
        _documents = documents;
        _files = files;
        _throttle = throttle;
        _aiBackoff = aiBackoff;
        _metrics = metrics;
        _logger = logger;
        _flexBodyMaxLength = MessageHandlerHelpers.GetIntConfig(config, "App:FlexBodyMaxLength", 2000);
    }

    public async Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
        if (evt.Message?.Type != "file")
            return false;

        if (evt.Source?.Type is "group" or "room")
        {
            var allowGroupFiles = MessageHandlerHelpers.GetBoolConfig(_config, "App:AllowGroupFileHandling", defaultValue: true);
            if (!allowGroupFiles)
                return true;  // 功能關閉時靜默略過
        }

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
        var fileName = evt.Message.FileName ?? "uploaded-file";

        string extractedText;
        try
        {
            extractedText = _content.ExtractTextFromFile(bytes, fileName, mimeType);
        }
        catch (NotSupportedException ex)
        {
            await _reply.ReplyTextAsync(evt.ReplyToken!, ex.Message, logContext, ct);
            return true;
        }

        var userPrompt = ResolveDocumentPrompt(evt);
        var preparedDocument = await _documents.PrepareAsync(fileName, mimeType, extractedText, userPrompt, ct);

        var documentPrompt = $"{preparedDocument.GroundedPrompt}\n\n以下是文件片段：\n{preparedDocument.SelectedContext}";

        var aiReply = await MessageHandlerHelpers.TryGetAiReplyAsync(
            () => _ai.GetReplyAsync(documentPrompt, userKey, ct),
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

        var downloadToken = _files.SaveTextFile(
            Path.GetFileNameWithoutExtension(fileName) + "-整理摘要.md",
            BuildSummaryFileContent(fileName, mimeType, aiReply));
        var downloadUrl = $"{publicBaseUrl}/downloads/{downloadToken}";

        var sanitizedReply = LineReplyTextFormatter.SanitizeForLine(aiReply);

        if (sanitizedReply.Length <= _flexBodyMaxLength)
        {
            var bubble = FlexMessageBuilder.BuildDocumentSummaryBubble(fileName, sanitizedReply, downloadUrl);
            var altText = FlexMessageBuilder.BuildAltText(sanitizedReply);
            await _reply.ReplyFlexAsync(evt.ReplyToken!, altText, bubble, logContext, ct);
        }
        else
        {
            var replyText = $"""
已完成整理：{fileName}

{sanitizedReply}

下載整理檔：
{downloadUrl}

提醒：下載連結會保留約 24 小時，重新部署後可能失效。
""";
            await _reply.ReplyAiTextAsync(evt.ReplyToken!, replyText, logContext, ct);
        }

        return true;
    }

    private static string ResolveDocumentPrompt(LineEvent evt)
    {
        var candidate = evt.Message?.Text?.Trim();
        return string.IsNullOrWhiteSpace(candidate)
            ? DefaultDocumentSummaryPrompt
            : candidate;
    }

    private static string BuildSummaryFileContent(string fileName, string mimeType, string summary)
    {
        return $"""
# 檔案整理摘要

- 原始檔名：{fileName}
- 類型：{mimeType}
- 產生時間（UTC）：{DateTime.UtcNow:yyyy-MM-dd HH:mm:ss}

## 整理結果

{summary}
""";
    }
}
