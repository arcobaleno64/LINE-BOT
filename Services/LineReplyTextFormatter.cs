using System.Text.RegularExpressions;

namespace LineBotWebhook.Services;

internal static class LineReplyTextFormatter
{
    private const string QuickRepliesStartTag = "<quick-replies>";
    private const string QuickRepliesEndTag = "</quick-replies>";
    private const string LineFriendlyOutputInstruction = "回覆需符合 LINE 純文字閱讀體驗：僅輸出純文字；不要使用 Markdown（例如 #、*、**、__、```、>、表格、[文字](連結)）。需要列點時請用「• 」，如需附連結請直接貼出完整 URL。";
    private const string QuickReplyInstruction = "回答結束後，若適合，可在回覆最後附上唯一格式：\\n\\n<quick-replies>[\"選項1\",\"選項2\"]</quick-replies>。最多 3 個選項，需短、自然、可直接點擊送出；若不適合提供，就不要附加任何 quick reply 區塊。";

    public static string BuildSystemPrompt(string basePrompt, bool enableQuickReplies)
    {
        var prompt = $"{basePrompt.TrimEnd()}\n{LineFriendlyOutputInstruction}";
        if (!enableQuickReplies)
            return prompt;

        return $"{prompt}\n{QuickReplyInstruction}";
    }

    public static string SanitizeForLine(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return text;

        var (beforeMetadata, metadata, afterMetadata) = SplitQuickReplyMetadata(text);
        var sanitized = SanitizeCore(beforeMetadata);

        if (metadata is null)
            return sanitized;

        return sanitized + metadata + SanitizeCore(afterMetadata);
    }

    private static (string Before, string? Metadata, string After) SplitQuickReplyMetadata(string text)
    {
        var start = text.LastIndexOf(QuickRepliesStartTag, StringComparison.Ordinal);
        if (start < 0)
            return (text, null, string.Empty);

        var end = text.IndexOf(QuickRepliesEndTag, start, StringComparison.Ordinal);
        if (end < 0)
            return (text, null, string.Empty);

        end += QuickRepliesEndTag.Length;
        return (text[..start], text[start..end], text[end..]);
    }

    private static string SanitizeCore(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return text;

        var sanitized = text.Replace("\r\n", "\n", StringComparison.Ordinal);

        sanitized = Regex.Replace(sanitized, @"\[(?<label>[^\]\r\n]+)\]\((?<url>https?://[^\s)]+)\)", "${label} (${url})");
        sanitized = Regex.Replace(sanitized, @"^\s{0,3}#{1,6}\s*", string.Empty, RegexOptions.Multiline);
        sanitized = Regex.Replace(sanitized, @"^\s{0,3}>\s?", string.Empty, RegexOptions.Multiline);
        sanitized = Regex.Replace(sanitized, @"^\s*[*+-]\s+", "• ", RegexOptions.Multiline);
        sanitized = Regex.Replace(sanitized, @"^\s*```[^\n]*\n?", string.Empty, RegexOptions.Multiline);
        sanitized = Regex.Replace(sanitized, @"\n?\s*```\s*$", string.Empty, RegexOptions.Multiline);

        sanitized = Regex.Replace(sanitized, @"(?<!\*)\*\*(.+?)\*\*(?!\*)", "$1");
        sanitized = Regex.Replace(sanitized, @"__(.+?)__", "$1");
        sanitized = Regex.Replace(sanitized, @"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", "$1");
        sanitized = Regex.Replace(sanitized, @"(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)", "$1");

        sanitized = Regex.Replace(sanitized, "\n{3,}", "\n\n");
        return sanitized.Trim();
    }
}