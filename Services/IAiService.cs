namespace LineBotWebhook.Services;

/// <summary>AI 回覆服務介面，各 provider adapter 皆實作此介面</summary>
public interface IAiService
{
    /// <summary>依使用者訊息產生 AI 回覆（帶對話記憶 key）</summary>
    Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default);
}
