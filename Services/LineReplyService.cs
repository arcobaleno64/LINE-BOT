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
        var chunks = SplitIntoLineMessages(text);
        var replyFailedRecorded = false;

        var payload = new
        {
            replyToken,
            messages = chunks.Select(x => new { type = "text", text = x }).ToArray()
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
                    "Failed to send LINE reply. StatusCode={StatusCode} MessageCount={MessageCount}",
                    (int)response.StatusCode,
                    chunks.Count);
                response.EnsureSuccessStatusCode();
            }

            _metrics.RecordReplySent(chunks.Count);
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
                    "Failed to send LINE reply. StatusCode={StatusCode} MessageCount={MessageCount}",
                    statusCode,
                    chunks.Count);
            }

            throw;
        }
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
