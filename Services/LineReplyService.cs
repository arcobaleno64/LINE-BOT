using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace LineBotWebhook.Services;

/// <summary>透過 LINE Messaging API 回覆訊息</summary>
public class LineReplyService
{
    private const string ReplyUrl = "https://api.line.me/v2/bot/message/reply";
    private const int MaxLineTextLength = 5000;
    private const int MaxLineMessagesPerReply = 5;

    private readonly HttpClient _http;
    private readonly string _accessToken;
    private readonly IWebhookMetrics _metrics;
    private readonly ILogger<LineReplyService> _logger;

    public LineReplyService(HttpClient http, IConfiguration config, IWebhookMetrics metrics, ILogger<LineReplyService> logger)
    {
        _http = http;
        _accessToken = config["Line:ChannelAccessToken"]
            ?? throw new InvalidOperationException("Missing Line:ChannelAccessToken");
        _metrics = metrics;
        _logger = logger;
    }

    /// <summary>回覆文字訊息</summary>
    public async Task ReplyTextAsync(string replyToken, string text, CancellationToken ct = default)
    {
        await ReplyTextAsync(replyToken, text, quickReplies: null, logContext: null, ct);
    }

    /// <summary>回覆 AI 文字訊息（會套用 LINE 純文字保護）</summary>
    public Task ReplyAiTextAsync(string replyToken, string text, CancellationToken ct = default)
    {
        return ReplyAiTextAsync(replyToken, text, quickReplies: null, logContext: null, ct);
    }

    /// <summary>回覆 AI 文字訊息並附帶最小排障關聯欄位（會套用 LINE 純文字保護）</summary>
    public Task ReplyAiTextAsync(string replyToken, string text, WebhookLogContext? logContext, CancellationToken ct = default)
    {
        return ReplyAiTextAsync(replyToken, text, quickReplies: null, logContext, ct);
    }

    /// <summary>回覆 AI 文字訊息並附 quick replies（會套用 LINE 純文字保護）</summary>
    public Task ReplyAiTextAsync(string replyToken, string text, IReadOnlyList<string>? quickReplies, WebhookLogContext? logContext, CancellationToken ct = default)
    {
        var lineSafeText = LineReplyTextFormatter.SanitizeForLine(text);
        return ReplyTextAsync(replyToken, lineSafeText, quickReplies, logContext, ct);
    }

    /// <summary>回覆文字訊息並附帶最小排障關聯欄位</summary>
    public async Task ReplyTextAsync(string replyToken, string text, WebhookLogContext? logContext, CancellationToken ct = default)
    {
        await ReplyTextAsync(replyToken, text, quickReplies: null, logContext, ct);
    }

    public async Task ReplyTextAsync(string replyToken, string text, IReadOnlyList<string>? quickReplies, WebhookLogContext? logContext, CancellationToken ct = default)
    {
        var chunks = SplitIntoLineMessages(text);
        var replyFailedRecorded = false;
        var quickReplyItems = BuildQuickReplyItems(quickReplies);

        var payload = new
        {
            replyToken,
            messages = chunks.Select((x, index) => BuildTextMessage(x, index == chunks.Count - 1 ? quickReplyItems : null)).ToArray()
        };

        var request = new HttpRequestMessage(HttpMethod.Post, ReplyUrl)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _accessToken);

        try
        {
            using var response = await _http.SendAsync(request, ct);
            if (!response.IsSuccessStatusCode)
            {
                replyFailedRecorded = true;
                _metrics.RecordReplyFailed((int)response.StatusCode);
                _logger.LogError(
                    "Failed to send LINE reply. EventId={EventId} HandlerType={HandlerType} MessageType={MessageType} SourceType={SourceType} StatusCode={StatusCode} MessageCount={MessageCount}",
                    logContext?.EventId,
                    logContext?.HandlerType,
                    logContext?.MessageType,
                    logContext?.SourceType,
                    (int)response.StatusCode,
                    chunks.Count);
                response.EnsureSuccessStatusCode();
            }

            _metrics.RecordReplySent(chunks.Count);
            _logger.LogInformation(
                "Sent LINE reply. EventId={EventId} HandlerType={HandlerType} MessageType={MessageType} SourceType={SourceType} MessageCount={MessageCount}",
                logContext?.EventId,
                logContext?.HandlerType,
                logContext?.MessageType,
                logContext?.SourceType,
                chunks.Count);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            if (!replyFailedRecorded)
            {
                var statusCode = ex is HttpRequestException httpEx && httpEx.StatusCode is HttpStatusCode code
                    ? (int?)code
                    : null;
                _metrics.RecordReplyFailed(statusCode);
                _logger.LogError(
                    ex,
                    "Failed to send LINE reply. EventId={EventId} HandlerType={HandlerType} MessageType={MessageType} SourceType={SourceType} StatusCode={StatusCode} MessageCount={MessageCount}",
                    logContext?.EventId,
                    logContext?.HandlerType,
                    logContext?.MessageType,
                    logContext?.SourceType,
                    statusCode,
                    chunks.Count);
            }

            throw;
        }
    }

    private static object BuildTextMessage(string text, IReadOnlyList<object>? quickReplyItems)
    {
        if (quickReplyItems is { Count: > 0 })
        {
            return new
            {
                type = "text",
                text,
                quickReply = new
                {
                    items = quickReplyItems
                }
            };
        }

        return new
        {
            type = "text",
            text
        };
    }

    private static IReadOnlyList<object> BuildQuickReplyItems(IReadOnlyList<string>? quickReplies)
    {
        if (quickReplies is null || quickReplies.Count == 0)
            return [];

        return quickReplies
            .Where(reply => !string.IsNullOrWhiteSpace(reply))
            .Select(reply => reply.Trim())
            .Distinct(StringComparer.Ordinal)
            .Take(3)
            .Select(reply => (object)new
            {
                type = "action",
                action = new
                {
                    type = "message",
                    label = reply,
                    text = reply
                }
            })
            .ToArray();
    }

    /// <summary>回覆 Flex Message</summary>
    public async Task ReplyFlexAsync(string replyToken, string altText, object contents, WebhookLogContext? logContext, CancellationToken ct = default)
    {
        await ReplyFlexAsync(replyToken, altText, contents, quickReplies: null, logContext, ct);
    }

    /// <summary>回覆 Flex Message 並附 quick replies</summary>
    public async Task ReplyFlexAsync(string replyToken, string altText, object contents, IReadOnlyList<string>? quickReplies, WebhookLogContext? logContext, CancellationToken ct = default)
    {
        var quickReplyItems = BuildQuickReplyItems(quickReplies);
        var flexMessage = BuildFlexMessage(altText, contents, quickReplyItems);

        var payload = new
        {
            replyToken,
            messages = new[] { flexMessage }
        };

        var request = new HttpRequestMessage(HttpMethod.Post, ReplyUrl)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _accessToken);

        var replyFailedRecorded = false;
        try
        {
            using var response = await _http.SendAsync(request, ct);
            if (!response.IsSuccessStatusCode)
            {
                replyFailedRecorded = true;
                _metrics.RecordReplyFailed((int)response.StatusCode);
                _logger.LogError(
                    "Failed to send LINE flex reply. EventId={EventId} HandlerType={HandlerType} MessageType={MessageType} SourceType={SourceType} StatusCode={StatusCode}",
                    logContext?.EventId,
                    logContext?.HandlerType,
                    logContext?.MessageType,
                    logContext?.SourceType,
                    (int)response.StatusCode);
                response.EnsureSuccessStatusCode();
            }

            _metrics.RecordReplySent(1);
            _logger.LogInformation(
                "Sent LINE flex reply. EventId={EventId} HandlerType={HandlerType} MessageType={MessageType} SourceType={SourceType}",
                logContext?.EventId,
                logContext?.HandlerType,
                logContext?.MessageType,
                logContext?.SourceType);
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            if (!replyFailedRecorded)
            {
                var statusCode = ex is HttpRequestException httpEx && httpEx.StatusCode is HttpStatusCode code
                    ? (int?)code
                    : null;
                _metrics.RecordReplyFailed(statusCode);
                _logger.LogError(
                    ex,
                    "Failed to send LINE flex reply. EventId={EventId} HandlerType={HandlerType} MessageType={MessageType} SourceType={SourceType} StatusCode={StatusCode}",
                    logContext?.EventId,
                    logContext?.HandlerType,
                    logContext?.MessageType,
                    logContext?.SourceType,
                    statusCode);
            }

            throw;
        }
    }

    private static object BuildFlexMessage(string altText, object contents, IReadOnlyList<object> quickReplyItems)
    {
        if (quickReplyItems is { Count: > 0 })
        {
            return new
            {
                type = "flex",
                altText,
                contents,
                quickReply = new { items = quickReplyItems }
            };
        }

        return new
        {
            type = "flex",
            altText,
            contents
        };
    }

    private static IReadOnlyList<string> SplitIntoLineMessages(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return ["(AI 無回應)"];

        var chunks = new List<string>(MaxLineMessagesPerReply);
        var remaining = text;

        while (remaining.Length > 0 && chunks.Count < MaxLineMessagesPerReply)
        {
            if (remaining.Length <= MaxLineTextLength)
            {
                chunks.Add(remaining);
                remaining = string.Empty;
                break;
            }

            var take = MaxLineTextLength;
            var splitAt = remaining.LastIndexOf('\n', take - 1, take);
            if (splitAt <= 0)
                splitAt = take;

            chunks.Add(remaining[..splitAt]);
            remaining = remaining[splitAt..].TrimStart('\n');
        }

        if (remaining.Length > 0 && chunks.Count > 0)
        {
            var last = chunks[^1];
            chunks[^1] = last.Length > MaxLineTextLength - 8
                ? last[..(MaxLineTextLength - 8)] + "\n...(略)"
                : last + "\n...(略)";
        }

        return chunks;
    }
}
