using LineBotWebhook.Services;

namespace LineBotWebhook.Services;

/// <summary>
/// 建構 LINE Flex Message JSON 結構（使用匿名物件，由 JsonSerializer 序列化）。
/// </summary>
public static class FlexMessageBuilder
{
    private const int MaxFlexBodyLength = 2000;

    /// <summary>文件摘要卡片</summary>
    public static object BuildDocumentSummaryBubble(string fileName, string summary, string downloadUrl)
    {
        var displaySummary = Truncate(summary, MaxFlexBodyLength);

        return new
        {
            type = "bubble",
            header = new
            {
                type = "box",
                layout = "vertical",
                contents = new object[]
                {
                    new { type = "text", text = "\U0001f4c4 文件摘要", weight = "bold", size = "lg", color = "#1DB446" }
                },
                paddingBottom = "sm"
            },
            body = new
            {
                type = "box",
                layout = "vertical",
                contents = new object[]
                {
                    new { type = "text", text = fileName, weight = "bold", size = "sm", color = "#666666" },
                    new { type = "separator", margin = "md" },
                    new { type = "text", text = displaySummary, wrap = true, size = "sm", margin = "md" }
                }
            },
            footer = new
            {
                type = "box",
                layout = "vertical",
                spacing = "sm",
                contents = new object[]
                {
                    new
                    {
                        type = "button",
                        action = new { type = "uri", label = "下載整理檔", uri = downloadUrl },
                        style = "primary",
                        color = "#1DB446"
                    }
                }
            }
        };
    }

    /// <summary>搜尋結果卡片</summary>
    public static object BuildSearchResultBubble(
        string aiAnswer,
        IReadOnlyList<WebSearchService.SearchSource> sources)
    {
        var displayAnswer = Truncate(aiAnswer, MaxFlexBodyLength);

        var footerContents = new List<object>();
        var maxSourceButtons = Math.Min(sources.Count, 3);
        for (var i = 0; i < maxSourceButtons; i++)
        {
            var src = sources[i];
            var label = TruncateLabel(src.Title, 40);
            footerContents.Add(new
            {
                type = "button",
                action = new { type = "uri", label, uri = src.Url },
                style = "link",
                height = "sm"
            });
        }

        if (sources.Count > 3)
        {
            footerContents.Add(new
            {
                type = "text",
                text = $"...其他 {sources.Count - 3} 筆來源",
                size = "xs",
                color = "#AAAAAA",
                align = "center",
                margin = "sm"
            });
        }

        return new
        {
            type = "bubble",
            header = new
            {
                type = "box",
                layout = "vertical",
                contents = new object[]
                {
                    new { type = "text", text = "\U0001f50d 搜尋結果", weight = "bold", size = "lg", color = "#0066FF" }
                },
                paddingBottom = "sm"
            },
            body = new
            {
                type = "box",
                layout = "vertical",
                contents = new object[]
                {
                    new { type = "text", text = displayAnswer, wrap = true, size = "sm" }
                }
            },
            footer = footerContents.Count > 0
                ? (object)new
                {
                    type = "box",
                    layout = "vertical",
                    spacing = "sm",
                    contents = footerContents.ToArray()
                }
                : new
                {
                    type = "box",
                    layout = "vertical",
                    contents = new object[]
                    {
                        new { type = "text", text = "(無來源)", size = "xs", color = "#AAAAAA", align = "center" }
                    }
                }
        };
    }

    /// <summary>建構 altText（截取前 400 字作為通知 / 舊版用戶顯示文字）</summary>
    public static string BuildAltText(string mainText, int maxLength = 400)
    {
        if (string.IsNullOrWhiteSpace(mainText))
            return "(載入中)";

        return mainText.Length <= maxLength
            ? mainText
            : mainText[..maxLength] + "...";
    }

    internal static string Truncate(string text, int maxLength)
    {
        if (string.IsNullOrWhiteSpace(text))
            return "(無內容)";

        return text.Length <= maxLength
            ? text
            : text[..(maxLength - 6)] + "\n...(略)";
    }

    private static string TruncateLabel(string text, int maxLength)
    {
        if (string.IsNullOrWhiteSpace(text))
            return "查看來源";

        return text.Length <= maxLength
            ? text
            : text[..(maxLength - 3)] + "...";
    }
}
