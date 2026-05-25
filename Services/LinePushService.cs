using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace LineBotWebhook.Services;

public enum PushResult { Accepted, Rejected, Conflict, QuotaBlocked, RateLimited, TargetNotFound }

public partial class LinePushService
{
    private const string PushUrl = "https://api.line.me/v2/bot/message/push";
    private const int MaxLineTextLength = 5000;
    private const int MaxMessagesPerPush = 5;

    private readonly HttpClient _http;
    private readonly string _accessToken;
    private readonly GroupRegistrationStore _store;
    private readonly IWebhookMetrics _metrics;
    private readonly ILogger<LinePushService> _logger;

    private int _monthlyPushCount;
    private int _monthlyBudget;
    private int _currentMonth;

    public LinePushService(
        HttpClient http,
        IConfiguration config,
        GroupRegistrationStore store,
        IWebhookMetrics metrics,
        ILogger<LinePushService> logger)
    {
        _http = http;
        var token = config["Line:ChannelAccessToken"];
        if (string.IsNullOrWhiteSpace(token))
            throw new InvalidOperationException("Missing Line:ChannelAccessToken");
        _accessToken = token;
        _store = store;
        _metrics = metrics;
        _logger = logger;
        _monthlyBudget = int.TryParse(config["App:PushMonthlyBudget"], out var b) ? b : 180;
        _currentMonth = DateTime.UtcNow.Month;
    }

    [GeneratedRegex(@"^C[0-9a-f]{32}$")]
    private static partial Regex GroupIdPattern();

    public static bool IsValidGroupId(string? targetId)
        => !string.IsNullOrEmpty(targetId) && GroupIdPattern().IsMatch(targetId);

    public async Task<PushResult> PushTextAsync(string targetId, string text, CancellationToken ct = default)
    {
        if (!IsValidGroupId(targetId))
            return PushResult.Rejected;

        var reg = await _store.GetAsync(targetId, ct);
        if (reg is null || !reg.Active || !reg.PushEnabled)
            return PushResult.TargetNotFound;

        var quotaLevel = GetQuotaLevel();
        if (quotaLevel == QuotaLevel.Disabled)
        {
            _logger.LogWarning("Push quota disabled. MonthlyCount={MonthlyCount} Budget={Budget}",
                _monthlyPushCount, _monthlyBudget);
            _metrics.RecordPushQuotaBlocked();
            return PushResult.QuotaBlocked;
        }

        var sanitized = LineReplyTextFormatter.SanitizeForLine(text);
        var chunks = SplitText(sanitized);
        var messages = chunks.Select(c => new { type = "text", text = c }).ToArray();

        var retryKey = Guid.NewGuid().ToString();
        var payload = new { to = targetId, messages };

        var request = new HttpRequestMessage(HttpMethod.Post, PushUrl)
        {
            Content = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json")
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", _accessToken);
        request.Headers.Add("X-Line-Retry-Key", retryKey);

        try
        {
            using var response = await _http.SendAsync(request, ct);

            if (response.StatusCode == HttpStatusCode.Conflict)
            {
                _logger.LogDebug("Push accepted (duplicate retry key). TargetId={TargetFingerprint} RetryKey={RetryKey}",
                    Fingerprint(targetId), retryKey);
                _metrics.RecordPushAccepted();
                return PushResult.Conflict;
            }

            if (response.StatusCode == HttpStatusCode.TooManyRequests)
            {
                _metrics.RecordPushRateLimited();
                _logger.LogWarning("Push rate limited by LINE. TargetId={TargetFingerprint}", Fingerprint(targetId));
                return PushResult.RateLimited;
            }

            if (response.StatusCode is HttpStatusCode.Forbidden or HttpStatusCode.NotFound)
            {
                _logger.LogWarning("Push target unreachable (bot may have left). TargetId={TargetFingerprint} StatusCode={StatusCode}",
                    Fingerprint(targetId), (int)response.StatusCode);
                await _store.SetPushEnabledAsync(targetId, false, ct);
                _metrics.RecordPushFailed((int)response.StatusCode);
                return PushResult.Rejected;
            }

            if (!response.IsSuccessStatusCode)
            {
                _metrics.RecordPushFailed((int)response.StatusCode);
                _logger.LogError("Push failed. TargetId={TargetFingerprint} StatusCode={StatusCode}",
                    Fingerprint(targetId), (int)response.StatusCode);
                return PushResult.Rejected;
            }

            IncrementMonthlyCount();
            _metrics.RecordPushAccepted();
            _logger.LogInformation("Push accepted. TargetId={TargetFingerprint} MessageCount={MessageCount} QuotaLevel={QuotaLevel}",
                Fingerprint(targetId), chunks.Count, quotaLevel);
            return PushResult.Accepted;
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            _metrics.RecordPushFailed(null);
            _logger.LogError(ex, "Push request exception. TargetId={TargetFingerprint}", Fingerprint(targetId));
            return PushResult.Rejected;
        }
    }

    public QuotaLevel GetQuotaLevel()
    {
        ResetIfNewMonth();
        var ratio = _monthlyBudget > 0 ? (double)_monthlyPushCount / _monthlyBudget : 1.0;
        return ratio switch
        {
            >= 0.95 => QuotaLevel.Disabled,
            >= 0.90 => QuotaLevel.AdminOnly,
            >= 0.80 => QuotaLevel.Warning,
            _ => QuotaLevel.Normal
        };
    }

    public int MonthlyPushCount => _monthlyPushCount;
    public int MonthlyBudget => _monthlyBudget;

    private void IncrementMonthlyCount()
    {
        ResetIfNewMonth();
        Interlocked.Increment(ref _monthlyPushCount);
    }

    private void ResetIfNewMonth()
    {
        var now = DateTime.UtcNow.Month;
        if (now != _currentMonth)
        {
            Interlocked.Exchange(ref _monthlyPushCount, 0);
            _currentMonth = now;
        }
    }

    private static IReadOnlyList<string> SplitText(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return ["(空白訊息)"];

        var chunks = new List<string>(MaxMessagesPerPush);
        var remaining = text;

        while (remaining.Length > 0 && chunks.Count < MaxMessagesPerPush)
        {
            if (remaining.Length <= MaxLineTextLength)
            {
                chunks.Add(remaining);
                break;
            }

            var splitAt = remaining.LastIndexOf('\n', MaxLineTextLength - 1, MaxLineTextLength);
            if (splitAt <= 0)
                splitAt = MaxLineTextLength;

            chunks.Add(remaining[..splitAt]);
            remaining = remaining[splitAt..].TrimStart('\n');
        }

        return chunks;
    }

    private static string Fingerprint(string id) => id.Length > 8 ? id[..4] + "…" + id[^4..] : "****";
}

public enum QuotaLevel { Normal, Warning, AdminOnly, Disabled }
