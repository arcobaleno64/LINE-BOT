using System.Text.RegularExpressions;

namespace LineBotWebhook.Services;

public class DateTimeIntentResponder : IDateTimeIntentResponder
{
    private readonly IConfiguration _config;

    private static readonly Regex TimeIntentRegex = new(
        @"(現在|目前|當前|此刻)?(時間|幾點|幾點了|幾點鐘|幾點幾分|幾點幾分幾秒)",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex DateIntentRegex = new(
        @"(今天|今日|明天|昨日|昨天|前天|後天)?(日期|幾月幾號|幾月幾日|幾號|年月日)",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    private static readonly Regex WeekdayIntentRegex = new(
        @"(今天|今日|明天|昨日|昨天|前天|後天)?(星期|禮拜|週)(幾|一|二|三|四|五|六|日|天)?",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);

    public DateTimeIntentResponder(IConfiguration config)
    {
        _config = config;
    }

    public bool TryBuildReply(string text, out string reply)
    {
        var normalized = NormalizeForIntent(text);
        var askTime = TimeIntentRegex.IsMatch(normalized);
        var askDate = DateIntentRegex.IsMatch(normalized);
        var askWeekday = WeekdayIntentRegex.IsMatch(normalized);

        if (!askTime && ContainsAny(normalized, "幾點", "時間"))
            askTime = true;
        if (!askDate && ContainsAny(normalized, "幾號", "幾月幾號", "日期"))
            askDate = true;
        if (!askWeekday && ContainsAny(normalized, "星期幾", "禮拜幾", "週幾"))
            askWeekday = true;

        if (!askTime && !askDate && !askWeekday)
        {
            reply = string.Empty;
            return false;
        }

        var tz = ResolveTimeZone(_config["App:TimeZoneId"] ?? "Asia/Taipei");
        var now = TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, tz);
        var dayOffset = DetectDayOffset(normalized);
        var target = now.Date.AddDays(dayOffset);
        var weekday = target.DayOfWeek switch
        {
            DayOfWeek.Sunday => "星期日",
            DayOfWeek.Monday => "星期一",
            DayOfWeek.Tuesday => "星期二",
            DayOfWeek.Wednesday => "星期三",
            DayOfWeek.Thursday => "星期四",
            DayOfWeek.Friday => "星期五",
            _ => "星期六"
        };

        var dayLabel = dayOffset switch
        {
            -2 => "前天",
            -1 => "昨天",
            0 => "今天",
            1 => "明天",
            2 => "後天",
            _ => "該日"
        };

        var lines = new List<string>();
        if (askTime)
            lines.Add($"現在時間：{now:HH:mm:ss}");
        if (askDate)
            lines.Add($"{dayLabel}日期：{target:yyyy 年 MM 月 dd 日}");
        if (askWeekday)
            lines.Add($"{dayLabel}：{weekday}");

        if (!askDate && !askWeekday)
            lines.Add($"日期：{target:yyyy 年 MM 月 dd 日}（{weekday}）");

        reply = string.Join("\n", lines);
        return true;
    }

    private static bool ContainsAny(string text, params string[] keywords)
        => keywords.Any(k => text.Contains(k, StringComparison.OrdinalIgnoreCase));

    private static string NormalizeForIntent(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return string.Empty;

        var normalized = text.Trim().ToLowerInvariant();
        normalized = normalized
            .Replace("？", "")
            .Replace("?", "")
            .Replace("，", "")
            .Replace(",", "")
            .Replace("。", "")
            .Replace("！", "")
            .Replace("!", "")
            .Replace(" ", "")
            .Replace("\t", "")
            .Replace("\n", "");
        return normalized;
    }

    private static int DetectDayOffset(string normalizedText)
    {
        if (ContainsAny(normalizedText, "前天")) return -2;
        if (ContainsAny(normalizedText, "昨天", "昨日")) return -1;
        if (ContainsAny(normalizedText, "明天")) return 1;
        if (ContainsAny(normalizedText, "後天")) return 2;
        return 0;
    }

    private static TimeZoneInfo ResolveTimeZone(string preferredTimeZoneId)
    {
        var candidates = new[] { preferredTimeZoneId, "Asia/Taipei", "Taipei Standard Time" };
        foreach (var id in candidates.Where(x => !string.IsNullOrWhiteSpace(x)).Distinct())
        {
            try
            {
                return TimeZoneInfo.FindSystemTimeZoneById(id);
            }
            catch (TimeZoneNotFoundException)
            {
            }
            catch (InvalidTimeZoneException)
            {
            }
        }

        return TimeZoneInfo.Local;
    }
}
