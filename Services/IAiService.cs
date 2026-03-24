namespace LineBotWebhook.Services;

/// <summary>AI 回覆服務介面，各 provider adapter 皆實作此介面</summary>
public interface IAiService
{
    /// <summary>依使用者訊息產生 AI 回覆（帶對話記憶 key）</summary>
    Task<string> GetReplyAsync(string userMessage, string userKey, CancellationToken ct = default, bool enableQuickReplies = false);

    /// <summary>依圖片內容產生 AI 回覆（可附使用者提示）</summary>
    Task<string> GetReplyFromImageAsync(byte[] imageBytes, string mimeType, string userPrompt, string userKey, CancellationToken ct = default);

    /// <summary>依檔案內容（已抽出的文字）產生 AI 回覆</summary>
    Task<string> GetReplyFromDocumentAsync(string fileName, string mimeType, string extractedText, string userPrompt, string userKey, CancellationToken ct = default);
}
