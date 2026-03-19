using System.Net;
using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public class TextMessageHandler : ITextMessageHandler
{
    private readonly IConfiguration _config;
    private readonly IAiService _ai;
    private readonly AiResponseCacheService _aiCache;
    private readonly InFlightRequestMergeService _inFlightMerge;
    private readonly LineReplyService _reply;
    private readonly WebSearchService _webSearch;
    private readonly UserRequestThrottleService _throttle;
    private readonly Ai429BackoffService _aiBackoff;
    private readonly IDateTimeIntentResponder _dateTimeIntentResponder;
    private readonly ILogger<TextMessageHandler> _logger;

    public TextMessageHandler(
        IConfiguration config,
        IAiService ai,
        AiResponseCacheService aiCache,
        InFlightRequestMergeService inFlightMerge,
        LineReplyService reply,
        WebSearchService webSearch,
        UserRequestThrottleService throttle,
        Ai429BackoffService aiBackoff,
        IDateTimeIntentResponder dateTimeIntentResponder,
        ILogger<TextMessageHandler> logger)
    {
        _config = config;
        _ai = ai;
        _aiCache = aiCache;
        _inFlightMerge = inFlightMerge;
        _reply = reply;
        _webSearch = webSearch;
        _throttle = throttle;
        _aiBackoff = aiBackoff;
        _dateTimeIntentResponder = dateTimeIntentResponder;
        _logger = logger;
    }

    public async Task<bool> HandleAsync(LineEvent evt, string publicBaseUrl, CancellationToken ct)
    {
        if (evt.Message?.Type != "text")
            return false;

        if (!MentionGateService.ShouldHandle(evt))
            return true;

        var userText = MentionGateService.StripMention(evt.Message);
        if (string.IsNullOrWhiteSpace(userText))
        {
            await _reply.ReplyTextAsync(evt.ReplyToken!, "請問有什麼我能幫忙的嗎？", ct);
            return true;
        }

        _logger.LogInformation("Processing text message from {UserId}: {Text}", evt.Source?.UserId, userText);

        if (_dateTimeIntentResponder.TryBuildReply(userText, out var dateTimeReply))
        {
            await _reply.ReplyTextAsync(evt.ReplyToken!, dateTimeReply, ct);
            return true;
        }

        var userKey = BuildUserKey(evt);
        if (!TryThrottle(userKey, evt.Message.Type, out var retryAfter))
        {
            await _reply.ReplyTextAsync(evt.ReplyToken!, $"訊息有點密集，請在 {retryAfter} 秒後再試。", ct);
            return true;
        }

        var searchOutcome = await _webSearch.TrySearchAsync(userText, ct);
        if (searchOutcome.Triggered)
        {
            if (!searchOutcome.Succeeded)
            {
                await _reply.ReplyTextAsync(evt.ReplyToken!, searchOutcome.Message, ct);
                return true;
            }

            var prompt = $"""
你將收到使用者問題與網路搜尋摘要。
請綜合來源整理成精簡、實用的繁體中文回答。
若來源彼此衝突，請清楚說明不一致處。

使用者問題：{userText}

{searchOutcome.ContextForAi}
""";

            var webAiReply = await TryGetAiReplyAsync(() => _ai.GetReplyAsync(prompt, userKey, ct), evt.ReplyToken!, ct);
            if (webAiReply is null)
                return true;

            var sourceList = WebSearchService.BuildSourceList(searchOutcome.Sources);
            var finalReply = $"""
{webAiReply}

參考來源：
{sourceList}
""";

            await _reply.ReplyTextAsync(evt.ReplyToken!, finalReply, ct);
            return true;
        }

        var textReply = await GetMergedTextReplyAsync(userKey, userText, ct);
        await _reply.ReplyTextAsync(evt.ReplyToken!, textReply, ct);
        return true;
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

    private async Task<string> GetMergedTextReplyAsync(string userKey, string userText, CancellationToken ct)
    {
        var cacheKey = BuildTextCacheKey(userKey, userText);
        if (_aiCache.TryGet(cacheKey, out var cachedReply))
        {
            _logger.LogInformation("Returning cached AI reply for key {CacheKey}", cacheKey);
            return cachedReply;
        }

        var mergeKey = BuildTextMergeKey(userKey, userText);
        var mergeExecution = _inFlightMerge.JoinOrRun(mergeKey, async () =>
        {
            if (_aiCache.TryGet(cacheKey, out var hotCachedReply))
                return hotCachedReply;

            if (!_aiBackoff.TryPass(out var cooldownRemaining))
                return $"目前流量較高，請約 {cooldownRemaining} 秒後再試。";

            try
            {
                var aiReply = await _ai.GetReplyAsync(userText, userKey, ct);
                if (string.IsNullOrWhiteSpace(aiReply))
                    return "(AI 無回應)";

                var cacheTtlSeconds = GetIntConfig("App:AiResponseCacheSeconds", 180);
                _aiCache.Set(cacheKey, aiReply, cacheTtlSeconds);
                return aiReply;
            }
            catch (Exception ex) when (IsTooManyRequests(ex))
            {
                _logger.LogWarning(ex, "AI provider returned 429 Too Many Requests");
                if (IsQuotaExhausted(ex))
                {
                    var quotaCooldown = GetIntConfig("App:AiQuotaCooldownSeconds", 300);
                    _aiBackoff.Trigger(quotaCooldown);
                    return "今日 AI 配額已達上限，請稍後或明天再試。";
                }

                var cooldownSeconds = GetIntConfig("App:Ai429CooldownSeconds", 12);
                _aiBackoff.Trigger(cooldownSeconds);
                return "目前流量較高，稍後再試。";
            }
        });

        if (mergeExecution.JoinedExisting)
            _logger.LogInformation("Merged duplicate text request into existing in-flight call. Key: {MergeKey}", mergeKey);

        return await mergeExecution.Task;
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

    private string BuildTextMergeKey(string userKey, string userText)
    {
        var tz = ResolveTimeZone(_config["App:TimeZoneId"] ?? "Asia/Taipei");
        var windowSeconds = GetIntConfig("App:AiMergeWindowSeconds", 60);
        var now = TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, tz);
        var bucket = now.Ticks / TimeSpan.FromSeconds(windowSeconds).Ticks;
        return $"{userKey}:text:{NormalizeForIntent(userText)}:{bucket}";
    }

    private static string BuildUserKey(LineEvent evt)
    {
        var sourceId = evt.Source?.GroupId ?? evt.Source?.RoomId ?? evt.Source?.UserId ?? "unknown";
        var userId = evt.Source?.UserId ?? "unknown";
        return $"{sourceId}:{userId}";
    }

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
            .Replace("：", "")
            .Replace(":", "")
            .Replace("；", "")
            .Replace(";", "")
            .Replace("（", "")
            .Replace("）", "")
            .Replace("(", "")
            .Replace(")", "")
            .Replace("！", "")
            .Replace("!", "")
            .Replace(" ", "")
            .Replace("\t", "")
            .Replace("\n", "");
        return normalized;
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
