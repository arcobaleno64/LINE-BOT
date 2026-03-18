using LineBotWebhook.Models;

namespace LineBotWebhook.Services;

/// <summary>
/// 判斷群組訊息是否需要處理：
/// ‧source.type == "user" (1 對 1) → 一律處理
/// ‧source.type == "group" / "room" → 僅在 Bot 被 @mention 時處理
/// </summary>
public static class MentionGateService
{
    /// <summary>回傳 true 表示此事件應該被處理</summary>
    public static bool ShouldHandle(LineEvent evt)
    {
        // 非 message event 不處理
        if (evt.Type != "message" || evt.Message is null)
            return false;

        // 只處理 text 類型
        if (evt.Message.Type != "text")
            return false;

        var sourceType = evt.Source?.Type ?? "user";

        // 1 對 1 聊天一律處理
        if (sourceType == "user")
            return true;

        // 群組 / 聊天室：必須有 @mention 且 isSelf == true
        if (sourceType is "group" or "room")
        {
            return evt.Message.Mention?.Mentionees
                ?.Any(m => m.IsSelf) == true;
        }

        return false;
    }

    /// <summary>從訊息文字中移除 @Bot 顯示名稱，只保留使用者真正想說的話</summary>
    public static string StripMention(LineMessage message)
    {
        var text = message.Text ?? string.Empty;
        if (message.Mention?.Mentionees is null || message.Mention.Mentionees.Count == 0)
            return text.Trim();

        // 從後面往前移除，避免 index 偏移
        foreach (var m in message.Mention.Mentionees.OrderByDescending(m => m.Index))
        {
            if (m.IsSelf && m.Index >= 0 && m.Index + m.Length <= text.Length)
            {
                text = text.Remove(m.Index, m.Length);
            }
        }

        return text.Trim();
    }
}
