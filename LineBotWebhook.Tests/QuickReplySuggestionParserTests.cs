using LineBotWebhook.Services;

namespace LineBotWebhook.Tests;

public class QuickReplySuggestionParserTests
{
    [Fact]
    public void ValidMetadata_SplitsReplyText_AndSuggestions()
    {
        var result = QuickReplySuggestionParser.Parse("主回覆內容\n\n<quick-replies>[\"分析文件\",\"分析圖片\"]</quick-replies>");

        Assert.Equal("主回覆內容", result.MainText);
        Assert.Equal(["分析文件", "分析圖片"], result.Suggestions);
    }

    [Fact]
    public void LiteralEscapedNewlineMetadata_SplitsReplyText_AndSuggestions()
    {
        var result = QuickReplySuggestionParser.Parse("主回覆內容\\n\\n<quick-replies>[\"分析文件\",\"分析圖片\"]</quick-replies>");

        Assert.Equal("主回覆內容", result.MainText);
        Assert.Equal(["分析文件", "分析圖片"], result.Suggestions);
    }

    [Fact]
    public void MetadataWithLeadingSpaces_BeforeTag_SplitsReplyText_AndSuggestions()
    {
        var result = QuickReplySuggestionParser.Parse("主回覆內容   <quick-replies>[\"分析文件\",\"分析圖片\"]</quick-replies>");

        Assert.Equal("主回覆內容", result.MainText);
        Assert.Equal(["分析文件", "分析圖片"], result.Suggestions);
    }

    [Fact]
    public void MalformedMetadata_DropsSuggestions_AndDoesNotLeakTags()
    {
        var result = QuickReplySuggestionParser.Parse("主回覆內容\n\n<quick-replies>[\"分析文件\",</quick-replies>");

        Assert.Equal("主回覆內容", result.MainText);
        Assert.Empty(result.Suggestions);
    }

    [Fact]
    public void NoMetadata_ReturnsOriginalReply()
    {
        var result = QuickReplySuggestionParser.Parse("一般回覆");

        Assert.Equal("一般回覆", result.MainText);
        Assert.Empty(result.Suggestions);
    }

    [Fact]
    public void Filtering_AppliesLimit_Dedup_Length_AndCharacterRules()
    {
        var result = QuickReplySuggestionParser.Parse("主回覆\n\n<quick-replies>[\" 分析文件 \",\"分析文件\",\"這是一個超過二十四個字而且應該被直接捨棄的候選建議\",\"含\\n換行\",\"正常提問\",\"再問一個\",\"第四個\"]</quick-replies>");

        Assert.Equal("主回覆", result.MainText);
        Assert.Equal(["分析文件", "正常提問", "再問一個"], result.Suggestions);
    }

    [Fact]
    public void MarkdownMainText_StillParsesQuickRepliesMetadata()
    {
        var result = QuickReplySuggestionParser.Parse("# 標題\n* **重點**\n詳見[文件](https://example.com)\n\n<quick-replies>[\"分析文件\",\"再問一個\"]</quick-replies>");

        Assert.Equal("# 標題\n* **重點**\n詳見[文件](https://example.com)", result.MainText);
        Assert.Equal(["分析文件", "再問一個"], result.Suggestions);
    }
}
