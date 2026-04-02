using LineBotWebhook.Services;

namespace LineBotWebhook.Tests;

public class LineReplyTextFormatterTests
{
    [Fact]
    public void SanitizeForLine_RemovesMarkdownMarkers_AndNormalizesBulletsAndLinks()
    {
        var raw = "# 重點\n* **第一點**\n* 第二點\n詳見[文件](https://example.com/doc)";

        var sanitized = LineReplyTextFormatter.SanitizeForLine(raw);

        Assert.DoesNotContain("#", sanitized, StringComparison.Ordinal);
        Assert.DoesNotContain("**", sanitized, StringComparison.Ordinal);
        Assert.Contains("• 第一點", sanitized, StringComparison.Ordinal);
        Assert.Contains("• 第二點", sanitized, StringComparison.Ordinal);
        Assert.Contains("文件 (https://example.com/doc)", sanitized, StringComparison.Ordinal);
    }

    [Fact]
    public void SanitizeForLine_PreservesQuickRepliesBlockUntouched()
    {
        var raw = "**主回覆**\n\n<quick-replies>[\"  選項A  \",\"選項B\"]</quick-replies>";

        var sanitized = LineReplyTextFormatter.SanitizeForLine(raw);

        Assert.StartsWith("主回覆", sanitized, StringComparison.Ordinal);
        Assert.Contains("<quick-replies>[\"  選項A  \",\"選項B\"]</quick-replies>", sanitized, StringComparison.Ordinal);
    }
}
