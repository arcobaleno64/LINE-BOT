namespace LineBotWebhook.Services;

/// <summary>AI 回覆服務介面，各 provider adapter 皆實作此介面</summary>
public interface IAiService
{
    /// <summary>依使用者訊息產生 AI 回覆</summary>
    Task<string> GetReplyAsync(string userMessage, CancellationToken ct = default);
}
