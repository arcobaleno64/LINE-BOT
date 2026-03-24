using System.Text.Json;

namespace LineBotWebhook.Services;

public static class QuickReplySuggestionParser
{
    private const string StartTag = "\n\n<quick-replies>";
    private const string EndTag = "</quick-replies>";
    private const int MaxSuggestions = 3;
    private const int MaxSuggestionLength = 24;

    public static QuickReplySuggestionResult Parse(string reply)
    {
        if (string.IsNullOrWhiteSpace(reply))
            return new QuickReplySuggestionResult("(AI 無回應)", []);

        var startIndex = reply.LastIndexOf(StartTag, StringComparison.Ordinal);
        if (startIndex < 0)
            return new QuickReplySuggestionResult(reply.Trim(), []);

        var cleanText = reply[..startIndex].TrimEnd();
        var endIndex = reply.IndexOf(EndTag, startIndex, StringComparison.Ordinal);
        if (endIndex < 0)
            return new QuickReplySuggestionResult(cleanText, []);

        var afterEnd = reply[(endIndex + EndTag.Length)..];
        if (!string.IsNullOrWhiteSpace(afterEnd))
            return new QuickReplySuggestionResult(cleanText, []);

        var payload = reply[(startIndex + StartTag.Length)..endIndex];

        try
        {
            var suggestions = JsonSerializer.Deserialize<string[]>(payload);
            return new QuickReplySuggestionResult(cleanText, SanitizeSuggestions(suggestions));
        }
        catch (JsonException)
        {
            return new QuickReplySuggestionResult(cleanText, []);
        }
    }

    private static IReadOnlyList<string> SanitizeSuggestions(IEnumerable<string?>? suggestions)
    {
        if (suggestions is null)
            return [];

        var accepted = new List<string>(MaxSuggestions);
        var seen = new HashSet<string>(StringComparer.Ordinal);

        foreach (var raw in suggestions)
        {
            var candidate = raw?.Trim();
            if (string.IsNullOrWhiteSpace(candidate))
                continue;

            if (candidate.Length > MaxSuggestionLength)
                continue;

            if (candidate.Contains('\n', StringComparison.Ordinal) || candidate.Contains('\r', StringComparison.Ordinal))
                continue;

            if (candidate.IndexOfAny(['<', '>', '[', ']', '{', '}', '"', '\\']) >= 0)
                continue;

            if (!seen.Add(candidate))
                continue;

            accepted.Add(candidate);
            if (accepted.Count == MaxSuggestions)
                break;
        }

        return accepted;
    }
}

public sealed record QuickReplySuggestionResult(string MainText, IReadOnlyList<string> Suggestions);
