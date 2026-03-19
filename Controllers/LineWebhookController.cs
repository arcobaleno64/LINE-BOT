using System.Security.Cryptography;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using LineBotWebhook.Models;
using LineBotWebhook.Services;
using Microsoft.AspNetCore.Mvc;

namespace LineBotWebhook.Controllers;

[ApiController]
[Route("api/line")]
public class LineWebhookController(
    IConfiguration config,
    IAiService ai,
    AiResponseCacheService aiCache,
    LineReplyService reply,
    LineContentService content,
    GeneratedFileService files,
    WebSearchService webSearch,
    UserRequestThrottleService throttle,
    Ai429BackoffService aiBackoff,
    ILogger<LineWebhookController> logger) : ControllerBase
{
    private readonly IConfiguration _config = config;
    private readonly string _channelSecret = config["Line:ChannelSecret"]
            ?? throw new InvalidOperationException("Missing Line:ChannelSecret");
    private readonly IAiService _ai = ai;
    private readonly AiResponseCacheService _aiCache = aiCache;
    private readonly LineReplyService _reply = reply;
    private readonly LineContentService _content = content;
    private readonly GeneratedFileService _files = files;
    private readonly WebSearchService _webSearch = webSearch;
    private readonly UserRequestThrottleService _throttle = throttle;
    private readonly Ai429BackoffService _aiBackoff = aiBackoff;
    private readonly ILogger<LineWebhookController> _logger = logger;

    private static readonly Regex TimeIntentRegex = new(
        @"(現在|目前|當前|此刻)?(時間|幾點|幾點了|幾點鐘|幾點幾分|幾點幾分幾秒)",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex DateIntentRegex = new(
        @"(今天|今日|明天|昨日|昨天|前天|後天)?(日期|幾月幾號|幾月幾日|幾號|年月日)",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex WeekdayIntentRegex = new(
        @"(今天|今日|明天|昨日|昨天|前天|後天)?(星期|禮拜|週)(幾|一|二|三|四|五|六|日|天)?",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);


    /// <summary>LINE Messaging API Webhook Endpoint</summary>
    [HttpPost("webhook")]
    public async Task<IActionResult> Webhook(CancellationToken ct)
    {
        // 1. 讀取 raw body
        using var reader = new StreamReader(Request.Body, Encoding.UTF8);
        var body = await reader.ReadToEndAsync(ct);

        // 2. 驗證 x-line-signature
        if (!VerifySignature(body, Request.Headers["x-line-signature"].ToString()))
        {
            _logger.LogWarning("Invalid LINE signature");
            return Unauthorized();
        }

        // 3. 反序列化
        var webhook = JsonSerializer.Deserialize<LineWebhookBody>(body);
        if (webhook?.Events is null || webhook.Events.Count == 0)
            return Ok();

        var publicBaseUrl = GetPublicBaseUrl();

        // 4. 處理每個 event（非同步 fire-and-forget，快速回 200 給 LINE）
        _ = Task.Run(async () =>
        {
            foreach (var evt in webhook.Events)
            {
                try
                {
                    await HandleEventAsync(evt, publicBaseUrl, CancellationToken.None);
                }
                catch (Exception ex)
                {
                    _logger.LogError(ex, "Error handling event {EventId}", evt.WebhookEventId);
                }
            }
        }, CancellationToken.None);

        return Ok();
    }

    private async Task HandleEventAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
        if (evt.Type != "message" || evt.Message is null)
            return;

        if (string.IsNullOrEmpty(evt.ReplyToken))
            return;

        // 組合 user key：群組/聊天室 + 使用者 ID
        var sourceId = evt.Source?.GroupId ?? evt.Source?.RoomId ?? evt.Source?.UserId ?? "unknown";
        var userId = evt.Source?.UserId ?? "unknown";
        var userKey = $"{sourceId}:{userId}";

        if (evt.Message.Type == "text")
        {
            if (!MentionGateService.ShouldHandle(evt))
                return;

            var userText = MentionGateService.StripMention(evt.Message);
            if (string.IsNullOrWhiteSpace(userText))
            {
                await _reply.ReplyTextAsync(evt.ReplyToken, "請問有什麼我能幫忙的嗎？", ct);
                return;
            }

            _logger.LogInformation("Processing text message from {UserId}: {Text}", evt.Source?.UserId, userText);

            if (TryBuildDateTimeReply(userText, out var dateTimeReply))
            {
                await _reply.ReplyTextAsync(evt.ReplyToken, dateTimeReply, ct);
                return;
            }

            if (!TryThrottle(userKey, evt.Message.Type, out var retryAfter))
            {
                await _reply.ReplyTextAsync(evt.ReplyToken, $"訊息有點密集，請在 {retryAfter} 秒後再試。", ct);
                return;
            }

            var searchOutcome = await _webSearch.TrySearchAsync(userText, ct);
            if (searchOutcome.Triggered)
            {
                if (!searchOutcome.Succeeded)
                {
                    await _reply.ReplyTextAsync(evt.ReplyToken, searchOutcome.Message, ct);
                    return;
                }

                var prompt = $"""
你將收到使用者問題與網路搜尋摘要。
請綜合來源整理成精簡、實用的繁體中文回答。
若來源彼此衝突，請清楚說明不一致處。

使用者問題：{userText}

{searchOutcome.ContextForAi}
""";

                var webAiReply = await TryGetAiReplyAsync(() => _ai.GetReplyAsync(prompt, userKey, ct), evt.ReplyToken, ct);
                if (webAiReply is null)
                    return;

                var sourceList = WebSearchService.BuildSourceList(searchOutcome.Sources);
                var finalReply = $"""
{webAiReply}

參考來源：
{sourceList}
""";

                await _reply.ReplyTextAsync(evt.ReplyToken, finalReply, ct);
                return;
            }

            var aiReply = await TryGetAiReplyAsync(
                () => _ai.GetReplyAsync(userText, userKey, ct),
                evt.ReplyToken,
                userKey,
                userText,
                ct);
            if (aiReply is null)
                return;

            await _reply.ReplyTextAsync(evt.ReplyToken, aiReply, ct);
            return;
        }

        if (evt.Message.Type == "image")
        {
            if (evt.Source?.Type is "group" or "room")
                return;

            if (!TryThrottle(userKey, evt.Message.Type, out var retryAfter))
            {
                await _reply.ReplyTextAsync(evt.ReplyToken, $"訊息有點密集，請在 {retryAfter} 秒後再試。", ct);
                return;
            }

            _logger.LogInformation("Processing image message from {UserId}", evt.Source?.UserId);
            var (bytes, mimeType) = await _content.DownloadMessageContentAsync(evt.Message.Id, ct);
            var aiReply = await TryGetAiReplyAsync(
                () => _ai.GetReplyFromImageAsync(bytes, mimeType, "請幫我分析這張圖片重點。", userKey, ct),
                evt.ReplyToken,
                ct);
            if (aiReply is null)
                return;

            await _reply.ReplyTextAsync(evt.ReplyToken, aiReply, ct);
            return;
        }

        if (evt.Message.Type == "file")
        {
            if (evt.Source?.Type is "group" or "room")
                return;

            if (!TryThrottle(userKey, evt.Message.Type, out var retryAfter))
            {
                await _reply.ReplyTextAsync(evt.ReplyToken, $"訊息有點密集，請在 {retryAfter} 秒後再試。", ct);
                return;
            }

            _logger.LogInformation("Processing file message from {UserId}", evt.Source?.UserId);
            var (bytes, mimeType) = await _content.DownloadMessageContentAsync(evt.Message.Id, ct);
            var fileName = evt.Message.FileName ?? "uploaded-file";

            string extractedText;
            try
            {
                extractedText = _content.ExtractTextFromFile(bytes, fileName, mimeType);
            }
            catch (NotSupportedException ex)
            {
                await _reply.ReplyTextAsync(evt.ReplyToken, ex.Message, ct);
                return;
            }

            var aiReply = await TryGetAiReplyAsync(
                () => _ai.GetReplyFromDocumentAsync(fileName, mimeType, extractedText, "請幫我整理重點、關鍵結論與待辦事項。", userKey, ct),
                evt.ReplyToken,
                ct);
            if (aiReply is null)
                return;

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

            await _reply.ReplyTextAsync(evt.ReplyToken, replyText, ct);
            return;
        }

        if (evt.Source?.Type == "user")
        {
            await _reply.ReplyTextAsync(evt.ReplyToken, "目前我支援文字、圖片與檔案（txt/md/csv/json/xml/log/pdf）。PDF 目前先支援文字型 PDF。", ct);
        }
    }

    private async Task<string?> TryGetAiReplyAsync(Func<Task<string>> aiCall, string replyToken, CancellationToken ct)
    {
        if (!_aiBackoff.TryPass(out var cooldownRemaining))
        {
            await _reply.ReplyTextAsync(replyToken, $"目前流量較高，請約 {cooldownRemaining} 秒後再試。", ct);
            return null;
        }

        try
        {
            return await aiCall();
        }
        catch (Exception ex) when (IsTooManyRequests(ex))
        {
            _logger.LogWarning(ex, "AI provider returned 429 Too Many Requests");
            if (IsQuotaExhausted(ex))
            {
                var quotaCooldown = GetIntConfig("App:AiQuotaCooldownSeconds", 300);
                _aiBackoff.Trigger(quotaCooldown);
                await _reply.ReplyTextAsync(replyToken, "今日 AI 配額已達上限，請稍後或明天再試。", ct);
                return null;
            }

            var cooldownSeconds = GetIntConfig("App:Ai429CooldownSeconds", 12);
            _aiBackoff.Trigger(cooldownSeconds);
            await _reply.ReplyTextAsync(replyToken, "目前流量較高，稍後再試。", ct);
            return null;
        }
    }

    private async Task<string?> TryGetAiReplyAsync(Func<Task<string>> aiCall, string replyToken, string userKey, string userText, CancellationToken ct)
    {
        var cacheKey = BuildTextCacheKey(userKey, userText);
        if (_aiCache.TryGet(cacheKey, out var cachedReply))
        {
            _logger.LogInformation("Returning cached AI reply for key {CacheKey}", cacheKey);
            return cachedReply;
        }

        var aiReply = await TryGetAiReplyAsync(aiCall, replyToken, ct);
        if (string.IsNullOrWhiteSpace(aiReply))
            return aiReply;

        var cacheTtlSeconds = GetIntConfig("App:AiResponseCacheSeconds", 180);
        _aiCache.Set(cacheKey, aiReply, cacheTtlSeconds);
        return aiReply;
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

    private static string BuildTextCacheKey(string userKey, string userText)
        => $"{userKey}:text:{NormalizeForIntent(userText)}";

    /// <summary>HMAC-SHA256 簽章驗證</summary>
    private bool VerifySignature(string body, string signature)
    {
        if (string.IsNullOrEmpty(signature))
            return false;

        var key  = Encoding.UTF8.GetBytes(_channelSecret);
        var data = Encoding.UTF8.GetBytes(body);

        using var hmac = new HMACSHA256(key);
        var hash = hmac.ComputeHash(data);
        var computed = Convert.ToBase64String(hash);

        return CryptographicOperations.FixedTimeEquals(
            Encoding.UTF8.GetBytes(computed),
            Encoding.UTF8.GetBytes(signature));
    }

    private string GetPublicBaseUrl()
    {
        var configured = _config["App:PublicBaseUrl"];
        if (!string.IsNullOrWhiteSpace(configured))
            return configured.TrimEnd('/');

        var proto = Request.Headers["x-forwarded-proto"].ToString();
        if (string.IsNullOrWhiteSpace(proto))
            proto = Request.Scheme;

        return $"{proto}://{Request.Host}".TrimEnd('/');
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

    private bool TryBuildDateTimeReply(string text, out string reply)
    {
        var normalized = NormalizeForIntent(text);
        var askTime = TimeIntentRegex.IsMatch(normalized);
        var askDate = DateIntentRegex.IsMatch(normalized);
        var askWeekday = WeekdayIntentRegex.IsMatch(normalized);

        // 常見簡短問法補強
        if (!askTime && ContainsAny(normalized, "幾點", "時間"))
            askTime = true;
        if (!askDate && ContainsAny(normalized, "幾號", "幾月幾號", "日期"))
            askDate = true;
        if (!askWeekday && ContainsAny(normalized, "星期幾", "禮拜幾", "週幾"))
            askWeekday = true;

        if (!askTime && !askDate && !askWeekday)
        {
            reply = string.Empty;
            return false;
        }

        var tz = ResolveTimeZone(_config["App:TimeZoneId"] ?? "Asia/Taipei");
        var now = TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, tz);
        var dayOffset = DetectDayOffset(normalized);
        var target = now.Date.AddDays(dayOffset);
        var weekday = target.DayOfWeek switch
        {
            DayOfWeek.Sunday => "星期日",
            DayOfWeek.Monday => "星期一",
            DayOfWeek.Tuesday => "星期二",
            DayOfWeek.Wednesday => "星期三",
            DayOfWeek.Thursday => "星期四",
            DayOfWeek.Friday => "星期五",
            _ => "星期六"
        };

        var dayLabel = dayOffset switch
        {
            -2 => "前天",
            -1 => "昨天",
            0 => "今天",
            1 => "明天",
            2 => "後天",
            _ => "該日"
        };

        var lines = new List<string>();
        if (askTime)
            lines.Add($"現在時間：{now:HH:mm:ss}");
        if (askDate)
            lines.Add($"{dayLabel}日期：{target:yyyy 年 MM 月 dd 日}");
        if (askWeekday)
            lines.Add($"{dayLabel}：{weekday}");

        if (!askDate && !askWeekday)
            lines.Add($"日期：{target:yyyy 年 MM 月 dd 日}（{weekday}）");

        reply = string.Join("\n", lines);
        return true;
    }

    private static bool ContainsAny(string text, params string[] keywords)
        => keywords.Any(k => text.Contains(k, StringComparison.OrdinalIgnoreCase));

    private static string NormalizeForIntent(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return string.Empty;

        var normalized = text.Trim().ToLowerInvariant();
        normalized = normalized
            .Replace("？", "")
            .Replace("?", "")
            .Replace("，", "")
            .Replace(",", "")
            .Replace("。", "")
            .Replace("！", "")
            .Replace("!", "")
            .Replace(" ", "")
            .Replace("\t", "")
            .Replace("\n", "");
        return normalized;
    }

    private static int DetectDayOffset(string normalizedText)
    {
        if (ContainsAny(normalizedText, "前天")) return -2;
        if (ContainsAny(normalizedText, "昨天", "昨日")) return -1;
        if (ContainsAny(normalizedText, "明天")) return 1;
        if (ContainsAny(normalizedText, "後天")) return 2;
        return 0;
    }

    private static TimeZoneInfo ResolveTimeZone(string preferredTimeZoneId)
    {
        var candidates = new[] { preferredTimeZoneId, "Asia/Taipei", "Taipei Standard Time" };
        foreach (var id in candidates.Where(x => !string.IsNullOrWhiteSpace(x)).Distinct())
        {
            try
            {
                return TimeZoneInfo.FindSystemTimeZoneById(id);
            }
            catch (TimeZoneNotFoundException)
            {
            }
            catch (InvalidTimeZoneException)
            {
            }
        }

        return TimeZoneInfo.Local;
    }
}
