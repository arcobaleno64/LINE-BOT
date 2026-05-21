using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

public interface IAdvisoryPostbackHandler
{
    /// <summary>
    /// 嘗試處理諮詢卡片之 postback 動作（action=example/improve/research）。
    /// 回傳 true 表示已處理（並已回覆使用者），false 表示非本 handler 之 action。
    /// </summary>
    Task<bool> TryHandleAsync(LineEvent evt, IReadOnlyDictionary<string, string> parameters, CancellationToken ct);
}

public class AdvisoryPostbackHandler : IAdvisoryPostbackHandler
{
    private const string HandlerType = "advisory-postback";

    private readonly IAiService _ai;
    private readonly WebSearchService _webSearch;
    private readonly LineReplyService _reply;
    private readonly AdvisoryContextStore _contextStore;
    private readonly UserRequestThrottleService _throttle;
    private readonly Ai429BackoffService _aiBackoff;
    private readonly IConfiguration _config;
    private readonly IWebhookMetrics _metrics;
    private readonly ILogger<AdvisoryPostbackHandler> _logger;

    public AdvisoryPostbackHandler(
        IAiService ai,
        WebSearchService webSearch,
        LineReplyService reply,
        AdvisoryContextStore contextStore,
        UserRequestThrottleService throttle,
        Ai429BackoffService aiBackoff,
        IConfiguration config,
        IWebhookMetrics metrics,
        ILogger<AdvisoryPostbackHandler> logger)
    {
        _ai = ai;
        _webSearch = webSearch;
        _reply = reply;
        _contextStore = contextStore;
        _throttle = throttle;
        _aiBackoff = aiBackoff;
        _config = config;
        _metrics = metrics;
        _logger = logger;
    }

    public async Task<bool> TryHandleAsync(LineEvent evt, IReadOnlyDictionary<string, string> parameters, CancellationToken ct)
    {
        var action = parameters.GetValueOrDefault("action", string.Empty);
        if (action is not "example" and not "improve" and not "research")
            return false;

        if (string.IsNullOrEmpty(evt.ReplyToken))
            return true;

        var token = parameters.GetValueOrDefault("token", string.Empty);
        var context = _contextStore.Get(token);
        if (context is null)
        {
            await _reply.ReplyTextAsync(evt.ReplyToken, "此項建議的對話脈絡已過期（30 分鐘上限），請重新提問，我再依新內容協助。", ct);
            return true;
        }

        var userKey = MessageHandlerHelpers.BuildUserKey(evt);
        var logContext = WebhookLogContext.FromEvent(evt, HandlerType, userKey);

        if (!MessageHandlerHelpers.TryThrottle(_throttle, _config, userKey, "text", out var retryAfter))
        {
            _metrics.RecordThrottleRejected(HandlerType, "postback");
            await _reply.ReplyTextAsync(evt.ReplyToken, $"訊息有點密集，請在 {retryAfter} 秒後再試。", logContext, ct);
            return true;
        }

        switch (action)
        {
            case "research":
                await HandleResearchAsync(evt, context, logContext, ct);
                return true;
            case "example":
                await HandleAiPromptAsync(
                    evt,
                    userKey,
                    BuildExamplePrompt(context),
                    logContext,
                    ct);
                return true;
            case "improve":
                await HandleAiPromptAsync(
                    evt,
                    userKey,
                    BuildImprovePrompt(context),
                    logContext,
                    ct);
                return true;
        }

        return true;
    }

    private async Task HandleAiPromptAsync(LineEvent evt, string userKey, string prompt, WebhookLogContext logContext, CancellationToken ct)
    {
        var aiReply = await MessageHandlerHelpers.TryGetAiReplyAsync(
            () => _ai.GetReplyAsync(prompt, userKey, ct, enableQuickReplies: true),
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
            return;

        var parsed = QuickReplySuggestionParser.Parse(aiReply);
        await _reply.ReplyAiTextAsync(evt.ReplyToken!, parsed.MainText, parsed.Suggestions, logContext, ct);
    }

    private async Task HandleResearchAsync(LineEvent evt, AdvisoryContext context, WebhookLogContext logContext, CancellationToken ct)
    {
        var outcome = await _webSearch.TrySearchAsync(context.OriginalPrompt, ct);
        if (!outcome.Triggered || !outcome.Succeeded)
        {
            var message = string.IsNullOrWhiteSpace(outcome.Message)
                ? "依目前內容判斷無需網路搜尋，可逕行回覆原問題。"
                : outcome.Message;
            await _reply.ReplyTextAsync(evt.ReplyToken!, message, logContext, ct);
            return;
        }

        var sourceList = WebSearchService.BuildSourceList(outcome.Sources);
        var reply = $"已查到下列來源，供進一步討論：\n\n{sourceList}";
        await _reply.ReplyTextAsync(evt.ReplyToken!, reply, logContext, ct);
    }

    private static string BuildExamplePrompt(AdvisoryContext context)
    {
        return $"""
請對以下情境提供「一個具體可仿效之範例」。範例需包含：場景、做法、預期成效、與可能風險。
原始問題：
{context.OriginalPrompt}

先前結論：
{context.Conclusion}
""";
    }

    private static string BuildImprovePrompt(AdvisoryContext context)
    {
        return $"""
請針對以下情境，給出「3 至 5 條具體改進方向」。每條格式：動作、責任人或角色、驗收方式、量化指標（若有）。
不必再附蘇格拉底式追問，本回合僅列改進方向即可。
原始問題：
{context.OriginalPrompt}

先前結論：
{context.Conclusion}
""";
    }
}
