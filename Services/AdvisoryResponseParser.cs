using System.Text.RegularExpressions;

namespace LineBotWebhook.Services;

/// <summary>
/// 解析 AI 回覆中之諮詢三段制標記：&lt;conclusion&gt;／&lt;recommendations&gt;／&lt;questions&gt;。
/// 標記不存在時退回為純文字。Quick replies 由 <see cref="QuickReplySuggestionParser"/> 另行處理。
/// </summary>
public static class AdvisoryResponseParser
{
    private static readonly Regex ConclusionRegex = BuildSectionRegex("conclusion");
    private static readonly Regex RecommendationsRegex = BuildSectionRegex("recommendations");
    private static readonly Regex QuestionsRegex = BuildSectionRegex("questions");

    public static AdvisoryResponse Parse(string mainText)
    {
        if (string.IsNullOrWhiteSpace(mainText))
            return AdvisoryResponse.Plain(string.Empty);

        var conclusion = ExtractSection(mainText, ConclusionRegex);
        var recommendationsRaw = ExtractSection(mainText, RecommendationsRegex);
        var questionsRaw = ExtractSection(mainText, QuestionsRegex);

        if (conclusion is null && recommendationsRaw is null && questionsRaw is null)
            return AdvisoryResponse.Plain(mainText.Trim());

        var stripped = StripAllTags(mainText).Trim();

        return new AdvisoryResponse(
            IsStructured: true,
            Conclusion: conclusion?.Trim() ?? string.Empty,
            Recommendations: SplitBullets(recommendationsRaw),
            Questions: SplitBullets(questionsRaw),
            PlainFallback: BuildPlainFallback(conclusion, recommendationsRaw, questionsRaw, stripped));
    }

    private static Regex BuildSectionRegex(string tag)
        => new($"<{tag}>(?<body>.*?)</{tag}>",
            RegexOptions.IgnoreCase | RegexOptions.Singleline | RegexOptions.Compiled);

    private static string? ExtractSection(string text, Regex regex)
    {
        var match = regex.Match(text);
        return match.Success ? match.Groups["body"].Value : null;
    }

    private static string StripAllTags(string text)
    {
        var stripped = ConclusionRegex.Replace(text, string.Empty);
        stripped = RecommendationsRegex.Replace(stripped, string.Empty);
        stripped = QuestionsRegex.Replace(stripped, string.Empty);
        return stripped;
    }

    private static IReadOnlyList<string> SplitBullets(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
            return [];

        var lines = raw.Split('\n', StringSplitOptions.RemoveEmptyEntries);
        var bullets = new List<string>(lines.Length);
        foreach (var line in lines)
        {
            var trimmed = line.Trim();
            if (string.IsNullOrEmpty(trimmed))
                continue;
            // 移除常見項目符號開頭。
            trimmed = Regex.Replace(trimmed, @"^[•\-\*\+]\s+", string.Empty);
            trimmed = Regex.Replace(trimmed, @"^\d+[\.\)]\s+", string.Empty);
            if (!string.IsNullOrWhiteSpace(trimmed))
                bullets.Add(trimmed);
        }
        return bullets;
    }

    private static string BuildPlainFallback(string? conclusion, string? recommendationsRaw, string? questionsRaw, string stripped)
    {
        // 提供舊版客戶端與通知 altText 之純文字呈現。
        var parts = new List<string>(4);
        if (!string.IsNullOrWhiteSpace(conclusion))
            parts.Add($"結論：{conclusion.Trim()}");

        var recs = SplitBullets(recommendationsRaw);
        if (recs.Count > 0)
            parts.Add("改進方向：\n" + string.Join("\n", recs.Select(r => $"• {r}")));

        var qs = SplitBullets(questionsRaw);
        if (qs.Count > 0)
            parts.Add("追問：\n" + string.Join("\n", qs.Select(q => $"• {q}")));

        if (parts.Count == 0)
            return stripped;

        var combined = string.Join("\n\n", parts);
        // 若標記外仍有殘餘段落（例如教授閒話開頭），保留在最後。
        if (!string.IsNullOrWhiteSpace(stripped))
            combined = stripped + "\n\n" + combined;
        return combined;
    }
}

public sealed record AdvisoryResponse(
    bool IsStructured,
    string Conclusion,
    IReadOnlyList<string> Recommendations,
    IReadOnlyList<string> Questions,
    string PlainFallback)
{
    public static AdvisoryResponse Plain(string text)
        => new(IsStructured: false, Conclusion: string.Empty, Recommendations: [], Questions: [], PlainFallback: text);
}
