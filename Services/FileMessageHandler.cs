using System.Net;
using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public class FileMessageHandler : IFileMessageHandler
{
    private const string HandlerType = "file";

    private readonly IConfiguration _config;
    private readonly IAiService _ai;
    private readonly LineReplyService _reply;
    private readonly LineContentService _content;
    private readonly GeneratedFileService _files;
    private readonly UserRequestThrottleService _throttle;
    private readonly Ai429BackoffService _aiBackoff;
    private readonly IWebhookMetrics _metrics;
    private readonly ILogger<FileMessageHandler> _logger;

    public FileMessageHandler(
        IConfiguration config,
        IAiService ai,
        LineReplyService reply,
        LineContentService content,
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
        _files = files;
        _throttle = throttle;
        _aiBackoff = aiBackoff;
        _metrics = metrics;
        _logger = logger;
    }

    public async Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
        if (evt.Message?.Type != "file")
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
        var fileName = evt.Message.FileName ?? "uploaded-file";

        string extractedText;
        try
        {
            extractedText = _content.ExtractTextFromFile(bytes, fileName, mimeType);
        }
        catch (NotSupportedException ex)
        {
            await _reply.ReplyTextAsync(evt.ReplyToken!, ex.Message, ct);
            return true;
        }

        var aiReply = await TryGetAiReplyAsync(
            () => _ai.GetReplyFromDocumentAsync(fileName, mimeType, extractedText, "請幫我整理重點、關鍵結論與待辦事項。", userKey, ct),
            evt.ReplyToken!,
            userKey,
            ct);
        if (aiReply is null)
            return true;

        var downloadToken = _files.SaveTextFile(
            Path.GetFileNameWithoutExtension(fileName) + "-整理摘要.md",
            BuildSummaryFileContent(fileName, mimeType, aiReply));
        var downloadUrl = $"{publicBaseUrl}/downloads/{downloadToken}";

        var replyText = $"""
已完成整理：{fileName}

{aiReply}

下載整理檔：
{downloadUrl}

提醒：下載連結會保留約 24 小時，重新部署後可能失效。
""";

        await _reply.ReplyTextAsync(evt.ReplyToken!, replyText, ct);
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
